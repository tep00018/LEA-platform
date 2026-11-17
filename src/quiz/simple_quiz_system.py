# File: src/quiz/simple_quiz_system.py
"""
Simple Quiz System with MCP RAG Integration
Enhanced educational quiz generation system using centralized content retrieval
and adaptive question generation based on learner motivation states.

This module provides a comprehensive quiz system that integrates with the 
LEA (Learning Enhancement Application) architecture, utilizing MCP-based
RAG retrieval for consistent content access across all learning modalities.
"""

import os
import random
from openai import OpenAI
from typing import Dict, List, Optional, Any
import time
from datetime import datetime
import uuid
import logging

from src.core import grading
from src.core.course_registry import default_registry
from src.onboarding.audit_checks import load_bank

logger = logging.getLogger(__name__)



def store_quiz_memory(
    redis_client, 
    username: str, 
    question: Dict, 
    user_answer: str, 
    is_correct: bool, 
    score: float
) -> None:
    """
    Store quiz interaction in the memory system for long-term tracking.
    
    This function persists quiz interactions to Redis for analytics and
    adaptive learning purposes. The stored data enables tracking of learner
    progress and performance patterns over time.
    
    Args:
        redis_client: Redis client instance for data persistence
        username: Unique identifier for the learner
        question: Dictionary containing question details
        user_answer: The learner's response to the question
        is_correct: Boolean indicating answer correctness
        score: Numerical score (0.0 to 1.0) for the response
    """
    try:
        if redis_client and hasattr(redis_client, 'store_short_term_memory'):
            redis_client.store_short_term_memory(
                username=username,
                interaction_type="quiz",
                content={
                    "question": question.get("text", ""),
                    "question_type": question.get("type", "multiple_choice"),
                    "user_answer": user_answer,
                    "correct": is_correct,
                    "score": score,
                    "go_id": question.get("go_id", ""),
                    "course": question.get("course", "unknown"),
                    "week": question.get("week", 1),
                    "timestamp": time.time()
                }
            )
            logger.debug(f"Stored quiz memory for {username}")
    except Exception as e:
        logger.debug(f"Failed to store quiz memory: {e}")


class SimpleQuizSystem:
    """
    Enhanced quiz system utilizing MCP RAG integration for content retrieval.
    
    This system generates adaptive quiz questions based on learning objectives,
    learner motivation states, and course content. It maintains consistency
    with Chat and Tutor modes by using centralized RAG retrieval through MCP.
    
    Key Features:
        - Adaptive question generation based on cognitive load and motivation
        - Question type variety enforcement for comprehensive assessment
        - Conversational feedback using personalized language
        - Integration with centralized RAG content retrieval
        - Support for multiple question formats (MC, T/F, FIB, OE)
    """
    
    def __init__(self, openai_api_key: Optional[str] = None, rag_tool=None, *,
                 openai_client=None, redis_client=None, kc_loader_factory=None):
        """
        Args:
            openai_api_key: API key, used when no ``openai_client`` is given
            rag_tool: RAGRetrievalTool instance for content retrieval
            openai_client: shared OpenAI client
            redis_client: LEARedisClient for short-term memory (optional)
            kc_loader_factory: ``course -> KCModelLoader``; defaults to a loader on ``REDIS_URL``

        The quiz system holds no per-quiz state: everything about a quiz, including the
        question-variety trackers, lives in the quiz dict that callers store and pass back.
        """
        self.openai_client = openai_client or OpenAI(api_key=openai_api_key)
        self.rag_tool = rag_tool
        self.redis_client = redis_client
        self._kc_loader_factory = kc_loader_factory

        # Question type configuration
        self.question_types = ["multiple_choice", "true_false", "fill_in_blank", "open_ended"]
        self.type_weights = [0.4, 0.3, 0.2, 0.1]

    @staticmethod
    def _new_trackers() -> Dict[str, Any]:
        return {
            "type_counts": {"multiple_choice": 0, "true_false": 0, "fill_in_blank": 0, "open_ended": 0},
            "question_history": [],
            "coding": {"count": 0, "questions": []},
        }

    def _bank_question(self, course: str, question_plan: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """A reviewed reference-question-bank entry for this GO and question type, converted
        to the same shape an LLM-generated question would have -- or None (fall back to
        generation) when the type isn't multiple_choice/true_false, no bank file exists for
        the course, or nothing reviewed matches this GO. Never calls a model."""
        if question_plan.get("type") not in ("multiple_choice", "true_false"):
            return None
        try:
            data_dir = default_registry().data_dir
        except AttributeError:
            return None  # a registry stub without data_dir (some tests): no bank available
        bank = load_bank(data_dir / "course_sources" / course / "question_bank.json")
        if not bank:
            return None
        candidates = [
            q for q in bank.get("questions", [])
            if q.get("go_id") == question_plan["go_id"] and q.get("type") == question_plan["type"]
            and q.get("tagging", {}).get("reviewed") is True
        ]
        if not candidates:
            return None
        return self._bank_question_to_data(random.choice(candidates))

    @staticmethod
    def _bank_question_to_data(q: Dict[str, Any]) -> Dict[str, Any]:
        options = q.get("options") or []
        correct_index = q.get("correct_index")
        if q["type"] == "multiple_choice":
            letters = [chr(ord("A") + i) for i in range(len(options))]
            data = {
                "options": [f"{letter}) {text}" for letter, text in zip(letters, options)],
                "correct_answer": letters[correct_index],
            }
        else:  # true_false
            data = {"correct_answer": str(options[correct_index]) if options else "True"}
        data.update({
            "type": q["type"],
            "text": q["text"],
            "explanation": f"From the course's reference question bank ({q.get('source', {}).get('curriculum', 'reviewed by the instructor')}).",
            "generated_at": datetime.now().isoformat(),
            "content_hash": hash(q["text"]) % 10000,
            "bank_question_id": q.get("id"),
        })
        return data

    def _kc_loader(self, course: str):
        if self._kc_loader_factory:
            return self._kc_loader_factory(course)
        from src.core.kc_model_loader import KCModelLoader
        import redis
        client = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"), decode_responses=True)
        return KCModelLoader(client, module=course)
    
    def set_rag_tool(self, rag_tool) -> None:
        """
        Set or update the RAG tool after initialization.
        
        This method allows for dynamic configuration of the RAG tool,
        enabling flexibility in system setup and testing scenarios.
        
        Args:
            rag_tool: RAGRetrievalTool instance for content retrieval
        """
        self.rag_tool = rag_tool
        logger.debug("RAG tool set for quiz system")
    
    def _get_relevant_content_via_rag(
        self, 
        keywords: List[str], 
        go_data: Dict[str, Any] = None,
        course: str = ""
    ) -> str:
        """
        Get GO-specific content using MCP RAG tool with correct extraction for your RAG structure
        """
        if not self.rag_tool:
            logger.warning("No RAG tool available, using fallback content")
            return self._get_fallback_content(go_data)
        
        try:
            skill_name = go_data.get("skill_name", "") if go_data else ""
            description = go_data.get("description", "") if go_data else ""
            
            # Construct targeted queries
            primary_query = f"{skill_name} {' '.join(keywords[:3])}" if keywords else skill_name
            
            query_variations = [
                primary_query,
                f"{skill_name} implementation" if skill_name else f"{primary_query} implementation",
                f"{skill_name} examples" if skill_name else f"{primary_query} examples"
            ]
            
            if description:
                desc_words = [word for word in description.lower().split() 
                            if len(word) > 4 and word not in ['machine', 'learning', 'using', 'with']]
                if desc_words:
                    query_variations.append(f"{desc_words[0]} {primary_query}")
            
            logger.debug(f"RAG search with GO-specific queries: {query_variations[:2]}")
            
            all_content_pieces = []
            
            # Execute RAG queries
            for i, query in enumerate(query_variations[:2]):
                try:
                    rag_result = self.rag_tool.execute({
                        "query": query,
                        "course": course,
                        "max_results": 3,
                        "use_reranking": True
                    })
                    
                    if rag_result.get("success") and rag_result.get("results"):
                        for j, result in enumerate(rag_result["results"]):
                            content = None
                            
                            # Your RAG system returns dicts with 'content' field
                            if isinstance(result, dict):
                                # Based on your debug output, the 'content' field exists
                                content = result.get("content")
                                
                                # Debug if content extraction fails
                                if not content:
                                    logger.debug(f"Result {j} has no 'content' field. Keys: {list(result.keys())}")
                                    # Try alternative field names just in case
                                    for field in ["text", "document", "page_content", "chunk_text"]:
                                        if field in result and result[field]:
                                            content = result[field]
                                            logger.debug(f"Found content in '{field}' field")
                                            break
                            elif isinstance(result, str):
                                # If result is directly a string, use it as content
                                content = result
                                logger.debug(f"Result {j} is a string, using directly")
                            
                            # Process valid content
                            if content:
                                # Check if content is actually meaningful (not just metadata)
                                content_str = str(content)
                                
                                # Skip if content is just "metadata..." or similar placeholder
                                if content_str.strip().startswith("metadata"):
                                    logger.debug(f"Skipping metadata placeholder content")
                                    continue
                                
                                # Use actual content if it's substantial
                                if len(content_str) > 50:
                                    content_piece = content_str[:800]
                                    
                                    # Avoid duplicates
                                    content_hash = hash(content_piece[:100])
                                    if not any(hash(existing['content'][:100]) == content_hash 
                                             for existing in all_content_pieces):
                                        all_content_pieces.append({
                                            'content': content_piece,
                                            'source': f'query_{i}_result_{j}',
                                            'has_code': self._has_code_content(content_piece),
                                            'query_used': query,
                                            'relevance_score': result.get("relevance", result.get("rerank_score", 0.5)) if isinstance(result, dict) else 0.5
                                        })
                                        
                                        if self._has_code_content(content_piece):
                                            logger.debug(f"⭐ Content piece from '{query}' contains code")
                                        
                                        # Show preview of actual content
                                        preview = content_piece[:100].replace('\n', ' ')
                                        logger.debug(f"Content preview: {preview}...")
                            else:
                                logger.debug(f"No content extracted from result {j}")
                    
                except Exception as rag_error:
                    logger.warning(f"RAG query failed for '{query}': {rag_error}")
            
            logger.debug(f"Retrieved {len(all_content_pieces)} diverse content pieces via RAG")
            
            # Balance content selection
            final_content_pieces = []
            code_pieces = [p for p in all_content_pieces if p['has_code']]
            non_code_pieces = [p for p in all_content_pieces if not p['has_code']]
            
            if skill_name and any(term in skill_name.lower() for term in ['implement', 'algorithm', 'code']):
                if code_pieces:
                    final_content_pieces.extend([p['content'] for p in code_pieces[:2]])
                if non_code_pieces and len(final_content_pieces) < 2:
                    final_content_pieces.append(non_code_pieces[0]['content'])
            else:
                if non_code_pieces:
                    final_content_pieces.append(non_code_pieces[0]['content'])
                if code_pieces and len(final_content_pieces) < 2:
                    final_content_pieces.append(code_pieces[0]['content'])
                if len(final_content_pieces) < 2 and len(non_code_pieces) > 1:
                    final_content_pieces.append(non_code_pieces[1]['content'])
            
            if not final_content_pieces and all_content_pieces:
                final_content_pieces = [all_content_pieces[0]['content']]
            
            if final_content_pieces:
                final_content = "\n\n---\n\n".join(final_content_pieces)
                logger.debug(f"Final content length: {len(final_content)} characters")
                logger.debug(f"Content includes code: {self._has_code_content(final_content)}")
                return final_content
            else:
                logger.debug(f"No content retrieved via RAG, using fallback")
                return self._get_fallback_content(go_data)
            
        except Exception as e:
            logger.exception(f"Failed to retrieve content via RAG: {e}")
            return self._get_fallback_content(go_data)


    def _get_fallback_content(self, go_data: Dict[str, Any] = None) -> str:
        """
        Provide fallback content when RAG retrieval is unavailable.
        
        This method ensures quiz generation can continue even when content
        retrieval fails, maintaining system resilience and user experience.
        
        Args:
            go_data: Granular objective data for context
            
        Returns:
            Generic content string related to the learning objective
        """
        if not go_data:
            return "No course content was retrieved for this question."

        skill_name = go_data.get("skill_name", "this concept")
        description = go_data.get("description", "")

        fallback_content = f"""
        Content about {skill_name}:

        {description if description else f"{skill_name} is a learning objective in this course."}
        """
        
        logger.debug(f"Using fallback content for {skill_name}")
        return fallback_content

    def _generate_question(
        self, 
        course: str, 
        question_plan: Dict[str, Any],
        orchestrator_context: Optional[Dict[str, Any]] = None,
        trackers: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate an adaptive question using RAG content and orchestrator guidance.
        ENHANCED: Uses question_plan metadata directly for coding decisions.
        """
        try:
            trackers = trackers if trackers is not None else self._new_trackers()
            # Determine if this should include code based on the metadata in question_plan
            # The question_plan already has all the fields we need!
            # Code questions only for courses whose profile allows them (papers, Section 5.4).
            profile = default_registry().profile(course)
            question_plan['course_name'] = profile.display_name
            question_plan['allows_code'] = profile.allows_code
            question_plan['code_language'] = profile.code_language or "python"
            question_plan['include_code'] = profile.allows_code and self._should_include_coding_question_from_plan(
                question_plan, trackers["coding"]
            )

            # Apply orchestrator recommendations if available
            if orchestrator_context:
                question_plan = self._apply_orchestrator_recommendations_fixed(
                    question_plan, orchestrator_context, trackers["type_counts"])
                logger.debug(f"🎯 Applied orchestrator recommendations - Type: {question_plan['type']}, Difficulty: {question_plan.get('adjusted_difficulty', 'medium')}")
            if not profile.allows_code:
                question_plan['include_code'] = False
            
            # A reviewed reference-question-bank entry for this exact GO and type is used
            # in place of an LLM-generated question when one exists (research, 2026-09-28):
            # see docs/API.md's "Reference question banks in Quiz mode".
            question_data = self._bank_question(course, question_plan)
            if question_data:
                question_data["go_id"] = question_plan["go_id"]
                question_data["lo_id"] = question_plan["lo_id"]
                question_data["skill_name"] = question_plan["skill_name"]
                question_data["skill_category"] = question_plan.get("skill_category", "")
                question_data["cognitive_level"] = question_plan.get("cognitive_level", "")
                question_data["course"] = course
                question_data["has_code"] = False
                question_data["orchestrator_applied"] = False
                self._track_question_for_variety(question_data, question_plan, trackers["question_history"])
                return question_data

            # Retrieve content via centralized RAG tool
            content = self._get_relevant_content_via_rag(
                question_plan["keywords"],
                question_plan,
                course
            )

            # FALLBACK: If we need code but RAG didn't provide any, add example code
            if question_plan.get('include_code') and not self._has_code_content(content):
                skill_name = question_plan.get('skill_name', '').lower()
                
                # Generate appropriate code example based on skill
                if 'reinforcement' in skill_name or 'q-learning' in skill_name:
                    code_example = """
    Example code for Q-learning:
    ```python
    # Simple Q-learning example
    Q = [[0, 0], [0, 0]]  # Q-table: 2 states, 2 actions
    state = 0
    action = 1
    reward = 1
    Q[state][action] = reward  # Update Q-value
    print(Q)
    ```"""
                elif 'classification' in skill_name:
                    code_example = """
    Example classification code:
    ```python
    from sklearn.tree import DecisionTreeClassifier
    X = [[0, 0], [1, 1]]
    y = [0, 1]
    clf = DecisionTreeClassifier()
    clf.fit(X, y)
    ```"""
                elif 'regression' in skill_name:
                    code_example = """
    Example regression code:
    ```python
    from sklearn.linear_model import LinearRegression
    X = [[1], [2], [3]]
    y = [2, 4, 6]
    model = LinearRegression()
    model.fit(X, y)
    ```"""
                else:
                    # Generic ML code
                    code_example = """
    Example ML code:
    ```python
    import numpy as np
    data = np.array([1, 2, 3, 4, 5])
    mean = np.mean(data)
    print(f"Mean: {mean}")
    ```"""
                
                content = f"{content}\n\n{code_example}"
                logger.debug(f"Added fallback code example for {skill_name}")
            
            # Create comprehensive generation prompt
            history = trackers["question_history"]
            prompt = self._create_enhanced_generation_prompt(question_plan, content, history)

            # If orchestrator context exists, merge it with the prompt
            if orchestrator_context:
                prompt = self._create_orchestrator_guided_prompt(question_plan, content, orchestrator_context, history)
            
            # Generate the question; retry once if the model's JSON fails validation
            question_data = None
            for attempt in range(2):
                response = self.openai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": "You are an expert educational content creator. Generate quiz questions that adapt to the student's cognitive state and learning needs. Reply with one JSON object."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.8,
                    max_tokens=1000,
                    response_format={"type": "json_object"},
                )
                question_text = response.choices[0].message.content.strip()
                question_data = self._parse_generated_question(question_text, question_plan["type"])
                if question_data:
                    break
                logger.warning(f"Generated question failed validation (attempt {attempt + 1}); retrying")
            
            if question_data:
                # Add metadata for tracking and analysis
                question_data["go_id"] = question_plan["go_id"]
                question_data["lo_id"] = question_plan["lo_id"]
                question_data["skill_name"] = question_plan["skill_name"]
                question_data["skill_category"] = question_plan.get("skill_category", "")
                question_data["cognitive_level"] = question_plan.get("cognitive_level", "")
                question_data["course"] = course
                question_data["has_code"] = question_plan.get('include_code', False)
                
                # Include orchestrator metadata if applicable
                if orchestrator_context:
                    question_data["orchestrator_applied"] = True
                    question_data["scaffolding_strategy"] = orchestrator_context.get("scaffolding_strategy", {}).get("strategy_type", "none")
                    question_data["difficulty_adjustment"] = orchestrator_context.get("scaffolding_strategy", {}).get("difficulty_adjustment", "maintain")
                    question_data["support_level"] = orchestrator_context.get("scaffolding_strategy", {}).get("support_level", "medium")
                else:
                    question_data["orchestrator_applied"] = False
                
                # Track for variety maintenance
                self._track_question_for_variety(question_data, question_plan, history)
            
            return question_data
            
        except Exception as e:
            logger.exception(f"Failed to generate question: {e}")
            return None
    
    def start_quiz(
        self, 
        course: str, 
        week: int, 
        username: str, 
        orchestrator_context: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        """
        Initialize a new quiz session with adaptive question generation.
        ENHANCED: Passes skill metadata for strategic coding questions.
        """
        try:
            # Verify RAG tool availability
            if not self.rag_tool:
                logger.error("No RAG tool available for quiz generation")
                return None
            
            # Load knowledge component model
            kc_loader = self._kc_loader(course)
            
            # Retrieve week content structure
            week_content = kc_loader.get_week_content(course, week)
            
            # Generate comprehensive question plan
            question_plan = []
            motivation_state = orchestrator_context.get('motivation_state') if orchestrator_context else None
            
            question_number = 1
            quiz_id = f"quiz_{username}_{course}_w{week}_{uuid.uuid4().hex[:8]}"
            
            # Question-variety trackers travel with the quiz
            trackers = self._new_trackers()
            
            # Build question plan for all granular objectives
            for lo in week_content.learning_objectives:
                lo_question_count = 0
                
                for go in lo.granular_objectives:
                    question_type = self._select_variety_enforced_question_type(
                        go, lo, question_number, lo_question_count, 
                        motivation_state, trackers["type_counts"]
                    )
                    
                    question_plan.append({
                        "go_id": go.go_id,
                        "lo_id": lo.lo_id,
                        "skill_name": go.skill_name,
                        "description": go.description,
                        "keywords": go.content_keywords,
                        "type": question_type,
                        "question_number": question_number,
                        "lo_question_count": lo_question_count,
                        "motivation_state": motivation_state,
                        "quiz_id": quiz_id,
                        "base_difficulty": 0.5,
                        "skill_category": getattr(go, 'skill_category', 'conceptual'),  # Safe access with default
                        "cognitive_level": getattr(go, 'cognitive_level', 'Understand'),  # Safe access with default
                        "complexity": getattr(go, 'complexity', 'basic'),  # Safe access with default
                        "total_questions": len(week_content.learning_objectives) * len(lo.granular_objectives)  # Approximate total
                    })
                    
                    # FIXED: These lines must be indented to be inside the inner for loop
                    question_number += 1
                    lo_question_count += 1
            
            # Log question distribution
            type_distribution = {}
            for q in question_plan:
                qtype = q["type"]
                type_distribution[qtype] = type_distribution.get(qtype, 0) + 1
            
            logger.debug(f"Question type distribution: {type_distribution}")
            
            if not question_plan:
                logger.error(f"No granular objectives found for {course} week {week}")
                return None
            for q in question_plan:
                q["total_questions"] = len(question_plan)
            
            # Generate the first question, skipping any plan item that can't be generated
            first_question, first_index = None, 0
            for first_index, first_question_plan in enumerate(question_plan):
                first_question = self._generate_question(course, first_question_plan, orchestrator_context, trackers)
                if first_question:
                    break
                logger.error(f"Could not generate question {first_index + 1}; skipping it")

            if not first_question:
                logger.error("Failed to generate any question for this quiz")
                return None
            
            # Create quiz session
            quiz_session = {
                "quiz_id": quiz_id,
                "username": username,
                "course": course,
                "week": week,
                "question_plan": question_plan,
                "current_question_index": first_index,
                "current_question": first_question,
                "answers": [],
                "start_time": datetime.now().isoformat(),
                "orchestrator_context": orchestrator_context,
                "trackers": trackers,
                "motivation_tracking": {
                    "initial_state": motivation_state,
                    "state_changes": [],
                    "adaptations_applied": []
                }
            }
            
            logger.debug(f"Started quiz {quiz_id} with {len(question_plan)} questions using MCP RAG")
            logger.debug(f"Initial motivation state: {motivation_state}")
            
            return quiz_session
            
        except Exception as e:
            logger.exception(f"Failed to start quiz: {e}")
            return None
    
    def get_next_question(self, quiz_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Generate and retrieve the next question in the quiz sequence.
        Enhanced to handle both synchronous and asynchronous execution contexts.
        """
        try:
            orchestrator_context = quiz_data.get('orchestrator_context')
            plan = quiz_data["question_plan"]

            # Move to the next planned question; if one can't be generated, skip to the next
            # rather than ending the quiz early.
            while quiz_data["current_question_index"] + 1 < len(plan):
                quiz_data["current_question_index"] += 1
                next_question_plan = plan[quiz_data["current_question_index"]]
                next_question = self._generate_question(
                    quiz_data["course"], next_question_plan, orchestrator_context=orchestrator_context,
                    trackers=quiz_data.setdefault("trackers", self._new_trackers()))
                if next_question:
                    quiz_data["current_question"] = next_question
                    return quiz_data
                logger.error(f"Could not generate question {quiz_data['current_question_index'] + 1}; skipping it")

            logger.debug(f"Quiz {quiz_data['quiz_id']} completed")
            return None

        except Exception as e:
            logger.error(f"Failed to get next question: {e}")
            return None

    def _apply_orchestrator_recommendations_fixed(
        self, 
        question_plan: Dict[str, Any], 
        orchestrator_context: Dict[str, Any],
        type_counts: Dict[str, int],
    ) -> Dict[str, Any]:
        """
        Apply orchestrator recommendations while preserving question variety.
        
        This method carefully applies cognitive load and motivation-based
        adjustments to question generation while maintaining the diversity
        necessary for comprehensive assessment.
        
        Args:
            question_plan: Original question specifications
            orchestrator_context: Context containing recommendations
            
        Returns:
            Modified question plan with applied recommendations
        """
        scaffolding = orchestrator_context.get("scaffolding_strategy", {})
        
        original_type = question_plan["type"]
        
        # Conservative type override based on cognitive state
        should_override = False
        recommended_type = original_type
        
        cognitive_state = orchestrator_context.get('cognitive_state')
        if cognitive_state:
            # A stored (JSON) context holds a dict; a fresh orchestrator result holds the object
            cognitive_load = (cognitive_state.get('cognitive_load', 5.0) if isinstance(cognitive_state, dict)
                              else getattr(cognitive_state, 'cognitive_load', 5.0))
            
            # Apply overrides only in extreme cases
            if cognitive_load > 8.0 and original_type == "open_ended":
                recommended_type = "multiple_choice"
                should_override = True
                logger.debug(f"🚨 High CL override: {original_type} → {recommended_type}")
            elif cognitive_load < 2.0 and original_type == "true_false" and type_counts["open_ended"] < 2:
                recommended_type = "open_ended"
                should_override = True
                logger.debug(f"🚀 Low CL override: {original_type} → {recommended_type}")
        
        # Apply motivation-based adjustments
        motivation_state = orchestrator_context.get('motivation_state', 'motivation_plateau')
        if motivation_state == 'motivation_drop' and original_type == "open_ended":
            recommended_type = "multiple_choice"
            should_override = True
            logger.debug(f"💝 Motivation support override: {original_type} → {recommended_type}")
        elif motivation_state == 'maintained_high' and original_type == "true_false" and type_counts["open_ended"] < 2:
            recommended_type = "open_ended"
            should_override = True
            logger.debug(f"🚀 High motivation challenge override: {original_type} → {recommended_type}")
        
        # Apply override if justified
        if should_override:
            question_plan["type"] = recommended_type
            logger.debug(f"🔄 Question type override applied: {original_type} → {recommended_type}")
        else:
            logger.debug(f"✅ Question type preserved: {original_type}")
        
        # The planned type was already counted at planning time; only move the count on override.
        if should_override and recommended_type != original_type:
            type_counts[original_type] = max(0, type_counts.get(original_type, 0) - 1)
            type_counts[recommended_type] = type_counts.get(recommended_type, 0) + 1
        
        # Apply difficulty adjustments
        difficulty_adjustment = scaffolding.get("difficulty_adjustment", "maintain")
        question_plan["adjusted_difficulty"] = self._calculate_adjusted_difficulty(
            question_plan.get("base_difficulty", 0.5), 
            difficulty_adjustment
        )
        
        # Set support parameters
        question_plan["support_level"] = scaffolding.get("support_level", "medium")
        question_plan["hint_count"] = scaffolding.get("hint_count", 2)
        question_plan["example_count"] = scaffolding.get("example_count", 2)
        
        # Apply content adaptations
        content_adaptations = scaffolding.get("content_adaptations", {})
        question_plan["content_density"] = content_adaptations.get("content_density", "moderate")
        question_plan["visualization_level"] = content_adaptations.get("visualization_level", "moderate_visual")
        
        return question_plan

    def _calculate_adjusted_difficulty(self, base_difficulty: float, adjustment: str) -> float:
        """
        Calculate adjusted difficulty based on orchestrator recommendations.
        
        Args:
            base_difficulty: Original difficulty level (0.0 to 1.0)
            adjustment: Adjustment directive from orchestrator
            
        Returns:
            Adjusted difficulty value bounded between 0.1 and 0.9
        """
        adjustments = {
            "decrease_significantly": -0.3,
            "decrease": -0.15,
            "maintain": 0.0,
            "increase": 0.15,
            "increase_significantly": 0.3
        }
        
        adjustment_value = adjustments.get(adjustment, 0.0)
        adjusted = base_difficulty + adjustment_value
        
        return max(0.1, min(0.9, adjusted))

    def _has_code_content(self, content: str) -> bool:
        """
        Determine if content contains programming code snippets.
        
        Args:
            content: Text content to analyze
            
        Returns:
            Boolean indicating presence of code
        """
        code_indicators = [
            'import ', 'from ', 'def ', 'class ', '= ', '()', '.fit(', '.predict(', 
            'sklearn', 'numpy', 'pandas', 'matplotlib', '```python', 'print(',
            'RandomForest', 'LogisticRegression', 'train_test_split', 'X_train', 'y_train'
        ]
        
        content_lower = content.lower()
        return any(indicator.lower() in content_lower for indicator in code_indicators)

    def _create_orchestrator_guided_prompt(
        self, 
        question_plan: Dict[str, Any], 
        content: str, 
        orchestrator_context: Optional[Dict[str, Any]],
        previous_questions: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Create comprehensive prompt for question generation with orchestrator guidance.
        
        This method constructs a detailed prompt that incorporates motivation state,
        cognitive load considerations, and scaffolding strategies to generate
        questions optimally suited to the learner's current state.
        
        Args:
            question_plan: Question specifications and metadata
            content: Retrieved course content for context
            orchestrator_context: Optional adaptive generation parameters
            
        Returns:
            Complete prompt string for question generation
        """
        base_prompt = self._create_enhanced_generation_prompt(question_plan, content, previous_questions)
        
        if not orchestrator_context:
            return base_prompt
        
        motivation_state = orchestrator_context.get('motivation_state', 'motivation_plateau')
        scaffolding = orchestrator_context.get('scaffolding_strategy', {})
        
        motivation_guidance = f"""
        **EXPLICIT MOTIVATION-INFORMED ADAPTATIONS:**
        
        Current Student Motivation State: {motivation_state.upper()}
        
        SPECIFIC CONTENT ADAPTATIONS REQUIRED:
        """
        
        # Apply state-specific generation guidelines
        if motivation_state == 'motivation_drop':
            motivation_guidance += """
        - MOTIVATION DROP DETECTED - Apply supportive intervention
        - Use encouraging, non-controlling language
        - Reduce cognitive pressure with simpler question structure
        - Include extra scaffolding and hints
        - Focus on effort and process rather than just correctness
        - Provide choices where possible
        - Add emotional support elements
        - Break complex concepts into smaller, manageable pieces
        """
        elif motivation_state == 'maintained_high':
            motivation_guidance += """
        - HIGH MOTIVATION DETECTED - Apply challenge escalation
        - Increase question complexity and depth
        - Include advanced applications and transfer opportunities  
        - Offer stretch goals and extension activities
        - Use challenging, engaging language
        - Encourage peer teaching opportunities
        - Present real-world, complex scenarios
        - Minimize scaffolding to encourage independent thinking
        """
        elif motivation_state == 'cold_start':
            motivation_guidance += """
        - BASELINE ESTABLISHMENT PHASE - Apply welcoming support
        - Use especially welcoming, encouraging tone
        - Provide positive reinforcement without performance pressure
        - Include clear, friendly explanations
        - Set up supportive learning environment
        - Focus on exploration and discovery
        - Avoid overwhelming with too much information
        - Use collaborative language
        """
        elif motivation_state == 'motivation_plateau':
            motivation_guidance += """
        - STABLE ENGAGEMENT - Apply process-oriented support
        - Celebrate effort and strategic thinking
        - Provide mastery-oriented feedback
        - Emphasize growth mindset principles
        - Focus on learning process and improvement
        - Offer metacognitive prompts
        - Balance challenge with support
        """
        
        # Add scaffolding strategy guidance
        strategy_type = scaffolding.get('strategy_type', 'procedural')
        motivation_guidance += f"""
        
        SCAFFOLDING STRATEGY: {strategy_type.upper()}
        """
        
        if strategy_type == "conceptual":
            motivation_guidance += """
        - Focus on core concepts and relationships
        - Use clear explanations and analogies
        - Include conceptual understanding checks
        - Emphasize theoretical foundations
        """
        elif strategy_type == "procedural":
            motivation_guidance += """
        - Emphasize step-by-step processes
        - Break down complex procedures
        - Include procedural knowledge checks
        - Focus on implementation details
        """
        elif strategy_type == "strategic":
            motivation_guidance += """
        - Focus on problem-solving strategies
        - Compare different approaches
        - Include strategy selection opportunities
        - Emphasize decision-making processes
        """
        elif strategy_type == "metacognitive":
            motivation_guidance += """
        - Encourage self-reflection and awareness
        - Include confidence and process questions
        - Ask about learning strategies
        - Promote self-monitoring
        """
        
        return base_prompt + "\n\n" + motivation_guidance

    def _create_enhanced_generation_prompt(self, question_plan: Dict[str, Any], content: str,
                                           previous_questions: Optional[List[Dict[str, Any]]] = None) -> str:
        """
        Create detailed prompt for question generation with variety requirements.
        ENHANCED: Better control over when to include code in questions.
        
        Args:
            question_plan: Question specifications and metadata
            content: Retrieved course content for context
            
        Returns:
            Base prompt string for question generation
        """
        question_type = question_plan["type"]
        skill_name = question_plan["skill_name"]
        description = question_plan["description"]
        question_number = question_plan.get("question_number", 1)
        lo_question_count = question_plan.get("lo_question_count", 0)
        
        # Check if this should be a coding question
        include_code = question_plan.get("include_code", False)
        
        previous_questions = previous_questions or []
        
        prompt = f"""
        Generate a {question_type} question for the specific skill: "{skill_name}"
        
        SKILL CONTEXT:
        - Skill: {skill_name}
        - Description: {description}
        - Question #{question_number} in quiz (#{lo_question_count + 1} for this Learning Objective)
        
        VARIETY REQUIREMENTS:
        - This is question #{question_number} - ensure it's different from previous questions
        - Previous question types used: {[q.get('type') for q in previous_questions[-3:]]}
        - Avoid repetitive patterns
        - Make each question unique and engaging
        
        RELEVANT COURSE CONTENT:
        {content[:1200]}
        
        **STRATEGIC QUESTION DESIGN:**

        Question #{question_number} Strategy:
        {self._get_question_strategy(question_number, lo_question_count, skill_name)}

        **NEVER BUILD A QUESTION ON A FALSE PREMISE:**
        - Every claim the question states as fact (including what the "correct" answer asserts) must actually
          be supported by the course content above -- don't assert something is true, or label an example a
          certain way, just because it makes for a tidy question.
        - Never use a toy or illustrative example to stand in for something that example can't actually show.
          A short snippet of code, or a simple worked example, cannot by itself demonstrate genuine
          understanding, consciousness, or general/"strong" intelligence -- don't build a question whose
          premise or expected answer claims it does.

        **CODE INCLUSION GUIDELINES:**
        """

        if include_code:
            prompt += """
            - THIS SHOULD BE A CODING QUESTION! You MUST include actual CODE_LANGUAGE code in the question.
            - DO NOT just reference code - you must CREATE and INCLUDE the actual code snippet
            - Format the code properly with ```python blocks
            - Code should be 3-10 lines, clear and readable
            - The code MUST appear IN the question text itself
            - Examples of good coding questions:
              * "What will this code output?\n```python\nfor i in range(3):\n    print(i)\n```"
              * "Find the error in this code:\n```python\ndef add(a, b):\n    return a + b\nresult = add(5)\n```"
            - NEVER say "Consider the following code" without actually showing the code
            - If generating a Q-learning question about reinforcement learning, CREATE a simple Q-table example
            - Any code you write must come from, or closely follow, the course content above -- don't invent an
              unrelated toy example (e.g. two functions that only differ in whether they compute one thing or
              several) and then claim it demonstrates a concept the code itself can't actually show.
            """.replace("CODE_LANGUAGE", question_plan.get("code_language", "python").capitalize())
        elif not question_plan.get("allows_code", False):
            prompt += f"""
            - This course ({question_plan.get('course_name', 'this course')}) does not involve programming.
            - Do not include code, pseudo-code, programming libraries or software examples.
            - Focus on the course's own concepts, theory and real-world application.
            """
        else:
            prompt += """
            - DO NOT include code in this question unless absolutely essential for understanding
            - Focus on conceptual understanding, theory, or high-level application
            - Use plain language without code snippets
            - If you must mention code-related concepts, describe them in words, not code
            """
        
        
        # if include_code:
        #     prompt += """
        # - THIS SHOULD BE A CODING QUESTION! Include Python code in the question.
        # - Make the code educational and well-formatted with ```python blocks
        # - Code should be 3-10 lines, clear and readable
        # - Focus on practical implementation or code analysis
        # - Examples: debugging code, predicting output, completing implementation, identifying errors
        # """
        # else:
        #     prompt += """
        # - DO NOT include code in this question unless absolutely essential for understanding
        # - Focus on conceptual understanding, theory, or high-level application
        # - Use plain language without code snippets
        # - If you must mention code-related concepts, describe them in words, not code
        # """
        
        prompt += "\n\n**QUESTION TYPE SPECIFIC REQUIREMENTS:**\n"
        
        # Add type-specific formatting requirements
        # FIXED: All elif statements must be at the same indentation level as the if

        # Also update the multiple choice with code format section:
        
        if question_type == "multiple_choice":
            if include_code:
                prompt += """
        MULTIPLE CHOICE WITH CODE FORMAT - Return JSON:
        {
            "question": "Question with ACTUAL code included. Example: 'What will this code output?\\n```python\\nx = [1, 2, 3]\\nprint(x[0])\\n```'",
            "options": ["A) 1", "B) 2", "C) 3", "D) [1, 2, 3]"],
            "correct_answer": "A",
            "explanation": "The code accesses the first element of the list, which is 1."
        }
        
        IMPORTANT: The question field MUST contain the actual code snippet, not just reference it!
        For Q-learning/reinforcement learning, create a simple example like:
        ```python
        Q = [[0, 0], [0, 0]]  # Q-table for 2 states, 2 actions
        Q[0][1] = 0.1  # Update Q-value
        print(Q)
        ```
        """

        
        # if question_type == "multiple_choice":
        #     if include_code:
        #         prompt += """
    # MULTIPLE CHOICE WITH CODE FORMAT - Return JSON:
    # {
    #     "question": "Question involving code analysis or implementation",
    #     "options": ["A) option1", "B) option2", "C) option3", "D) option4"],
    #     "correct_answer": "A",
    #     "explanation": "Clear explanation with code reasoning"
    # }
    
    # CODING QUESTION APPROACHES:
    # - Output prediction: "What will this code output?"
    # - Error identification: "Which line contains an error?"
    # - Implementation choice: "Which implementation is most efficient?"
    # - Code completion: "What should replace the ??? to make this work?"
    # """
            else:
                prompt += """
    MULTIPLE CHOICE FORMAT - Return JSON:
    {
        "question": "Engaging conceptual question without code",
        "options": ["A) option1", "B) option2", "C) option3", "D) option4"],
        "correct_answer": "A",
        "explanation": "Clear explanation with reasoning"
    }
    
    VARIETY APPROACHES:
    - Conceptual: "Which principle best explains..."
    - Application: "In a real-world scenario involving..."
    - Comparison: "What distinguishes X from Y..."
    - Problem-solving: "Given this situation..."
    - Analysis: "The following approach demonstrates..."
    """
        elif question_type == "true_false":  # FIXED: This elif is now at the correct indentation
            if include_code:
                prompt += """
    TRUE/FALSE WITH CODE FORMAT - Return JSON:
    {
        "question": "Statement about code behavior or implementation",
        "correct_answer": "True" or "False",
        "explanation": "Detailed explanation of why the statement is true/false"
    }
    
    CODE-BASED APPROACHES:
    - Code behavior: "This code will always produce the same output regardless of input order."
    - Implementation correctness: "The following implementation correctly handles edge cases."
    - Performance claims: "This algorithm has O(n) time complexity."
    """
            else:
                prompt += """
    TRUE/FALSE FORMAT - Return JSON:
    {
        "question": "Clear conceptual statement without code",
        "correct_answer": "True" or "False",
        "explanation": "Detailed explanation of why the statement is true/false"
    }
    
    VARIETY APPROACHES:
    - Definitional: "Concept X is defined as..."
    - Comparative: "Approach A is generally more effective than Approach B for..."
    - Situational: "In situation Y, technique X is always the best choice."
    """
        elif question_type == "fill_in_blank":  # FIXED: Correct indentation
            if include_code:
                prompt += """
    FILL IN THE BLANK WITH CODE FORMAT - Return JSON:
    {
        "question": "Code snippet with exactly one _____ blank to complete",
        "correct_answer": "precise code term or expression",
        "explanation": "Why this completes the code correctly"
    }
    
    CODE COMPLETION APPROACHES:
    - Method names: "model._____(X_train, y_train)  # Train the model"
    - Parameters: "clf = RandomForestClassifier(n_estimators=_____)  # Set number of trees"
    - Operations: "X_scaled = _____.fit_transform(X)  # Normalize the features"
    """
            else:
                prompt += """
    FILL IN THE BLANK FORMAT - Return JSON:
    {
        "question": "Complete sentence with exactly one _____ blank (no code)",
        "correct_answer": "precise term or short phrase",
        "explanation": "Why this answer fits the context"
    }
    
    VARIETY APPROACHES:
    - Technical terms: "The _____ algorithm is particularly effective for..."
    - Concepts: "The key principle behind this approach is _____"
    - Definitions: "_____ is the process by which..." (a key term from the course content)
    """
        else:  # open_ended - FIXED: else is also at correct indentation
            if include_code:
                prompt += """
    OPEN-ENDED WITH CODE FORMAT - Return JSON:
    {
        "question": "Question requiring code analysis or implementation explanation",
        "sample_answer": "Comprehensive answer including code understanding (3-4 sentences)",
        "key_points": ["key_point_1", "key_point_2", "key_point_3"],
        "explanation": "What constitutes a good answer"
    }
    
    CODE-FOCUSED APPROACHES:
    - Debug analysis: "Explain why this code produces unexpected results and how to fix it"
    - Implementation design: "Describe how you would implement X, including key methods"
    - Code comparison: "Compare these two implementations and explain trade-offs"
    """
            else:
                prompt += """
    OPEN-ENDED FORMAT - Return JSON:
    {
        "question": "Thought-provoking conceptual question without code",
        "sample_answer": "Comprehensive example answer (3-4 sentences)",
        "key_points": ["key_point_1", "key_point_2", "key_point_3"],
        "explanation": "What constitutes a good answer"
    }
    
    VARIETY APPROACHES:
    - Analysis: "Analyze the trade-offs between..."
    - Application: "Describe how you would apply X in scenario Y..."
    - Evaluation: "Evaluate the effectiveness of approach X for..."
    - Design: "Design a solution that addresses..."
    - Comparison: "Compare and contrast methods X and Y..."
    """
        
        return prompt

    def _get_question_strategy(self, question_number: int, lo_question_count: int, skill_name: str) -> str:
        """
        Determine strategic approach for question generation.
        
        This method selects an appropriate questioning strategy based on
        the question's position in the sequence and the skill being assessed.
        
        Args:
            question_number: Overall question number in quiz
            lo_question_count: Question number within learning objective
            skill_name: Name of the skill being assessed
            
        Returns:
            Strategy description for question generation
        """
        skill_lower = skill_name.lower()
        
        strategies = [
            "Focus on conceptual understanding - test core principles",
            "Emphasize practical application - how is this used?",
            "Compare and contrast - how does this differ from alternatives?",
            "Problem-solving focus - given a scenario, what approach?",
            "Implementation details - technical specifics and methods"
        ]
        
        # Strategic selection based on position and content
        if lo_question_count == 0:
            if any(term in skill_lower for term in ['concept', 'definition', 'understanding']):
                return strategies[0]
            else:
                return strategies[1]
        elif lo_question_count == 1:
            return strategies[2]
        else:
            return strategies[(question_number % len(strategies))]

    def _track_question_for_variety(self, question_data: Dict, question_plan: Dict, history: List[Dict]) -> None:
        """
        Track generated questions to ensure variety and prevent repetition.
        
        Args:
            question_data: Generated question information
            question_plan: Original question specifications
        """
        history.append({
            'type': question_data['type'],
            'skill': question_plan['skill_name'],
            'has_code': '```' in question_data['text']
        })
        del history[:-10]

    def _parse_generated_question(self, response_text: str, question_type: str) -> Optional[Dict[str, Any]]:
        """Parse model output into a question and check it can actually be graded.

        Returns None (so the caller retries) if the JSON is missing, or if the fields the
        grader needs are absent or inconsistent: multiple choice needs 2-6 options and a
        correct_answer that names one of them; true/false needs a True/False answer;
        fill-in-blank needs an expected answer; open-ended needs a sample answer or key points.
        """
        data = grading.parse_json_object(response_text)
        if not data or not str(data.get("question", "")).strip():
            logger.error(f"Generated question has no JSON or no 'question': {response_text[:200]}")
            return None

        if question_type == "multiple_choice":
            options = data.get("options")
            if not isinstance(options, list) or not 2 <= len(options) <= 6:
                logger.error(f"Multiple-choice question has invalid options: {options}")
                return None
            letters = {grading.choice_letter(str(o)) for o in options}
            answer = grading.choice_letter(str(data.get("correct_answer", "")))
            if answer is None or answer not in letters:
                logger.error(f"Multiple-choice correct_answer {data.get('correct_answer')!r} is not one of the options")
                return None
            data["correct_answer"] = answer
        elif question_type == "true_false":
            value = grading.to_bool(data.get("correct_answer"))
            if value is None:
                logger.error(f"True/false question has no True/False answer: {data.get('correct_answer')!r}")
                return None
            data["correct_answer"] = "True" if value else "False"
        elif question_type == "fill_in_blank":
            if not str(data.get("correct_answer", "")).strip():
                logger.error("Fill-in-blank question has no expected answer")
                return None
        else:  # open_ended
            if not (str(data.get("sample_answer", "")).strip() or data.get("key_points")):
                logger.error("Open-ended question has neither a sample answer nor key points")
                return None
            if not isinstance(data.get("key_points", []), list):
                data["key_points"] = [str(data["key_points"])]
            data["correct_answer"] = data.get("sample_answer", "")

        data["type"] = question_type
        data["text"] = self._format_code_blocks(str(data["question"]))
        data["generated_at"] = datetime.now().isoformat()
        data["content_hash"] = hash(data["text"]) % 10000
        return data

    def _format_code_blocks(self, text: str) -> str:
        """
        Format code blocks for proper display in the interface.
        FIXED: Only format actual code blocks that are already marked with ```
        or contain multiple strong code indicators.
        
        Args:
            text: Raw text potentially containing code
            
        Returns:
            Text with properly formatted code blocks
        """
        # If already formatted with code blocks, return as-is
        if '```python' in text or '```' in text:
            return text
        
        lines = text.split('\n')
        formatted_lines = []
        in_code_block = False
        code_lines = []
        
        for line in lines:
            # FIXED: Much stricter code detection - require multiple indicators
            # or specific patterns that are unlikely in normal text
            code_indicators = 0
            
            # Strong indicators (worth 2 points each)
            strong_indicators = [
                ('import ', line.startswith('import ')),  # Must start with import
                ('from ', line.startswith('from ') and ' import ' in line),  # Full import statement
                ('def ', line.strip().startswith('def ')),  # Function definition
                ('class ', line.strip().startswith('class ')),  # Class definition
                ('.fit(', True),  # Method calls with parentheses
                ('.predict(', True),
                ('.transform(', True),
                ('sklearn', True),  # Library names
                ('np.', 'np.' in line),  # NumPy calls
                ('pd.', 'pd.' in line),  # Pandas calls
                ('plt.', 'plt.' in line),  # Matplotlib calls
            ]
            
            # Weaker indicators (worth 1 point each) - only count if specific patterns
            weak_indicators = [
                ('=', '=' in line and any(p in line for p in ['X_', 'y_', 'model', 'clf', 'reg'])),
                ('print(', 'print(' in line),
                ('for ', line.strip().startswith('for ') and ' in ' in line),  # For loops
                ('if ', line.strip().startswith('if ') and ':' in line),  # If statements
                ('return ', line.strip().startswith('return ')),
                ('[', ('[' in line and ']' in line) and any(c in line for c in ['X', 'y', 'data', 'df'])),
            ]
            
            # Count strong indicators
            for pattern, condition in strong_indicators:
                if pattern in line and condition:
                    code_indicators += 2
            
            # Count weak indicators
            for pattern, condition in weak_indicators:
                if condition:
                    code_indicators += 1
            
            # Require at least 3 points to consider it code
            # This prevents single words like "from" in normal text from triggering
            is_likely_code = code_indicators >= 3
            
            if is_likely_code:
                if not in_code_block:
                    in_code_block = True
                    code_lines = [line]
                else:
                    code_lines.append(line)
            else:
                if in_code_block:
                    # End code block only if we have actual code content
                    if code_lines and len(code_lines) > 1:  # Require multiple lines
                        formatted_lines.append("```python")
                        formatted_lines.extend(code_lines)
                        formatted_lines.append("```")
                    else:
                        # False positive - just add the lines normally
                        formatted_lines.extend(code_lines)
                    code_lines = []
                    in_code_block = False
                formatted_lines.append(line)
        
        # Handle trailing code block
        if in_code_block and code_lines and len(code_lines) > 1:
            formatted_lines.append("```python")
            formatted_lines.extend(code_lines)
            formatted_lines.append("```")
        elif code_lines:
            # Single line that looked like code - don't format it
            formatted_lines.extend(code_lines)
        
        return '\n'.join(formatted_lines)
    
    
    def _should_include_coding_question_from_plan(
        self,
        question_plan: Dict[str, Any],
        coding: Dict[str, Any],
    ) -> bool:
        """
        Determine if this question should include coding based on question_plan metadata.
        ``coding`` is this quiz's tracker ({"count", "questions"}).
        """
        current_coding_count = coding['count']
        total_questions = question_plan.get('total_questions', 11)
        
        # Limit to 1-2 coding questions per quiz (roughly 10-20% of questions)
        max_coding_questions = min(2, max(1, int(total_questions * 0.15)))
        
        if current_coding_count >= max_coding_questions:
            return False
        
        # Get metadata from question_plan
        skill_category = question_plan.get('skill_category', '').lower()
        cognitive_level = question_plan.get('cognitive_level', '').lower()
        skill_name = question_plan.get('skill_name', '').lower()
        complexity = question_plan.get('complexity', '').lower()
        question_number = question_plan.get('question_number', 1)
        
        # High priority for coding questions
        high_priority_coding = any([
            skill_category == 'application',
            skill_category == 'analytical' and any(term in skill_name for term in ['implement', 'code', 'build']),
            cognitive_level in ['apply', 'create'],
            complexity == 'advanced' and skill_category in ['analytical', 'application'],
            any(term in skill_name for term in ['implement', 'code', 'program', 'develop', 'build', 'algorithm', 'debug'])
        ])
        
        # Medium priority for coding questions  
        medium_priority_coding = any([
            skill_category == 'analytical',
            cognitive_level == 'analyze',
            complexity in ['intermediate', 'advanced'],
            any(term in skill_name for term in ['optimize', 'trace', 'predict', 'output'])
        ])
        
        # Strategic placement - prefer mid-quiz for coding questions (questions 4-8)
        optimal_position = 4 <= question_number <= 8
        
        include_code = False
        
        if high_priority_coding:
            # Always include if high priority and haven't hit limit
            include_code = True
            logger.debug(f"🎯 High priority coding for '{skill_name}' (category: {skill_category}, level: {cognitive_level})")
        elif medium_priority_coding and optimal_position:
            # Include for medium priority if in optimal position
            include_code = current_coding_count == 0
            if include_code:
                logger.debug(f"📍 Medium priority coding for '{skill_name}' at position {question_number}")
        elif question_number == 6 and current_coding_count == 0:
            # Ensure at least one coding question around the middle
            include_code = True
            logger.debug(f"⚡ Forcing coding question at position 6 for balance")
        
        # Update tracker if including code
        if include_code:
            coding['count'] += 1
            coding['questions'].append(question_number)
            logger.debug(f"📝 Coding question #{question_number}: '{skill_name}'")
            logger.debug(f"Total coding questions: {current_coding_count + 1}/{max_coding_questions}")
        
        return include_code
        
    def _select_variety_enforced_question_type(
        self, 
        go, 
        lo, 
        question_number: int, 
        lo_question_count: int, 
        motivation_state: str = None, 
        type_counts: Optional[Dict[str, int]] = None,
    ) -> str:
        """
        Select question type ensuring variety across the quiz.
        
        This method maintains balanced distribution of question types
        while considering the skill being assessed and learner motivation.
        
        Args:
            go: Granular objective being assessed
            lo: Learning objective context
            question_number: Overall question position
            lo_question_count: Position within learning objective
            motivation_state: Current learner motivation level
            type_counts: this quiz's running count of planned types (updated here)
            
        Returns:
            Selected question type string
        """
        # Retrieve current type distribution
        if type_counts is None:
            type_counts = self._new_trackers()["type_counts"]
        total_questions = sum(type_counts.values())
        
        # Target distribution for balance
        target_distribution = {
            "multiple_choice": 0.4,
            "true_false": 0.2,
            "fill_in_blank": 0.2,
            "open_ended": 0.2
        }
        
        # Identify under-represented types
        available_types = []
        for qtype, target_ratio in target_distribution.items():
            current_ratio = type_counts[qtype] / max(1, total_questions)
            if current_ratio < target_ratio:
                available_types.append(qtype)
        
        # Ensure all types remain available
        if not available_types:
            available_types = list(target_distribution.keys())
        
        # Strategic selection based on skill content
        skill_name = go.skill_name.lower()
        
        if "concept" in skill_name or "definition" in skill_name:
            preferred_types = ["multiple_choice", "true_false"]
        elif "implement" in skill_name or "code" in skill_name:
            preferred_types = ["fill_in_blank", "multiple_choice"]
        elif "analyze" in skill_name or "compare" in skill_name:
            preferred_types = ["open_ended", "multiple_choice"]
        else:
            preferred_types = ["multiple_choice", "true_false"]
        
        # Select from available types with preference
        selected_type = None
        for pref_type in preferred_types:
            if pref_type in available_types:
                selected_type = pref_type
                break
        
        # Fallback to first available
        if not selected_type:
            selected_type = available_types[0]
        
        # Apply motivation-based adjustments
        if motivation_state == 'motivation_drop' and selected_type == "open_ended":
            alternative_types = [t for t in available_types if t != "open_ended"]
            if alternative_types:
                selected_type = alternative_types[0]
        elif motivation_state == 'maintained_high' and selected_type == "true_false":
            if "open_ended" in available_types:
                selected_type = "open_ended"
        
        # Update tracking
        type_counts[selected_type] += 1
        
        logger.debug(f"Q{question_number} - Selected type: {selected_type} (Available: {available_types})")
        logger.debug(f"Q{question_number} - Current distribution: {type_counts}")
        
        return selected_type

    def _evaluate_answer_with_motivation_context(
        self, 
        question: Dict[str, Any], 
        student_answer: str, 
        orchestrator_context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Evaluate answer with motivation-aware adjustments.
        
        This method adapts evaluation feedback based on the learner's
        current motivation state, providing appropriate encouragement
        or challenge as needed.
        
        Args:
            question: Question data including correct answer
            student_answer: The learner's response
            orchestrator_context: Context containing motivation state
            
        Returns:
            Evaluation dictionary with motivation-adjusted feedback
        """
        # Perform base evaluation
        base_evaluation = self._evaluate_answer(question, student_answer)
        adjusted_evaluation = base_evaluation.copy()
        if not base_evaluation.get("graded", False):
            return adjusted_evaluation

        # Motivation changes the wording of feedback only; the score and verdict stay as graded.
        motivation_state = orchestrator_context.get('motivation_state', 'motivation_plateau')
        explanation = self._ensure_conversational_language(base_evaluation.get('explanation', ''))
        is_correct = base_evaluation.get('correct', False)

        if motivation_state == 'motivation_drop':
            adjusted_evaluation['explanation'] = (
                f"Excellent work! {explanation}" if is_correct
                else f"Good attempt! {explanation} Let's break this down step by step."
            )
        elif motivation_state == 'maintained_high':
            adjusted_evaluation['explanation'] = (
                f"Outstanding! {explanation} Ready for a more advanced perspective?" if is_correct
                else f"{explanation} What other approaches might you consider?"
            )
        elif motivation_state == 'cold_start':
            adjusted_evaluation['explanation'] = (
                f"Great start! {explanation}" if is_correct
                else f"Welcome to learning! {explanation} Don't worry - this is all part of the process."
            )
        else:  # motivation_plateau
            adjusted_evaluation['explanation'] = explanation

        # Add motivation metadata
        adjusted_evaluation['motivation_informed'] = True
        adjusted_evaluation['motivation_state'] = motivation_state
        
        return adjusted_evaluation
    def _evaluate_answer(self, question: Dict[str, Any], student_answer: str) -> Dict[str, Any]:
        """Grade one answer. Multiple choice and true/false are exact; free text uses the LLM
        grader. Any grading failure returns an ungraded result (correct=None)."""
        question_type = question.get("type", "multiple_choice")
        explanation = question.get("explanation", "")

        if question_type == "multiple_choice":
            return grading.grade_multiple_choice(
                student_answer, question.get("correct_answer", ""), question.get("options", []), explanation
            )
        if question_type == "true_false":
            return grading.grade_true_false(student_answer, question.get("correct_answer"), explanation)

        reference = {"question": question.get("text", "")}
        if question_type == "fill_in_blank":
            reference["expected answer"] = question.get("correct_answer", "")
        else:
            reference["sample answer"] = question.get("sample_answer") or question.get("correct_answer", "")
            reference["key points"] = "; ".join(question.get("key_points", []))
        result = grading.grade_with_llm(
            self.openai_client, kind=question_type, reference=reference, student_answer=student_answer
        )
        if result["graded"] and not result.get("explanation"):
            result["explanation"] = explanation
        return result

    def _ensure_conversational_language(self, explanation: str) -> str:
        """
        Ensure explanation uses conversational second-person language.
        
        This method converts any third-person references to second-person
        to maintain a personal, engaging tone in feedback.
        
        Args:
            explanation: Original explanation text
            
        Returns:
            Explanation with conversational language
        """
        if not explanation:
            return "Keep working on this concept!"
        
        conversational_explanation = explanation
        
        # Replace third-person patterns with second-person
        replacements = [
            ("the student", "you"),
            ("The student", "You"),
            ("student's", "your"),
            ("Student's", "Your"),
            ("the learner", "you"),
            ("The learner", "You"),
            ("learner's", "your"),
            ("Learner's", "Your"),
            ("they did not", "you did not"),
            ("They did not", "You did not"),
            ("they should", "you should"),
            ("They should", "You should"),
            ("their understanding", "your understanding"),
            ("Their understanding", "Your understanding"),
            ("their response", "your response"),
            ("Their response", "Your response")
        ]
        
        for old, new in replacements:
            conversational_explanation = conversational_explanation.replace(old, new)
        
        return conversational_explanation

    def submit_answer(self, quiz_data: Dict[str, Any], answer: str) -> Optional[Dict[str, Any]]:
        """
        Submit and evaluate a student answer with memory storage.
        
        This method processes answer submission, performs evaluation,
        stores the interaction for analytics, and updates the quiz session.
        
        Args:
            quiz_data: Current quiz session data
            answer: The learner's response
            
        Returns:
            Evaluation results or None on failure
        """
        try:
            current_question = quiz_data["current_question"]
            question_plan = quiz_data["question_plan"][quiz_data["current_question_index"]]
            
            # Retrieve orchestrator context for adaptive evaluation
            orchestrator_context = quiz_data.get('orchestrator_context')
            
            # Perform evaluation with optional motivation context
            if orchestrator_context:
                evaluation = self._evaluate_answer_with_motivation_context(
                    current_question, answer, orchestrator_context
                )
                logger.debug(f"🎯 Motivation-aware answer evaluation complete")
            else:
                evaluation = self._evaluate_answer(current_question, answer)
            
            # Store interaction in memory system
            username = quiz_data.get("username", "unknown_user")
            store_quiz_memory(
                self.redis_client,
                username,
                current_question,
                answer,
                evaluation.get("correct"),
                evaluation.get("score")
            )
            
            # Record answer in session
            answer_record = {
                "question_index": quiz_data["current_question_index"],
                "go_id": question_plan["go_id"],
                "question": current_question["text"],
                "student_answer": answer,
                "correct_answer": current_question.get("correct_answer"),
                "evaluation": evaluation,
                "timestamp": datetime.now().isoformat(),
                "motivation_state": orchestrator_context.get('motivation_state') if orchestrator_context else None
            }
            
            quiz_data["answers"].append(answer_record)
            
            return evaluation
            
        except Exception as e:
            logger.error(f"Failed to submit answer: {e}")
            return None
