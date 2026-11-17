# src/mcp/tool_registry.py - FIXED VERSION
"""
Comprehensive MCP Tool Registry with All Integrated Tools
FIXED: Removed decorator pattern, using direct handler registration
"""

import json
import os
import threading
from typing import Dict, Any, List, Optional

# Import existing tools
from src.core.academic_calendar import AcademicCalendarManager, create_default_academic_calendar
from src.core.redact import redact
from src.mcp.youtube_cache import YouTubeSearchCache, is_quota_error
from src.mcp.tools.rag_retrieval_tool import RAGRetrievalTool
from src.mcp.tools.document_ingestion import DocumentIngestionSystem

# Import new search libraries
from ddgs import DDGS
import logging

from src.core.course_registry import default_registry
from src.core.kc_ids import parent_ids
from src.core.mastery_tracker import MasteryTracker
from src.core.validation import InvalidIdentifier, course_code as validate_course_code

logger = logging.getLogger(__name__)

class MCPToolRegistry:
    """Comprehensive tool registry with all LEA functionality - FIXED VERSION"""
    
    def __init__(self, redis_client=None):
        """Initialize tool registry with all available tools"""
        self.redis_client = redis_client
        self.tools = {}
        self._kc_models: Dict[str, Any] = {}

        # Mastery tracking backs the mastery_summary and mastery_update tools.
        try:
            self.mastery_tracker = MasteryTracker(storage_backend="redis", redis_client=redis_client)
        except Exception as e:
            logger.error(f"Mastery tracker could not be created: {e}")
            self.mastery_tracker = None
        
        # Base paths for data (LEA_DATA_DIR or the repository's data/ folder)
        self.base_data_dir = default_registry().data_dir
        self.kc_models_dir = self.base_data_dir / "kc_models"

        # Initialize YouTube API (enhanced debugging)
        logger.debug(f"Current working directory: {os.getcwd()}")
        logger.debug(f"Checking for YOUTUBE_API_KEY...")
        
        self.youtube_api_key = os.getenv("YOUTUBE_API_KEY")
        self._youtube_lock = threading.Lock()
        
        if self.youtube_api_key:
            # Strip whitespace just in case
            self.youtube_api_key = self.youtube_api_key.strip()
            logger.debug("YouTube API key found")
            
            try:
                import httplib2
                from googleapiclient.discovery import build
                # 10 s timeout; calls are serialised because the client isn't thread-safe
                self.youtube = build('youtube', 'v3', developerKey=self.youtube_api_key,
                                     http=httplib2.Http(timeout=10))
                logger.debug("✅ YouTube service initialized successfully")
            except Exception as e:
                logger.debug(f"❌ YouTube service initialization failed: {e}")
                self.youtube = None
        else:
            logger.info("YOUTUBE_API_KEY not set; YouTube worked-example search is disabled.")
            self.youtube = None
               
        # Initialize existing tools with enhanced error handling
        self._initialize_existing_tools()
        
        # Register all tools (existing + new)
        self._register_all_tools()
        
        logger.debug(f"Enhanced MCP Tool Registry initialized with {len(self.tools)} tools")
    
    def _initialize_existing_tools(self):
        """Initialize all existing tools with proper error handling"""
        # Academic calendar tool
        try:
            self.calendar_manager = AcademicCalendarManager(self.redis_client)
            self.academic_calendar = self.calendar_manager.get_calendar()
            logger.debug("Academic calendar initialized successfully")
        except Exception as e:
            logger.debug(f"Academic calendar manager failed: {e}, using default")
            self.academic_calendar = create_default_academic_calendar()
            self.calendar_manager = None
        
        # RAG tools
        try:
            self.rag_tool = RAGRetrievalTool()
            logger.debug("RAG tool initialized successfully")
        except Exception as e:
            logger.debug(f"RAG tool initialization failed: {e}")
            self.rag_tool = None
        
        try:
            self.ingestion_system = DocumentIngestionSystem()
            logger.debug("Document ingestion system initialized successfully")
        except Exception as e:
            logger.debug(f"Document ingestion system initialization failed: {e}")
            self.ingestion_system = None

    def _register_all_tools(self):
        """Register all available tools with their handlers and schemas"""
        self._register_academic_tools()
        self._register_rag_tools()
        self._register_search_tools()
        self._register_kc_model_tools()
        self._register_mastery_tools()  # FIXED VERSION

    def _register_mastery_tools(self):
        """FIXED: Register mastery-related MCP tools using direct handler pattern"""
        try:
            # Register mastery summary tool
            self.tools["mastery_summary"] = {
                "handler": self._handle_mastery_summary,
                "schema": {
                    "name": "mastery_summary",
                    "description": "Get mastery summary for a user and course",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "username": {
                                "type": "string",
                                "description": "Username to get mastery for",
                                "required": True
                            },
                            "course_code": {
                                "type": "string", 
                                "description": "Course code to get mastery for",
                                "required": True
                            }
                        }
                    }
                }
            }
            
            # Register mastery update tool
            self.tools["mastery_update"] = {
                "handler": self._handle_mastery_update,
                "schema": {
                    "name": "mastery_update",
                    "description": "Update mastery levels based on interaction",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "username": {
                                "type": "string",
                                "description": "Username to update mastery for",
                                "required": True
                            },
                            "course_code": {
                                "type": "string",
                                "description": "Course code to update mastery for", 
                                "required": True
                            },
                            "interaction_data": {
                                "type": "object",
                                "description": "Interaction data for mastery update",
                                "required": True
                            }
                        }
                    }
                }
            }
            
            logger.debug("Mastery tools registered successfully using direct handler pattern")
        except Exception as e:
            logger.error(f"Failed to register mastery tools: {e}")
            # Don't raise - this is not critical for basic functionality
    
    # FIXED: Add mastery tool handlers
    def _handle_mastery_summary(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle mastery summary requests"""
        try:
            username = parameters.get("username", "")
            course_code = parameters.get("course_code", "")

            if not username or not course_code:
                return {"success": False, "error": "username and course_code are required"}
            
            if self.mastery_tracker is None:
                return {"success": False, "error": "Mastery tracking is not configured"}

            mastery_data = self.mastery_tracker.get_mastery_summary(username, course_code)
            return {"success": True, "data": mastery_data}

        except Exception as e:
            return {"success": False, "error": f"Mastery summary error: {str(e)}"}
    
    def _handle_mastery_update(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle mastery update requests"""
        try:
            username = parameters.get("username", "")
            course_code = parameters.get("course_code", "")
            interaction_data = parameters.get("interaction_data", {})
            
            if not username or not course_code or not interaction_data:
                return {"success": False, "error": "username, course_code and interaction_data are required"}
            
            if self.mastery_tracker is None:
                return {"success": False, "error": "Mastery tracking is not configured"}

            go_id = interaction_data.get("go_id")
            if not go_id:
                return {"success": False, "error": "interaction_data.go_id is required"}

            lo_id, week = parent_ids(go_id, self.load_kc_model(course_code))
            lo_id = interaction_data.get("lo_id") or lo_id
            week = interaction_data.get("week_number") or week
            if lo_id is None or week is None:
                return {"success": False, "error": f"Cannot resolve learning objective for {go_id}"}

            context = {
                "username": username,
                "course_code": course_code,
                "mode": interaction_data.get("mode"),
                "is_quiz": interaction_data.get("mode") == "quiz",
                "correct": interaction_data.get("correct"),
                "score": interaction_data.get("score"),
                "question_type": interaction_data.get("question_type"),
                "go_data": {"go_id": go_id},
                "lo_data": {"lo_id": lo_id},
            }
            learner_mastery = self.mastery_tracker.update_learner_mastery(
                username, course_code, interaction_data.get("student_response", ""),
                go_id, lo_id, int(week), context,
            )
            return {
                "success": True,
                "go_id": go_id,
                "lo_id": lo_id,
                "week": int(week),
                "data": self.mastery_tracker._format_mastery_summary(learner_mastery),
            }

        except Exception as e:
            return {"success": False, "error": f"Mastery update error: {str(e)}"}

    def _available_course_codes(self) -> List[str]:
        """Course codes found as folders under data/kc_models (empty if none)."""
        try:
            return sorted(d.name for d in self.kc_models_dir.iterdir()
                          if d.is_dir() and not d.name.startswith("."))
        except OSError:
            return []

    def _register_academic_tools(self):
        """Register academic calendar and related tools"""
        course_codes = self._available_course_codes()
        self.tools["academic_calendar"] = {
            "handler": self._handle_academic_calendar,
            "schema": {
                "name": "academic_calendar",
                "description": "Get academic calendar information including current week, assignments, and deadlines",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "course": {
                            "type": "string",
                            "description": "Course code for course-specific calendar info",
                            **({"enum": course_codes} if course_codes else {}),
                        },
                        "username": {
                            "type": "string",
                            "description": "Username for personalized calendar info"
                        },
                        "info_type": {
                            "type": "string",
                            "description": "Type of calendar information to retrieve",
                            "enum": ["current", "upcoming", "assignments", "exams", "full"],
                            "default": "current"
                        }
                    }
                }
            }
        }
    
    def _register_rag_tools(self):
        """Register RAG retrieval and document ingestion tools"""
        if self.rag_tool:
            self.tools["rag_retrieval"] = {
                "handler": self._handle_rag_retrieval,
                "schema": self.rag_tool.get_schema()
            }
        
        if self.ingestion_system:
            self.tools["document_ingestion"] = {
                "handler": self._handle_document_ingestion,
                "schema": {
                    "name": "document_ingestion",
                    "description": "Process and ingest documents into RAG collections",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "action": {
                                "type": "string",
                                "description": "Action to perform",
                                "enum": ["process_all_modules", "process_module", "get_stats"],
                                "required": True
                            },
                            "module": {
                                "type": "string",
                                "description": "Specific module to process (when action is process_module)"
                            }
                        }
                    }
                }
            }
            
    def _register_search_tools(self):
        """Register web search and YouTube search tools"""
        # General web search
        self.tools["web_search"] = {
            "handler": self._handle_web_search,
            "schema": {
                "name": "web_search",
                "description": "Search the web for current information on any topic",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query for web results",
                            "required": True
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default: 5)",
                            "default": 5
                        },
                        "region": {
                            "type": "string",
                            "description": "Search region (us, uk, etc.)",
                            "default": "uk"
                        }
                    }
                }
            }
        }
        
        # YouTube search for worked examples
        self.tools["youtube_worked_examples"] = {
            "handler": self._handle_youtube_search,
            "schema": {
                "name": "youtube_worked_examples",
                "description": "Find YouTube videos with worked examples for specific topics, prioritizing high view counts",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "Topic to find worked examples for",
                            "required": True
                        },
                        "subject_area": {
                            "type": "string",
                            "description": "Subject area context (math, programming, physics, etc.)",
                            "default": "general"
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of video results (default: 3)",
                            "default": 3
                        }
                    }
                }
            }
        }
    
    def _register_kc_model_tools(self):
        """Register knowledge component model lookup tools"""
        self.tools["kc_model_lookup"] = {
            "handler": self._handle_kc_model_lookup,
            "schema": {
                "name": "kc_model_lookup",
                "description": "Look up knowledge component models for specific course modules",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "module": {
                            "type": "string",
                            "description": "Course module code (e.g., AIML101)",
                            "required": True
                        },
                        "component": {
                            "type": "string",
                            "description": "Specific knowledge component to look up (optional)"
                        }
                    }
                }
            }
        }
    
    # Tool Handlers - Existing Tools (same as before, keeping original handlers)
    def _handle_academic_calendar(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle academic calendar requests using the existing tool pattern"""
        try:
            course = parameters.get("course", "")
            username = parameters.get("username", "")
            info_type = parameters.get("info_type", "current")
            
            if self.calendar_manager:
                calendar_info = self.calendar_manager.get_academic_context(
                    course=course,
                    username=username
                )
            else:
                if info_type == "current":
                    calendar_info = self.academic_calendar.get_current_academic_info()
                else:
                    calendar_info = self.academic_calendar.get_course_specific_info(course, username)
            
            # Filter based on info_type (mirroring your academic_calendar_tool.py logic)
            if info_type == "current":
                filtered_context = {
                    "academic_week": calendar_info.get("academic_week"),
                    "week_type": calendar_info.get("week_type"),
                    "event": calendar_info.get("event"),
                    "current_events": calendar_info.get("current_events", []),
                    "course_week_context": calendar_info.get("course_week_context")
                }
            elif info_type == "upcoming":
                filtered_context = {
                    "upcoming_events": calendar_info.get("upcoming_events", []),
                    "course_upcoming_events": calendar_info.get("course_upcoming_events", []),
                    "course_assignments_due_soon": calendar_info.get("course_assignments_due_soon", [])
                }
            elif info_type == "assignments":
                filtered_context = {
                    "course_assignments_due_soon": calendar_info.get("course_assignments_due_soon", []),
                    "assignment_context": "Assignments and deadlines for current course"
                }
            else:  # full
                filtered_context = calendar_info
            
            return {
                "success": True,
                "tool": "academic_calendar",
                "calendar_info": filtered_context,
                "formatted_summary": self._format_calendar_summary(filtered_context, course)
            }
            
        except Exception as e:
            return {
                "success": False,
                "tool": "academic_calendar",
                "error": str(e)
            }
    
    def _format_calendar_summary(self, context: Dict, course: str = None) -> str:
        """Format calendar information into a readable summary"""
        parts = []
        
        if context.get("academic_week"):
            week_info = f"Academic Week {context['academic_week']}"
            if context.get("week_type"):
                week_info += f" ({context['week_type'].title()})"
            parts.append(week_info)
        
        current_events = context.get("current_events", [])
        if current_events:
            parts.append(f"Today: {', '.join([e['title'] for e in current_events[:2]])}")
        
        assignments = context.get("course_assignments_due_soon", [])
        if assignments:
            next_assignment = assignments[0]
            parts.append(f"Next assignment: {next_assignment['title']} (due {next_assignment['start_date'][:10]})")
        
        if context.get("course_week_context"):
            parts.append(context["course_week_context"])
        
        return " | ".join(parts) if parts else "No current academic events"
    
    def _handle_rag_retrieval(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle RAG retrieval requests"""
        if not self.rag_tool:
            return {"success": False, "error": "RAG tool not available"}
        return self.rag_tool.execute(parameters)
    
    def _handle_document_ingestion(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle document ingestion requests"""
        if not self.ingestion_system:
            return {"success": False, "error": "Document ingestion system not available"}
            
        action = parameters.get("action", "")
        module = parameters.get("module", "")
        
        try:
            if action == "process_all_modules":
                result = self.ingestion_system.process_all_modules()
                return {"success": True, "action": "process_all_modules", "result": result}
            elif action == "process_module" and module:
                result = self.ingestion_system.process_module(module)
                return {"success": True, "action": "process_module", "module": module, "result": result}
            elif action == "get_stats":
                stats = self.ingestion_system.get_ingestion_stats()
                return {"success": True, "action": "get_stats", "stats": stats}
            else:
                return {"success": False, "error": f"Invalid action or missing module: {action}"}
        except Exception as e:
            return {"success": False, "error": f"Ingestion error: {str(e)}"}

    def _handle_web_search(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle general web search requests using DuckDuckGo"""
        query = parameters.get("query", "")
        max_results = parameters.get("max_results", 5)
        region = parameters.get("region", "uk")
        
        if not query:
            return {"success": False, "error": "Query parameter is required"}
        
        try:
            # Use DuckDuckGo for web search (no API key required)
            with DDGS() as ddgs:
                results = []
                search_results = ddgs.text(query, region=region, max_results=max_results)
                
                for result in search_results:
                    results.append({
                        "title": result.get("title", ""),
                        "url": result.get("href", ""),
                        "snippet": result.get("body", ""),
                        "source": result.get("href", "").split('/')[2] if result.get("href") else ""
                    })
            
            return {
                "success": True,
                "tool": "web_search",
                "query": query,
                "num_results": len(results),
                "results": results,
                "summary": f"Found {len(results)} web results for '{query}'"
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": f"Web search failed: {str(e)}",
                "fallback_message": f"Unable to search for '{query}' at this time"
            }
    
    def _youtube_search(self, search_query: str, max_results: int) -> List[Dict[str, Any]]:
        """Most-viewed matching videos (the API client isn't thread-safe, so calls are serialised)."""
        with self._youtube_lock:
            # Use YouTube Data API v3 for better results
            search_response = self.youtube.search().list(
                q=search_query,
                part='id,snippet',
                maxResults=max_results * 2,  # Get more to sort by views
                type='video',
                order='viewCount',  # Sort by view count
                videoDuration='medium'  # Prefer substantial tutorials
            ).execute()
        
            items = search_response.get('items', [])
            ids = [item['id']['videoId'] for item in items]
            stats = {}
            if ids:
                # One statistics call for all results instead of one call per video
                details = self.youtube.videos().list(part='statistics', id=",".join(ids)).execute()
                stats = {d['id']: int(d['statistics'].get('viewCount', 0)) for d in details.get('items', [])}

            videos = []
            for search_result in items:
                video_id = search_result['id']['videoId']
                videos.append({
                    "title": search_result['snippet']['title'],
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "channel": search_result['snippet']['channelTitle'],
                    "description": search_result['snippet']['description'][:200] + "...",
                    "view_count": stats.get(video_id, 0),
                    "published": search_result['snippet']['publishedAt'][:10]
                })

            # Sort by view count and take top results
            videos.sort(key=lambda x: x['view_count'], reverse=True)
            videos = videos[:max_results]
        return videos

    @staticmethod
    def _youtube_unavailable(search_query: str, reason: str) -> Dict[str, Any]:
        """A search that wasn't sent (quota paused, or it just failed): the tutor uses its fallback."""
        return {
            "success": False, "error": reason, "paused": True,
            "fallback_url": f"https://www.youtube.com/results?search_query={search_query.replace(' ', '+')}",
        }

    def _handle_youtube_search(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle YouTube search for worked examples, prioritizing view count"""
        topic = parameters.get("topic", "")
        subject_area = parameters.get("subject_area", "general")
        max_results = parameters.get("max_results", 3)
        
        if not topic:
            return {"success": False, "error": "Topic parameter is required"}
        
        # Construct search query for worked examples
        search_query = f"{topic} worked example tutorial {subject_area}"
        
        cache = YouTubeSearchCache(getattr(self, "redis_client", None))
        source = "api"
        try:
            if self.youtube:
                videos = cache.get(search_query)
                if videos is not None:
                    source = "cache"  # asked before this week: no quota used
                elif cache.quota_paused_until():
                    return self._youtube_unavailable(search_query, "YouTube's daily quota is used up; search resumes "
                                                                   "when it resets")
                elif cache.failed_recently(search_query):
                    return self._youtube_unavailable(search_query, "This search failed a moment ago; not retrying yet")
                else:
                    videos = self._youtube_search(search_query, max_results)
                    cache.put(search_query, videos)

            else:
                source = "search-link"
                # Fallback to basic search without API
                videos = [{
                    "title": f"Worked Example: {topic}",
                    "url": f"https://www.youtube.com/results?search_query={search_query.replace(' ', '+')}",
                    "channel": "Search Results",
                    "description": f"YouTube search results for {topic} worked examples",
                    "view_count": "N/A",
                    "note": "YouTube API not available - showing search URL"
                }]
            
            return {
                "success": True,
                "tool": "youtube_worked_examples",
                "topic": topic,
                "search_query": search_query,
                "num_results": len(videos),
                "videos": videos,
                "source": source,  # api, cache, or search-link (no API key)
                "summary": f"Found {len(videos)} YouTube worked examples for '{topic}'"
            }

        except Exception as e:
            if is_quota_error(e):
                cache.pause_for_quota()  # no more searches until Google's quota resets
            else:
                cache.note_failure(search_query)
            return {
                "success": False,
                # A Google API error's text is the request URL, API key included: never return it as is.
                "error": f"YouTube search failed: {redact(str(e))}",
                "fallback_url": f"https://www.youtube.com/results?search_query={search_query.replace(' ', '+')}"
            }
    
    def load_kc_model(self, module: str) -> Optional[Dict[str, Any]]:
        """Read and cache data/kc_models/<MODULE>/kc_model_<MODULE>.json (None if missing)."""
        try:
            module = validate_course_code(module)
        except InvalidIdentifier:
            return None
        if module not in self._kc_models:
            kc_file = self.kc_models_dir / module / f"kc_model_{module}.json"
            if not kc_file.exists():
                return None
            with open(kc_file, "r", encoding="utf-8") as f:
                self._kc_models[module] = json.load(f)
        return self._kc_models[module]

    def _handle_kc_model_lookup(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Handle knowledge component model lookup from data/kc_models/ directory"""
        component = parameters.get("component", "")
        try:
            module = validate_course_code(parameters.get("module", ""))
        except InvalidIdentifier as e:
            return {"success": False, "error": str(e)}
        
        try:
            # Construct file path: data/kc_models/{module}/kc_model_{module}.json
            module_dir = self.kc_models_dir / module
            kc_file = module_dir / f"kc_model_{module}.json"
            
            if not kc_file.exists():
                # List available modules for helpful error message
                available_modules = []
                if self.kc_models_dir.exists():
                    available_modules = [d.name for d in self.kc_models_dir.iterdir() if d.is_dir()]
                
                return {
                    "success": False,
                    "error": f"KC model file not found for module '{module}'",
                    "expected_path": str(kc_file),
                    "available_modules": available_modules
                }
            
            # Load the KC model JSON file
            with open(kc_file, 'r', encoding='utf-8') as f:
                kc_model = json.load(f)
            
            result = {
                "success": True,
                "tool": "kc_model_lookup",
                "module": module,
                "kc_model_path": str(kc_file),
                "kc_model": kc_model
            }
            
            # If a specific component was requested, filter the results
            if component:
                component_data = None
                
                # Search for the component in the model structure
                # This assumes your KC model has a structure where components can be found
                if isinstance(kc_model, dict):
                    # Try different common keys for components
                    for key in ['components', 'knowledge_components', 'kcs', 'skills']:
                        if key in kc_model:
                            components = kc_model[key]
                            if isinstance(components, dict) and component in components:
                                component_data = components[component]
                                break
                            elif isinstance(components, list):
                                # Search in list of components
                                for comp in components:
                                    if (isinstance(comp, dict) and 
                                        (comp.get('name') == component or comp.get('id') == component)):
                                        component_data = comp
                                        break
                
                if component_data:
                    result["requested_component"] = component
                    result["component_data"] = component_data
                else:
                    result["component_not_found"] = component
                    result["available_components"] = self._extract_component_names(kc_model)
            
            # Add summary information
            result["summary"] = self._summarize_kc_model(kc_model, module)
            
            return result
            
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"Invalid JSON in KC model file: {str(e)}",
                "file_path": str(kc_file)
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"KC model lookup failed: {str(e)}",
                "module": module
            }
    
    def _extract_component_names(self, kc_model: Dict) -> List[str]:
        """Extract component names from KC model for helpful error messages"""
        names = []
        if isinstance(kc_model, dict):
            for key in ['components', 'knowledge_components', 'kcs', 'skills']:
                if key in kc_model:
                    components = kc_model[key]
                    if isinstance(components, dict):
                        names.extend(components.keys())
                    elif isinstance(components, list):
                        for comp in components:
                            if isinstance(comp, dict):
                                if 'name' in comp:
                                    names.append(comp['name'])
                                elif 'id' in comp:
                                    names.append(comp['id'])
        return names
    
    def _summarize_kc_model(self, kc_model: Dict, module: str) -> str:
        """Create a helpful summary of the KC model"""
        summary_parts = [f"KC Model for {module}"]
        
        if isinstance(kc_model, dict):
            # Count components
            component_count = 0
            for key in ['components', 'knowledge_components', 'kcs', 'skills']:
                if key in kc_model:
                    components = kc_model[key]
                    if isinstance(components, dict):
                        component_count = len(components)
                    elif isinstance(components, list):
                        component_count = len(components)
                    break
            
            if component_count > 0:
                summary_parts.append(f"{component_count} knowledge components")
            
            # Add other relevant info
            if 'description' in kc_model:
                summary_parts.append(f"Description: {kc_model['description'][:100]}...")
            
            if 'version' in kc_model:
                summary_parts.append(f"Version: {kc_model['version']}")
        
        return " | ".join(summary_parts)
    
    # Registry Management Methods (same as before)
    def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a specific tool with parameters"""
        if tool_name not in self.tools:
            return {
                "success": False,
                "error": f"Tool '{tool_name}' not found",
                "available_tools": list(self.tools.keys())
            }
        
        try:
            handler = self.tools[tool_name]["handler"]
            result = handler(parameters)
            
            # Ensure tool name is in result for tracking
            if isinstance(result, dict) and "tool" not in result:
                result["tool"] = tool_name
            
            return result
            
        except Exception as e:
            logger.debug(f"Tool execution error for {tool_name}: {e}")
            return {
                "success": False,
                "error": f"Tool execution failed: {str(e)}",
                "tool": tool_name
            }
    
    def get_available_tools(self) -> List[str]:
        """Get list of all available tools"""
        return list(self.tools.keys())
    
    def get_tool_schemas(self) -> Dict[str, Any]:
        """Get schemas for all tools"""
        schemas = {}
        for tool_name, tool_info in self.tools.items():
            schemas[tool_name] = tool_info["schema"]
        return schemas
    
    def get_rag_courses(self) -> List[str]:
        """Get available RAG course collections"""
        try:
            if self.rag_tool:
                return self.rag_tool.get_available_courses()
            else:
                return []
        except Exception as e:
            logger.debug(f"Error getting RAG courses: {e}")
            return []
    
    def get_tool_info(self, tool_name: str) -> Dict[str, Any]:
        """Get detailed information about a specific tool"""
        if tool_name not in self.tools:
            return {
                "error": f"Tool '{tool_name}' not found",
                "available_tools": list(self.tools.keys())
            }
        
        tool_info = self.tools[tool_name]
        info = {
            "name": tool_name,
            "description": tool_info["schema"]["description"],
            "schema": tool_info["schema"],
            "available": True
        }
        
        # Add tool-specific information
        if tool_name == "rag_retrieval" and self.rag_tool:
            info["available_courses"] = self.rag_tool.get_available_courses()
        elif tool_name == "kc_model_lookup":
            available_modules = []
            if self.kc_models_dir.exists():
                available_modules = [d.name for d in self.kc_models_dir.iterdir() if d.is_dir()]
            info["available_modules"] = available_modules
        
        return info