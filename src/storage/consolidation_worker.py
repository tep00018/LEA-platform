# src/storage/consolidation_worker.py
"""
Memory Consolidation Worker
Processes short-term memories into long-term storage
"""

import json
import threading
from typing import Dict, List, Any
from datetime import datetime
from openai import OpenAI
import logging

logger = logging.getLogger(__name__)

class MemoryConsolidationWorker:
    """
    Worker that consolidates short-term memories into long-term storage
    Runs as a background process
    """
    
    def __init__(self, redis_client, openai_api_key: str = None):
        """Initialize consolidation worker"""
        self.redis_client = redis_client
        self.openai_client = OpenAI(api_key=openai_api_key) if openai_api_key else OpenAI()
        self.running = False
        self.consolidation_interval = 60  # Process every minute for testing (change to 300 for production)
        self.min_memories_to_consolidate = 3  # Minimum memories before consolidation
        self._stop = threading.Event()
        
        # Import schemas
        from src.storage.memory_schemas import MemorySchemas
        self.memory_schemas = MemorySchemas()
        
        logger.debug("Memory consolidation worker initialized")
    
    def start(self):
        """Run the consolidation loop on the current thread until ``stop()``."""
        self.running = True
        logger.debug("Starting memory consolidation worker...")
        while not self._stop.is_set():
            try:
                self._process_consolidation_queue()
                self._stop.wait(self.consolidation_interval)
            except Exception as e:
                logger.error(f"Consolidation worker error: {e}")
                self._stop.wait(30)
        self.running = False

    def start_in_background(self) -> threading.Thread:
        """Run the loop on a daemon thread."""
        thread = threading.Thread(target=self.start, name="memory-consolidation", daemon=True)
        thread.start()
        return thread

    def stop(self):
        """Stop the consolidation worker"""
        self._stop.set()
        logger.debug("Stopping memory consolidation worker...")
    
    def _process_consolidation_queue(self):
        """Process pending consolidation tasks"""
        try:
            redis_conn = self.redis_client.get_redis() if hasattr(self.redis_client, 'get_redis') else self.redis_client
            queue_key = self.memory_schemas.get_consolidation_queue_key()
            
            # Process up to 5 tasks per cycle
            for _ in range(5):
                # Get task from queue
                task_data = redis_conn.lpop(queue_key)
                if not task_data:
                    break
                
                task = json.loads(task_data)
                logger.debug(f"Processing consolidation for {task['username']} - {task['session_id']}")
                # Allow the session to be queued again once this attempt is under way.
                redis_conn.srem(self.memory_schemas.get_consolidation_pending_key(),
                                f"{task['username']}:{task['session_id']}")
                
                # Consolidate the session
                success = self._consolidate_session(
                    task['username'],
                    task['session_id']
                )
                
                if not success and task['attempts'] < 3:
                    # Re-queue if failed (with retry limit), unless it was queued again meanwhile
                    task['attempts'] += 1
                    if redis_conn.sadd(self.memory_schemas.get_consolidation_pending_key(),
                                       f"{task['username']}:{task['session_id']}"):
                        redis_conn.rpush(queue_key, json.dumps(task))
                    
        except Exception as e:
            logger.error(f"Queue processing error: {e}")
    
    def _consolidate_session(self, username: str, session_id: str) -> bool:
        """Consolidate a session's memories. Holds a per-session lock, so two workers (e.g.
        Streamlit and the API) never summarise or trim the same memories."""
        from src.storage.locks import LockBusy, redis_lock
        try:
            with redis_lock(self.redis_client, f"consolidate:{username}:{session_id}", timeout=120, wait=0,
                            keep_alive=True):
                return self._consolidate_session_locked(username, session_id)
        except LockBusy:
            logger.debug(f"Session {session_id} is being consolidated by another worker")
            return True

    def _consolidate_session_locked(self, username: str, session_id: str) -> bool:
        try:
            # Oldest first, so the ones summarised can be trimmed off the front afterwards
            redis_conn = self.redis_client.get_redis() if hasattr(self.redis_client, 'get_redis') else self.redis_client
            key = self.memory_schemas.get_short_term_key(username, session_id)
            raw_memories = redis_conn.lrange(key, 0, 49)
            memories = []
            for raw in raw_memories:
                try:
                    memories.append(json.loads(raw))
                except json.JSONDecodeError:
                    logger.warning(f"Skipping unreadable memory in session {session_id}")
            
            if len(memories) < self.min_memories_to_consolidate:
                logger.debug(f"Not enough memories to consolidate ({len(memories)} < {self.min_memories_to_consolidate})")
                return False
            
            # Generate summary
            summary = self._generate_summary(memories)
            
            # Extract key concepts
            key_concepts = self._extract_key_concepts(memories)
            
            # Analyze learning patterns
            patterns = self._analyze_learning_patterns(memories)
            
            # Store in long-term memory
            success = self._store_long_term_memory(
                username=username,
                session_id=session_id,
                summary=summary,
                key_concepts=key_concepts,
                patterns=patterns,
                original_count=len(memories)
            )
            
            if success:
                # Remove only the memories that were summarised; newer ones stay queued.
                self._cleanup_short_term(username, session_id, len(raw_memories))
                logger.debug(f"Successfully consolidated {len(memories)} memories for {username}")
            
            return success
            
        except Exception as e:
            logger.error(f"Session consolidation error: {e}")
            return False
    
    def _generate_summary(self, memories: List[Dict]) -> str:
        """Generate summary of interactions using GPT"""
        try:
            # Build context from memories
            interactions = []
            for mem in memories[:10]:  # Limit to prevent token overflow
                content = mem.get('content', {})
                if mem['type'] == 'chat':
                    interactions.append(f"Student asked: {content.get('message', 'unknown')}")
                elif mem['type'] == 'chat_response':
                    interactions.append(f"Assistant responded about: {content.get('user_message', 'unknown')[:100]}")
                elif mem['type'] == 'quiz':
                    interactions.append(f"Quiz: {content.get('question', 'unknown')[:100]} - Correct: {content.get('correct', False)}")
            
            prompt = f"""Summarize this learning session in 2-3 sentences:
            
            Interactions:
            {chr(10).join(interactions)}
            
            Focus on: main topics covered, student's understanding level, and key achievements."""
            
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=150,
                temperature=0.7
            )
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"Summary generation failed: {e}")
            return f"Session with {len(memories)} interactions on various topics."
    
    def _extract_key_concepts(self, memories: List[Dict]) -> List[str]:
        """Extract key concepts from memories"""
        concepts = set()
        
        for mem in memories:
            content = mem.get('content', {})
            
            # Extract from different memory types
            if 'go_id' in content:
                concepts.add(content['go_id'])
            if 'skill_name' in content:
                concepts.add(content['skill_name'])
            if 'course' in content and 'week' in content:
                concepts.add(f"{content['course']}_Week{content['week']}")
            
            # Extract from messages (simple keyword extraction)
            if 'message' in content:
                message = content['message'].lower()
                # Add logic for keyword extraction if needed
                if 'regression' in message:
                    concepts.add('regression')
                if 'classification' in message:
                    concepts.add('classification')
                if 'neural' in message:
                    concepts.add('neural_networks')
        
        return list(concepts)[:10]  # Limit to top 10 concepts
    
    def _analyze_learning_patterns(self, memories: List[Dict]) -> Dict[str, Any]:
        """Analyze learning patterns from memories"""
        patterns = {
            "total_interactions": len(memories),
            "interaction_types": {},
            "quiz_performance": {"correct": 0, "total": 0},
            "cognitive_load_avg": 0.0,
            "topics_covered": set(),
            "session_duration_estimate": 0
        }
        
        cognitive_loads = []
        timestamps = []
        
        for mem in memories:
            # Count interaction types
            mem_type = mem.get('type', 'unknown')
            patterns["interaction_types"][mem_type] = patterns["interaction_types"].get(mem_type, 0) + 1
            
            # Track quiz performance
            if mem_type == 'quiz':
                patterns["quiz_performance"]["total"] += 1
                if mem.get('content', {}).get('correct', False):
                    patterns["quiz_performance"]["correct"] += 1
            
            # Track cognitive load
            metadata = mem.get('metadata', {})
            if 'cognitive_load' in metadata:
                cognitive_loads.append(metadata['cognitive_load'])
            
            # Track timestamps for duration
            if 'timestamp' in mem:
                try:
                    timestamps.append(datetime.fromisoformat(mem['timestamp']))
                except:
                    pass
            
            # Track topics
            content = mem.get('content', {})
            if 'course' in content:
                patterns["topics_covered"].add(content['course'])
        
        # Calculate averages
        if cognitive_loads:
            patterns["cognitive_load_avg"] = sum(cognitive_loads) / len(cognitive_loads)
        
        # Estimate session duration
        if len(timestamps) >= 2:
            duration = (max(timestamps) - min(timestamps)).seconds / 60  # in minutes
            patterns["session_duration_estimate"] = round(duration, 1)
        
        # Convert set to list for JSON serialization
        patterns["topics_covered"] = list(patterns["topics_covered"])
        
        return patterns
    
    def _store_long_term_memory(
        self,
        username: str,
        session_id: str,
        summary: str,
        key_concepts: List[str],
        patterns: Dict[str, Any],
        original_count: int
    ) -> bool:
        """Store consolidated memory in long-term storage"""
        try:
            redis_conn = self.redis_client.get_redis() if hasattr(self.redis_client, 'get_redis') else self.redis_client
            
            # Determine course from patterns
            course = None
            if patterns.get("topics_covered"):
                course = patterns["topics_covered"][0]
            
            # Create long-term memory entry
            long_term_entry = self.memory_schemas.create_long_term_entry(
                session_id=session_id,
                summary=summary,
                key_concepts=key_concepts,
                learning_patterns=patterns,
                metadata={
                    "original_memory_count": original_count,
                    "consolidation_timestamp": datetime.now().isoformat()
                }
            )
            
            # Store in Redis
            key = self.memory_schemas.get_long_term_key(username, course)
            redis_conn.rpush(key, json.dumps(long_term_entry))
            
            # Set expiry to 90 days
            redis_conn.expire(key, 86400 * 90)
            
            logger.debug(f"Stored long-term memory for {username} - {course}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to store long-term memory: {e}")
            return False
    
    def _cleanup_short_term(self, username: str, session_id: str, consumed: int):
        """Drop the ``consumed`` oldest short-term memories (the ones just summarised)."""
        try:
            redis_conn = self.redis_client.get_redis() if hasattr(self.redis_client, 'get_redis') else self.redis_client
            key = self.memory_schemas.get_short_term_key(username, session_id)
            redis_conn.ltrim(key, consumed, -1)
            logger.debug(f"Cleaned up short-term memories for session {session_id}")
        except Exception as e:
            logger.error(f"Failed to cleanup short-term memories: {e}")

# Standalone function to run worker
def run_consolidation_worker(redis_client, openai_api_key: str = None):
    """Run the consolidation worker"""
    worker = MemoryConsolidationWorker(redis_client, openai_api_key)
    worker.start()