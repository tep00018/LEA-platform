"""
Simple Tutor System for LEA
Provides guided tutoring through learning objectives with adaptive scaffolding
UPDATED: Integrates sophisticated scaffolding engine (conceptual, procedural, strategic, metacognitive)
"""

import json
import logging
import re

from src.core import grading
from src.core import scaffolding_model
from src.core.llm import complete
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime
from pydantic import BaseModel, Field
from enum import Enum

logger = logging.getLogger(__name__)

class ScaffoldingLevel(Enum):
    """Scaffolding intensity levels"""
    VERY_HIGH = "very_high"
    HIGH = "high"
    MEDIUM = "medium" 
    LOW = "low"
    MINIMAL = "minimal"

class ScaffoldingStrategy(Enum):
    """Scaffolding strategies from engine"""
    CONCEPTUAL = "conceptual"
    PROCEDURAL = "procedural"
    STRATEGIC = "strategic"
    METACOGNITIVE = "metacognitive"

class TutorSession(BaseModel):
    """One tutoring session. Plain data (JSON-serialisable) so it can be stored between requests."""
    session_id: str
    username: str
    course: str
    week: int
    go_list: List[Dict[str, Any]]
    current_go_index: int = 0
    conversation_history: List[Dict[str, Any]] = Field(default_factory=list)
    
    # UPDATED: Track both strategy and intensity
    scaffolding_strategy: str = "procedural"  # Default strategy
    scaffolding_intensity: str = "medium"     # Default intensity
    scaffolding_level: str = "medium"         # Keep for backwards compatibility
    
    correct_count: int = 0
    incorrect_count: int = 0
    consecutive_correct: int = 0
    consecutive_incorrect: int = 0
    interaction_count: int = 0
    go_interaction_count: int = 0  # attempts on the current GO; resets when the GO changes
    awaiting_diagnostic: bool = True  # the first reply answers "what do you already know?"
    start_time: datetime = Field(default_factory=datetime.now)
    mastery_scores: Dict[str, float] = Field(default_factory=dict)
    current_mastery: float = 0.0
    requires_review: bool = False
    review_concepts: List[str] = Field(default_factory=list)
    # Notes on a quiz the learner just took, when they opened the session to review it
    # ("Review with the tutor"). Only steers the tutor's wording; grading doesn't read it.
    quiz_review: Optional[str] = None
    # Where the video help shown on the latest reply came from: curated (an instructor's list),
    # search:api / search:cache / search-link (automatic search), or fallback (generic links).
    last_help_source: Optional[str] = None

class SimpleTutorSystem:
    """Simple tutor system with adaptive scaffolding and GO-based progression"""
    
    def __init__(self, openai_client, redis_client=None, mcp_client=None, curated_videos=None):
        """Initialize tutor system

        Args:
            openai_client: OpenAI client for generating responses
            redis_client: Optional Redis client for caching
            mcp_client: Optional MCP client for YouTube/tool integration
            curated_videos: Optional ``(course, go_id) -> [video]``: the instructor's videos
                for an objective, preferred over any automatic search
        """
        self.openai_client = openai_client
        self.redis_client = redis_client
        self.mcp_client = mcp_client
        self.curated_videos = curated_videos
        
        # UPDATED: Strategy-specific scaffolding templates
        self.scaffolding_templates = {
            'conceptual': {
                'focus': "Understanding core concepts and relationships",
                'intro': "Let's explore the fundamental concepts behind this.",
                'hint': "Think about the underlying principle: ",
                'example': "Here's a conceptual model: ",
                'check': "How do these concepts relate? ",
                'feedback_style': "Focus on WHY and HOW things work",
                'prompt_guidance': "Use analogies, concept maps, and explain relationships between ideas"
            },
            'procedural': {
                'focus': "Step-by-step problem solving processes",
                'intro': "Let me walk you through this step by step.",
                'hint': "The next step is: ",
                'example': "Here's a worked example: ",
                'check': "Can you complete the next step? ",
                'feedback_style': "Focus on WHAT to do NEXT",
                'prompt_guidance': "Provide clear sequential steps, worked examples, and procedural guidance"
            },
            'strategic': {
                'focus': "Problem-solving strategies and approaches",
                'intro': "Let's think about different approaches to this.",
                'hint': "Consider this strategy: ",
                'example': "You could approach it like: ",
                'check': "Which approach would work best here? ",
                'feedback_style': "Focus on evaluating different approaches",
                'prompt_guidance': "Compare strategies, discuss trade-offs, help choose best approach"
            },
            'metacognitive': {
                'focus': "Self-reflection and learning awareness",
                'intro': "Let's reflect on your learning process.",
                'hint': "Think about your thinking: ",
                'example': "Reflect on how you approached this: ",
                'check': "What's your confidence level and why? ",
                'feedback_style': "Focus on the learning process itself",
                'prompt_guidance': "Encourage self-reflection, confidence assessment, learning strategy evaluation"
            }
        }
        
        # Intensity modifiers for prompts
        self.intensity_modifiers = {
            'very_high': "Provide maximum support with detailed explanations, multiple examples, and break everything into tiny steps",
            'high': "Give substantial support with clear explanations and examples",
            'medium': "Balance support with independent thinking opportunities",
            'low': "Provide minimal hints and encourage independent problem-solving",
            'minimal': "Only intervene when absolutely necessary"
        }
        
        logger.info(f"SimpleTutorSystem initialized with MCP client: {mcp_client is not None}")
        
    def start_tutoring_session(
        self,
        course: str,
        week: int,
        username: str,
        kc_loader=None,  # unused; kept for callers that still pass it
        go_list: List[Dict[str, Any]] = (),
        orchestrator_context: Optional[Dict] = None,
        quiz_review: Optional[str] = None,
        review_intro: Optional[str] = None,
        adaptive_start: bool = True,
    ) -> TutorSession:
        """Start a new tutoring session with GO-based progression. ``quiz_review`` (notes on a
        quiz just taken) goes into every reply's prompt; ``review_intro`` opens the first message.
        With ``adaptive_start`` (the default) the session begins at the first objective the learner
        has not mastered; pass False when ``go_list`` is already the list to teach, in order."""
        
        session_id = f"tutor_{username}_{course}_{week}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Initialize session
        session = TutorSession(
            session_id=session_id,
            username=username,
            course=course,
            week=week,
            go_list=list(go_list),
            quiz_review=quiz_review,
        )
        
        # UPDATED: Apply initial scaffolding from orchestrator if available
        if orchestrator_context and 'scaffolding_strategy' in orchestrator_context:
            self._apply_scaffolding_decision(session, orchestrator_context['scaffolding_strategy'])
        
        # Initialize mastery scores for each GO
        for go in go_list:
            go_id = go.get('go_id', f'GO_{len(session.mastery_scores)}')
            session.mastery_scores[go_id] = 0.0
        
        # Check for adaptive start based on prior mastery
        if self.redis_client:
            session = self._check_prior_mastery(session)
        if not adaptive_start:
            session.current_go_index = 0

        # Generate initial message
        initial_message = self._generate_initial_message(session, orchestrator_context, review_intro)
        
        session.conversation_history.append({
            "role": "tutor",
            "content": initial_message,
            "timestamp": datetime.now().isoformat(),
            "go_id": session.go_list[session.current_go_index].get('go_id') if session.go_list else None,
            "scaffolding_strategy": session.scaffolding_strategy,
            "scaffolding_intensity": session.scaffolding_intensity
        })
        
        logger.info(f"Started tutoring session {session_id} for {username} with {len(go_list)} GOs")
        logger.info(f"Initial scaffolding: {session.scaffolding_strategy} at {session.scaffolding_intensity} intensity")
        return session
        
    def process_student_response(
        self,
        session: TutorSession,
        student_input: str,
        rag_content: Optional[str] = None,
        orchestrator_context: Optional[Dict] = None,
        on_token=None,
    ) -> Dict[str, Any]:
        """Grade the reply, then generate the tutor's answer (streamed through ``on_token``
        if given; the returned ``message`` is always the full, final text)."""
        
        try:
            if session.current_go_index >= len(session.go_list):
                return self._get_completed_response(session)

            session.interaction_count += 1
            session.go_interaction_count += 1
            current_go = session.go_list[session.current_go_index]
            go_id = current_go.get('go_id', f'GO_{session.current_go_index}')
            
            # Add student response to history
            session.conversation_history.append({
                "role": "student",
                "content": student_input,
                "timestamp": datetime.now().isoformat(),
                "go_id": go_id
            })
            
            # Grade the response against the objective (LLM grader; heuristic only if grading fails)
            is_correct, mastery_score, evaluation_details = self._evaluate_response_enhanced(
                student_input,
                current_go,
                session
            )
            is_graded = evaluation_details.get('graded', False)

            # The first reply answers the opening "what do you already know?" probe. It can
            # move the learner on if it already shows mastery, but it is not recorded as
            # graded evidence, so an honest "not sure yet" doesn't count against them.
            diagnostic = session.awaiting_diagnostic
            session.awaiting_diagnostic = False
            
            # Update mastery for current GO
            session.mastery_scores[go_id] = mastery_score
            session.current_mastery = mastery_score
            
            # Update session tracking
            if is_correct:
                session.correct_count += 1
                session.consecutive_correct += 1
                session.consecutive_incorrect = 0
            else:
                session.incorrect_count += 1
                session.consecutive_incorrect += 1
                session.consecutive_correct = 0
                
                # Track concepts that need review
                if session.consecutive_incorrect >= 2:
                    session.requires_review = True
                    if go_id not in session.review_concepts:
                        session.review_concepts.append(go_id)
            
            logger.debug(f"Evaluation: Correct={is_correct}, Mastery={mastery_score:.2f}, "
                        f"Consecutive incorrect={session.consecutive_incorrect}")
            
            # UPDATED: Apply scaffolding from orchestrator
            if orchestrator_context and 'scaffolding_strategy' in orchestrator_context:
                self._apply_scaffolding_decision(session, orchestrator_context['scaffolding_strategy'])
                logger.info(f"Applied orchestrator scaffolding: {session.scaffolding_strategy} "
                           f"at {session.scaffolding_intensity} intensity")
            
            # Video help once per stuck streak: when the streak reaches 3 wrong answers in a row, not
            # again on every wrong reply after that (a correct answer or a new objective resets it).
            youtube_content = None
            session.last_help_source = None
            if session.consecutive_incorrect == 3:
                logger.info(f"🎥 YouTube TRIGGERED: {session.consecutive_incorrect} consecutive incorrect")
                if self.mcp_client or self.curated_videos:
                    youtube_content = self._get_youtube_help(session)
            
            # Generate adaptive tutor response
            tutor_message = self._generate_adaptive_response(
                session=session,
                student_input=student_input,
                is_correct=is_correct,
                mastery_score=mastery_score,
                evaluation_details=evaluation_details,
                rag_content=rag_content,
                orchestrator_context=orchestrator_context,
                youtube_content=youtube_content,
                on_token=on_token,
            )

            # Add tutor response to history
            session.conversation_history.append({
                "role": "tutor",
                "content": tutor_message,
                "timestamp": datetime.now().isoformat(),
                "go_id": go_id,
                "scaffolding_strategy": session.scaffolding_strategy,
                "scaffolding_intensity": session.scaffolding_intensity,
                "scaffolding_level": session.scaffolding_intensity  # For backwards compatibility
            })
            
            # Advance on a graded correct answer that reaches the GO's mastery threshold, or on
            # a graded correct answer after three attempts at this GO. Ungraded turns never advance.
            threshold = current_go.get('mastery_threshold', 0.8)
            has_achieved_mastery = is_graded and is_correct and mastery_score >= threshold
            if diagnostic:
                should_advance = has_achieved_mastery
            else:
                should_advance = has_achieved_mastery or (
                    is_graded and is_correct and session.go_interaction_count >= 3
                )
            
            # Handle GO progression
            session_complete = False
            next_go_info = None
            
            if should_advance:
                session.current_go_index += 1
                session.go_interaction_count = 0
                session.consecutive_correct = 0
                session.consecutive_incorrect = 0
                
                if session.current_go_index >= len(session.go_list):
                    session_complete = True
                else:
                    next_go_info = session.go_list[session.current_go_index]
                    logger.info(f"Advancing to GO {session.current_go_index + 1}/{len(session.go_list)}")
            
            return {
                'message': tutor_message,
                'graded': is_graded and not diagnostic,
                'diagnostic': diagnostic,
                'is_correct': is_correct,
                'evidence_weight': scaffolding_model.evidence_weight(evaluation_details.get('checkable'),
                                                                     evaluation_details.get('confidence')),
                'one_question_extracted': evaluation_details.get('one_question_extracted'),
                'one_question_about_objective': evaluation_details.get('one_question_about_objective'),
                'one_question_category': evaluation_details.get('one_question_category'),
                'recorded_question': evaluation_details.get('recorded_question'),
                'mastery_score': mastery_score,
                'has_achieved_mastery': has_achieved_mastery,
                'session_complete': session_complete,
                'scaffolding_level': session.scaffolding_intensity,  # For backwards compatibility
                'scaffolding_strategy': session.scaffolding_strategy,  # NEW
                'scaffolding_intensity': session.scaffolding_intensity,  # NEW
                'current_go': go_id,
                'next_go': next_go_info,
                'requires_review': session.requires_review,
                'orchestrator_applied': orchestrator_context is not None,
                'youtube_shown': youtube_content is not None,
                'youtube_source': session.last_help_source if youtube_content is not None else None,
                'progress': {
                    'current': min(session.current_go_index + 1, len(session.go_list)),
                    'total': len(session.go_list),
                    'percentage': min(session.current_go_index + 1, len(session.go_list)) / len(session.go_list) * 100
                }
            }
            
        except Exception as e:
            logger.error(f"Error processing student response: {e}", exc_info=True)
            return self._get_error_response(session)

    def _apply_scaffolding_decision(self, session: TutorSession, scaffolding_strategy: Dict[str, Any]):
        """Apply scaffolding decision from orchestrator/engine"""
        
        # Handle both ScaffoldingDecision objects and dict responses
        if hasattr(scaffolding_strategy, 'strategy_type'):
            # ScaffoldingDecision object
            session.scaffolding_strategy = scaffolding_strategy.strategy_type
            session.scaffolding_intensity = scaffolding_strategy.intensity_level
            session.scaffolding_level = scaffolding_strategy.intensity_level  # Backwards compatibility
            
        elif isinstance(scaffolding_strategy, dict):
            # Dictionary response
            session.scaffolding_strategy = scaffolding_strategy.get('strategy_type', 'procedural')
            session.scaffolding_intensity = scaffolding_strategy.get('intensity_level', 'medium')
            session.scaffolding_level = scaffolding_strategy.get('intensity_level', 'medium')
            
            # Also check for alternative key names
            if 'intervention_type' in scaffolding_strategy and 'strategy_type' not in scaffolding_strategy:
                # Map intervention types to strategies
                intervention_map = {
                    'concept_review': 'conceptual',
                    'maintain_flow': 'procedural',
                    'increase_support': 'procedural',
                    'reduce_support': 'strategic',
                    'metacognitive_prompt': 'metacognitive'
                }
                intervention = scaffolding_strategy.get('intervention_type', 'maintain_flow')
                session.scaffolding_strategy = intervention_map.get(intervention, 'procedural')
        
        logger.debug(f"Applied scaffolding: {session.scaffolding_strategy} at {session.scaffolding_intensity}")

    def _generate_adaptive_response(
        self,
        session: TutorSession,
        student_input: str,
        is_correct: bool,
        mastery_score: float,
        evaluation_details: Dict,
        rag_content: Optional[str] = None,
        orchestrator_context: Optional[Dict] = None,
        youtube_content: Optional[str] = None,
        on_token=None,
    ) -> str:
        """Generate adaptive tutor response using strategy-specific scaffolding"""
        
        current_go = session.go_list[session.current_go_index]
        skill_name = current_go.get('skill_name', 'this concept')
        description = current_go.get('description', '')
        
        # Get strategy-specific templates
        strategy_template = self.scaffolding_templates.get(
            session.scaffolding_strategy, 
            self.scaffolding_templates['procedural']
        )
        
        # Get intensity modifier
        intensity_modifier = self.intensity_modifiers.get(
            session.scaffolding_intensity,
            self.intensity_modifiers['medium']
        )
        
        # Build context-aware prompt
        one_question_rules = ""
        if scaffolding_model.tutor_records_one_question():
            one_question_rules = (
                f"6. End your message with exactly one clear question about {skill_name} that has a right "
                "or wrong answer you could check against the course material. Ask it last, as its own "
                "short sentence.\n"
                "7. You may ask one additional exploratory or connecting question earlier in your message, "
                "but if you do, label it clearly as optional, e.g. \"(just something to think about, not "
                "required)\". Never end on that question -- always end on the one required, checkable one.\n"
                "8. State only facts that are supported by the course content given to you below -- never add "
                "a date, name, number or other specific detail that isn't in it.\n"
                "9. Keep your whole reply to about 200 words or less."
            )
        system_prompt = f"""You are LEA, a supportive AI tutor helping a student learn {skill_name}.

SCAFFOLDING STRATEGY: {session.scaffolding_strategy.upper()}
Focus: {strategy_template['focus']}
Feedback Style: {strategy_template['feedback_style']}
Guidance: {strategy_template['prompt_guidance']}

INTENSITY LEVEL: {session.scaffolding_intensity.upper()}
{intensity_modifier}

CRITICAL RULES:
1. Apply the {session.scaffolding_strategy} scaffolding strategy consistently
2. Match the {session.scaffolding_intensity} intensity level
3. NEVER use false praise for incorrect answers
4. Be direct, clear, and educational without being harsh
5. For incorrect answers: acknowledge difficulty, provide correct information, explain clearly
{one_question_rules}

Current Status:
- Concept: {skill_name}
- Description: {description}
- Student answered: {"correctly ✓" if is_correct else "incorrectly ✗"} 
- Mastery level: {mastery_score:.1%}
- Consecutive incorrect: {session.consecutive_incorrect}
- Interaction count: {session.interaction_count}

{f"Course content available: {rag_content[:500]}" if rag_content else ""}
"""
        if session.quiz_review:
            system_prompt += f"""
QUIZ REVIEW: The student opened this session to review a quiz they just took. Their results:
{session.quiz_review}
When the current concept relates to a quiz question they missed, address that specific mistake
and check they now understand it. Don't re-mark the quiz or change its score.
"""
        
        # Generate strategy-specific user prompt
        if is_correct:
            user_prompt = self._get_correct_response_prompt_with_strategy(
                student_input, mastery_score, skill_name, session, strategy_template
            )
        else:
            user_prompt = self._get_incorrect_response_prompt_with_strategy(
                student_input, skill_name, evaluation_details, session, strategy_template
            )
        
        # Add YouTube content if available
        if youtube_content:
            user_prompt += f"\n\nINCLUDE these helpful video resources:\n{youtube_content}"
        
        try:
            tutor_message = complete(
                self.openai_client, on_token=on_token,
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=scaffolding_model.tutor_temperature(),
                max_tokens=500,
            )

            # Ensure YouTube videos are included if available
            if youtube_content and "Video Resources" not in tutor_message:
                tutor_message += youtube_content
                if on_token:
                    on_token(youtube_content)
            
            logger.debug(f"Generated {session.scaffolding_strategy} response at {session.scaffolding_intensity} intensity")
            return tutor_message
            
        except Exception as e:
            logger.error(f"Error generating tutor response: {e}")
            return self._get_fallback_response(is_correct, skill_name, youtube_content)
    
    def _get_incorrect_response_prompt_with_strategy(
        self, 
        student_input: str, 
        skill_name: str, 
        evaluation_details: Dict,
        session: TutorSession,
        strategy_template: Dict
    ) -> str:
        """Generate strategy-specific prompt for incorrect responses"""
        
        # Check for "I don't know" type responses
        unknown_responses = ["i don't know", "idk", "no idea", "not sure", "don't know", "unsure"]
        is_unknown = any(resp in student_input.lower() for resp in unknown_responses)
        
        base_prompt = f"""The student said: "{student_input}"
Strategy to apply: {session.scaffolding_strategy}
Intensity: {session.scaffolding_intensity}"""
        
        if session.scaffolding_strategy == "conceptual":
            if is_unknown:
                return base_prompt + f"""
They don't know. Build conceptual understanding:
1. Start with: "{strategy_template['intro']}"
2. Explain the core concept using an analogy
3. Show how concepts relate to each other
4. Use: "{strategy_template['example']}" to provide a conceptual model
5. End with: "{strategy_template['check']}" """
            else:
                return base_prompt + f"""
Incorrect answer. Focus on conceptual understanding:
1. Identify the conceptual misunderstanding
2. Use: "{strategy_template['hint']}" to guide toward the principle
3. Explain WHY this concept works this way
4. Connect to related concepts they might know
5. Check understanding of relationships"""
                
        elif session.scaffolding_strategy == "procedural":
            if is_unknown:
                return base_prompt + f"""
They don't know. Provide step-by-step guidance:
1. Start with: "{strategy_template['intro']}"
2. Break down into clear sequential steps
3. Use: "{strategy_template['example']}" to show a worked example
4. Walk through each step explicitly
5. Ask them to try the first step"""
            else:
                return base_prompt + f"""
Incorrect answer. Provide procedural support:
1. Identify which step went wrong
2. Use: "{strategy_template['hint']}" for the next step
3. Show the correct procedure step-by-step
4. Provide a similar worked example
5. Guide them through trying again"""
                
        elif session.scaffolding_strategy == "strategic":
            return base_prompt + f"""
Focus on problem-solving strategies:
1. Start with: "{strategy_template['intro']}"
2. Present 2-3 different approaches to this problem
3. Use: "{strategy_template['hint']}" to suggest a strategy
4. Compare pros/cons of each approach
5. Ask: "{strategy_template['check']}" """
            
        else:  # metacognitive
            return base_prompt + f"""
Focus on learning reflection:
1. Start with: "{strategy_template['intro']}"
2. Ask them to reflect on their thinking process
3. Use: "{strategy_template['hint']}" about their approach
4. Help them identify where confusion arose
5. Ask: "{strategy_template['check']}" about confidence"""
    
    def _get_correct_response_prompt_with_strategy(
        self, 
        student_input: str, 
        mastery_score: float, 
        skill_name: str,
        session: TutorSession,
        strategy_template: Dict
    ) -> str:
        """Generate strategy-specific prompt for correct responses"""
        
        base_prompt = f"""The student correctly answered: "{student_input}"
Strategy to apply: {session.scaffolding_strategy}
Intensity: {session.scaffolding_intensity}"""
        
        if session.scaffolding_strategy == "conceptual":
            return base_prompt + f"""
Correct! Deepen conceptual understanding:
1. Praise their conceptual grasp
2. Connect this concept to broader principles
3. Ask how this relates to other concepts
4. Extend to more complex relationships"""
            
        elif session.scaffolding_strategy == "procedural":
            return base_prompt + f"""
Correct! Reinforce procedural mastery:
1. Confirm the correct procedure
2. Highlight which steps were done well
3. Suggest a slightly harder variation
4. Ask them to explain the process"""
            
        elif session.scaffolding_strategy == "strategic":
            return base_prompt + f"""
Correct! Explore strategic thinking:
1. Praise their problem-solving approach
2. Ask why they chose this strategy
3. Discuss alternative approaches
4. Challenge with a variant requiring strategy selection"""
            
        else:  # metacognitive
            return base_prompt + f"""
Correct! Promote metacognitive awareness:
1. Ask them to reflect on how they knew
2. Explore their confidence level
3. Discuss what made this click
4. Connect to their learning journey"""

    # Keep all other methods unchanged
    def _get_youtube_help(self, session: TutorSession) -> Optional[str]:
        """Get YouTube video help via MCP client (Streamlit-compatible)"""
        try:
            current_go = session.go_list[session.current_go_index]
            curated = self._curated_help(session, current_go)
            if curated:
                session.last_help_source = "curated"
                return curated
            if not self.mcp_client:
                logger.debug("No MCP client available for YouTube")
                return None

            skill_name = current_go.get('skill_name', '')
            keywords = current_go.get('content_keywords', [])
            
            # Build search query
            search_terms = [skill_name] + keywords[:2] if keywords else [skill_name]
            search_query = f"{' '.join(search_terms)} tutorial for beginners"
            logger.info(f"🎥 Requesting YouTube videos for: {search_query}")
            
            request = {
                "tool": "youtube_worked_examples",
                "parameters": {"topic": search_query, "subject_area": session.course, "max_results": 3},
            }
            result = self.mcp_client.mcp_server.handle_tool_request(request)

            # Process results
            if result and result.get('success') and result.get('videos'):
                videos = result['videos']
                
                # Format video recommendations
                video_text = "\n\n📹 **Video Resources to Help You:**\n"
                for i, video in enumerate(videos[:3], 1):
                    video_text += f"{i}. [{video['title']}]({video['url']})\n"
                    if video.get('duration'):
                        video_text += f"   Duration: {video['duration']}\n"
                
                logger.info(f"✅ Retrieved {len(videos)} YouTube videos")
                session.last_help_source = f"search:{result.get('source', 'api')}"
                return video_text
            else:
                logger.warning(f"YouTube search returned no videos: {result}")

                # Fallback: Return hardcoded educational videos for the topic
                fallback_text = self._get_fallback_youtube_links(skill_name)
                if fallback_text:
                    logger.info("Using fallback YouTube links")
                    session.last_help_source = "fallback"
                    return fallback_text
                
                return None
                
        except Exception as e:
            logger.error(f"YouTube help retrieval failed: {e}", exc_info=True)

            # Last resort: Return generic help message
            try:
                topic = session.go_list[session.current_go_index].get('skill_name', 'AI concepts')
            except Exception:
                topic = 'AI concepts'
            session.last_help_source = "fallback"
            return self._get_fallback_youtube_links(topic)

    def _curated_help(self, session: TutorSession, current_go: Dict[str, Any]) -> Optional[str]:
        """The instructor's videos for this objective as a video block (None if there are none).
        Their order and notes are kept; up to three are shown."""
        if not self.curated_videos:
            return None
        try:
            videos = list(self.curated_videos(session.course, current_go.get('go_id')) or [])[:3]
        except Exception as e:
            logger.warning(f"Curated videos couldn't be read: {e}")
            return None
        if not videos:
            return None
        text = "\n\n📹 **Video Resources to Help You:**\n"
        for i, video in enumerate(videos, 1):
            text += f"{i}. [{video['title']}]({video['url']})\n"
            if video.get('note'):
                text += f"   {video['note']}\n"
        return text

    def _get_fallback_youtube_links(self, topic: str) -> str:
        """Provide fallback YouTube links when API fails"""
        # [Keep existing implementation]
        fallback_links = {
            "AI": [
                ("IBM Technology - What is AI?", "https://www.youtube.com/results?search_query=IBM+Technology+What+is+AI"),
                ("MIT OpenCourseWare - AI Basics", "https://www.youtube.com/results?search_query=MIT+OpenCourseWare+artificial+intelligence+basics"),
                ("CrashCourse - AI Explained", "https://www.youtube.com/results?search_query=CrashCourse+Computer+Science+AI")
            ],
            "default": [
                (f"Search: {topic} tutorial", f"https://www.youtube.com/results?search_query={topic.replace(' ', '+')}+tutorial+for+beginners"),
                (f"Search: {topic} explained", f"https://www.youtube.com/results?search_query={topic.replace(' ', '+')}+explained+simply"),
                (f"Search: Learn {topic}", f"https://www.youtube.com/results?search_query=learn+{topic.replace(' ', '+')}+basics")
            ]
        }
        
        # Determine which links to use
        if "AI" in topic or "artificial" in topic.lower() or "intelligence" in topic.lower():
            links = fallback_links["AI"]
        else:
            links = fallback_links["default"]
        
        # Format as video links
        video_text = "\n\n📹 **Video Resources to Help You:**\n"
        for i, (title, url) in enumerate(links, 1):
            video_text += f"{i}. [{title}]({url})\n"
        
        return video_text
    
    _UNKNOWN = re.compile(r"\b(i\s*don'?t\s*know|idk|no idea|not sure|unsure|dunno)\b", re.IGNORECASE)
    _STOPWORDS = {"the", "and", "of", "to", "in", "a", "an", "for", "on", "with", "its", "is", "are", "how", "what"}

    @classmethod
    def _concept_terms(cls, current_go: Dict) -> List[str]:
        """Human-readable concept terms for a GO: its tags and skill name, split into words."""
        raw = list(current_go.get('content_keywords', [])) + [current_go.get('skill_name', '')]
        terms = set()
        for item in raw:
            for word in re.split(r"[\s_\-/]+", str(item).lower()):
                if len(word) > 1 and word not in cls._STOPWORDS:
                    terms.add(word)
        return sorted(terms)

    def _extract_recorded_question(self, tutor_message: str, go_id: str, skill_name: str,
                                   other_objectives: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        """The one required, checkable question ``tutor_message`` ends on, and whether it counts as being
        about ``skill_name``. Extraction only -- a separate, non-streamed call; never rewrites or shows
        anything to the student. None on any failure (network, bad JSON, missing fields).

        ``other_objectives`` (the rest of the week's GO list, passed only when
        ``LEA_TUTOR_QUESTION_SCOPE=broad``): asks for a four-way category instead of a plain yes/no, and
        counts both "current" and "related_comparison" as about this objective -- a question that connects
        or compares the current objective with another still counts, so long as answering it would mainly
        show understanding of the current one. A question clearly about a different same-week objective, or
        about something outside the week, still does not count (``credit_other_go``, crediting such a
        question to that other objective instead, is a separate, not-yet-built idea)."""
        if other_objectives:
            system = ("From the tutor message below, find the ONE required checkable question it ends on "
                     "(ignore any question explicitly labelled optional). The tutor is meant to be teaching "
                     f'this objective right now: "{skill_name}". This week also covers these other '
                     f"objectives: {'; '.join(other_objectives)}. Reply with a single JSON object and "
                     'nothing else: {"question": "the question, or empty string if there is none", '
                     '"category": one of "current" (the question is about "' + skill_name + '"), '
                     '"related_comparison" (it connects or compares "' + skill_name + '" with another '
                     "concept, but a good answer would still mainly need to show understanding of \"" +
                     skill_name + "\"), \"same_week_other_go\" (it is clearly about one of the other "
                     'objectives listed instead), or "outside_week" (about something not in this week\'s '
                     'objectives at all, or there is no real question)}.')
        else:
            system = ("From the tutor message below, find the ONE required checkable question it ends on "
                     "(ignore any question explicitly labelled optional, e.g. \"just something to think "
                     "about\"). Reply with a single JSON object and nothing else: "
                     '{"question": "the question, or empty string if there is none", '
                     '"about_this_objective": true or false}. "about_this_objective" is true only if that '
                     f'question is genuinely about "{skill_name}", not a different topic.')
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "system", "content": system},
                         {"role": "user", "content": f"Tutor message:\n{tutor_message[-2000:]}"}],
                temperature=0.0, max_tokens=150, response_format={"type": "json_object"},
            )
            data = json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.debug(f"Recorded-question extraction failed: {e}")
            return None
        question = data.get("question")
        if not isinstance(question, str) or not question.strip():
            return None
        if other_objectives:
            category = data.get("category")
            if category not in ("current", "related_comparison", "same_week_other_go", "outside_week"):
                return None
            about = category in ("current", "related_comparison")
            return {"question": question.strip(), "about_this_objective": about, "go_id": go_id, "category": category}
        about = data.get("about_this_objective")
        if not isinstance(about, bool):
            return None
        return {"question": question.strip(), "about_this_objective": about, "go_id": go_id}

    def _evaluate_response_enhanced(
        self,
        student_input: str,
        current_go: Dict,
        session: TutorSession
    ) -> Tuple[bool, float, Dict]:
        """Grade a tutor response against the current GO.

        Returns (is_correct, score, details). ``details['graded']`` is False when the LLM
        grader could not produce a valid verdict; the heuristic verdict is then used only
        to keep the conversation going and never counts towards mastery or advancement.
        """
        # Only a bare "I don't know" skips the grader; "not sure, but I think..." is graded.
        text = (student_input or "").strip()
        if self._UNKNOWN.search(text) and len(re.findall(r"\w+", text)) <= 6:
            return False, 0.4, {'graded': True, 'understanding_level': 'none',
                                'matched_keywords': [], 'missing_concepts': []}

        last_question = next(
            (m['content'] for m in reversed(session.conversation_history[:-1]) if m.get('role') == 'tutor'), ""
        )
        one_question_telemetry: Dict[str, Any] = {}
        if scaffolding_model.tutor_records_one_question():
            # Extracted now, at grading time (not when the tutor's message was generated): no extra
            # latency on the tutor's turn, and no call at all if the student never replies.
            others = None
            if scaffolding_model.tutor_question_scope() == "broad":
                others = [g.get('skill_name', g.get('go_id', '')) for g in session.go_list
                         if g.get('go_id') != current_go.get('go_id')]
            extracted = self._extract_recorded_question(last_question, current_go.get('go_id'),
                                                        current_go.get('skill_name', ''), others)
            one_question_telemetry = {
                'one_question_extracted': bool(extracted),
                'one_question_about_objective': bool(extracted and extracted["about_this_objective"]),
                'one_question_category': extracted.get("category") if extracted else None,
            }
            if extracted and extracted["about_this_objective"]:
                one_question_telemetry['recorded_question'] = extracted["question"]
                last_question = extracted["question"]
            else:
                # No valid recorded question for this GO (extraction failed, or the tutor's message wasn't
                # about it): nothing legitimate to grade against, so this turn is ungraded, not guessed at.
                result = grading.ungraded("no recorded checkable question for the current GO")
                is_correct, score, details = self._heuristic_fallback(result, student_input, current_go)
                return is_correct, score, {**details, **one_question_telemetry}
        result = grading.grade_with_llm(
            self.openai_client,
            kind="tutor",
            reference={
                "learning objective": current_go.get('skill_name', ''),
                "objective description": current_go.get('description', ''),
                "key concepts": ", ".join(self._concept_terms(current_go)),
            },
            student_answer=student_input,
            conversation=last_question[-800:],
        )
        if result["graded"]:
            score = result["score"]
            details = {
                'graded': True,
                'matched_keywords': result.get('matched_concepts', []),
                'missing_concepts': result.get('missing_concepts', [])[:3],
                'understanding_level': ('mastery' if score >= 0.8 else 'developing' if score >= 0.6
                                        else 'basic' if score >= 0.4 else 'minimal'),
                'grader_explanation': result.get('explanation', ''),
                **one_question_telemetry,
            }
            if 'checkable' in result:
                details['checkable'], details['confidence'] = result.get('checkable'), result.get('confidence')
            return result["correct"], score, details

        is_correct, score, details = self._heuristic_fallback(result, student_input, current_go)
        return is_correct, score, {**details, **one_question_telemetry}

    def _heuristic_fallback(self, result: Dict[str, Any], student_input: str, current_go: Dict) -> Tuple[bool, float, Dict]:
        """For the conversation only (grading failed, the grader found nothing checkable, or -- with
        LEA_TUTOR_RECORDED_QUESTION on -- there was no valid recorded question): needs at least one
        concept term. Never counts towards mastery (``graded`` stays False)."""
        text = (student_input or "").lower()
        terms = self._concept_terms(current_go)
        matched = [t for t in terms if re.search(rf"\b{re.escape(t)}\b", text)]
        ratio = len(matched) / len(terms) if terms else 0.0
        score = min(1.0, 0.3 + 0.5 * ratio + (0.1 if len(text.split()) > 10 else 0.0))
        details = {'graded': False, 'matched_keywords': matched,
                   'missing_concepts': [t for t in terms if t not in matched][:3],
                   'understanding_level': 'unknown'}
        if 'checkable' in result:
            details['checkable'], details['confidence'] = result.get('checkable'), result.get('confidence')
        return bool(matched) and score >= 0.6, score, details
    
    def _generate_initial_message(self, session: TutorSession, orchestrator_context: Optional[Dict] = None,
                                  review_intro: Optional[str] = None) -> str:
        """Generate initial tutoring message"""
        # [Keep existing implementation]
        if not session.go_list:
            return "Let's begin our tutoring session. What would you like to learn about?"
        
        first_go = session.go_list[session.current_go_index]
        skill_name = first_go.get('skill_name', 'our first concept')
        description = first_go.get('description', '')
        
        # Check for orchestrator context
        motivation_level = "standard"
        if orchestrator_context and 'motivation_state' in orchestrator_context:
            motivation_level = orchestrator_context.get('motivation_state', 'standard')
        
        # Adaptive greeting based on context
        if motivation_level == 'cold_start':
            greeting = "Welcome! I'm LEA, and I'm here to help you learn at your own pace."
        elif motivation_level == 'maintained_high':
            greeting = "Great to see you! You've been doing excellent work."
        else:
            greeting = "Hi! I'm LEA, your AI tutor."
        if review_intro:
            greeting = review_intro
        
        return f"""{greeting} Today we'll work through {len(session.go_list)} concepts in {session.course}, Week {session.week}.

Let's start with: **{skill_name}**

{description}

Can you tell me what you already know about {skill_name}? Even if you're not sure, any thoughts you have will help me understand where to begin."""
    
    def _check_prior_mastery(self, session: TutorSession) -> TutorSession:
        """Start at the first GO the learner has not yet mastered (review from the start if all are)."""
        try:
            conn = self.redis_client.get_redis() if hasattr(self.redis_client, 'get_redis') else self.redis_client
            raw = conn.get(f"mastery:{session.username}:{session.course}")
            if not raw:
                return session
            stored = json.loads(raw).get('go_masteries', {})

            def level(value):
                return value.get('level', 0.0) if isinstance(value, dict) else float(value)

            first_unmastered = None
            for i, go in enumerate(session.go_list):
                go_id = go.get('go_id')
                if go_id in stored:
                    session.mastery_scores[go_id] = level(stored[go_id])
                if first_unmastered is None and session.mastery_scores.get(go_id, 0.0) < go.get('mastery_threshold', 0.8):
                    first_unmastered = i
            session.current_go_index = first_unmastered if first_unmastered is not None else 0
            if session.current_go_index:
                logger.info(f"Starting at GO {session.current_go_index + 1}/{len(session.go_list)}: earlier GOs already mastered")
        except Exception as e:
            logger.error(f"Error checking prior mastery: {e}")
        return session

    def _get_completed_response(self, session: TutorSession) -> Dict[str, Any]:
        return {
            'message': "You've worked through every objective in this session. Start a new session to review, or try a quiz.",
            'graded': False,
            'is_correct': False,
            'mastery_score': session.current_mastery,
            'has_achieved_mastery': False,
            'session_complete': True,
            'scaffolding_level': session.scaffolding_intensity,
            'scaffolding_strategy': session.scaffolding_strategy,
            'scaffolding_intensity': session.scaffolding_intensity,
            'current_go': None,
            'orchestrator_applied': False,
        }

    def _get_fallback_response(self, is_correct: bool, skill_name: str, youtube_content: Optional[str] = None) -> str:
        """Generate fallback response when API fails"""
        # [Keep existing implementation]
        if is_correct:
            response = f"That's correct! You understand {skill_name}. Let's continue building on this knowledge."
        else:
            response = f"Let me help clarify {skill_name}. This concept involves understanding the key principles and how to apply them."
        
        if youtube_content:
            response += youtube_content
        
        return response
    
    def _get_error_response(self, session: TutorSession) -> Dict[str, Any]:
        """Generate error response"""
        # [Keep existing implementation]
        return {
            'message': "I encountered an error processing your response. Let's continue with the current concept.",
            'graded': False,
            'is_correct': False,
            'mastery_score': 0.0,
            'has_achieved_mastery': False,
            'session_complete': False,
            'scaffolding_level': session.scaffolding_intensity,
            'scaffolding_strategy': session.scaffolding_strategy,
            'scaffolding_intensity': session.scaffolding_intensity,
            'orchestrator_applied': False
        }
    
    def get_session_summary(self, session: TutorSession) -> Dict[str, Any]:
        """Get comprehensive session summary"""
        # [Keep existing implementation with strategy info]
        total_gos = len(session.go_list)
        completed_gos = session.current_go_index
        mastered_gos = sum(1 for score in session.mastery_scores.values() if score >= 0.8)
        
        accuracy = session.correct_count / max(session.interaction_count, 1)
        average_mastery = sum(session.mastery_scores.values()) / len(session.mastery_scores) if session.mastery_scores else 0
        
        return {
            'session_id': session.session_id,
            'username': session.username,
            'course': session.course,
            'week': session.week,
            'total_gos': total_gos,
            'gos_completed': completed_gos,
            'gos_mastered': mastered_gos,
            'accuracy': accuracy,
            'average_mastery': average_mastery,
            'correct_count': session.correct_count,
            'incorrect_count': session.incorrect_count,
            'interaction_count': session.interaction_count,
            'scaffolding_strategy': session.scaffolding_strategy,
            'scaffolding_intensity': session.scaffolding_intensity,
            'requires_review': session.requires_review,
            'review_concepts': session.review_concepts,
            'duration': (datetime.now() - session.start_time).total_seconds()
        }
