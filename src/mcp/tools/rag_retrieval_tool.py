# src/mcp/tools/rag_retrieval_tool.py
"""
RAG Retrieval Tool for LEA MCP Server
Handles multi-course RAG operations with ChromaDB using per-course directories
"""

import os
import threading
import chromadb
import nltk
from typing import Dict, Any, List
from sentence_transformers import CrossEncoder
from chromadb.utils import embedding_functions
import torch

# Streamlit's file watcher walks every imported module's __path__; torch.classes raises
# on that lookup and floods the console. An empty path makes the watcher skip it.
torch.classes.__path__ = []
import logging
from pathlib import Path

from src.core.course_registry import default_registry
from src.core.validation import InvalidIdentifier, course_code as validate_course_code

logger = logging.getLogger(__name__)

# Load environment variables if not already loaded
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv might not be available in all environments

# Download required NLTK data
for _resource in ("punkt", "punkt_tab"):  # NLTK 3.9+ needs punkt_tab
    try:
        nltk.data.find(f"tokenizers/{_resource}")
    except LookupError:
        nltk.download(_resource, quiet=True)

class RAGRetrievalTool:
    """
    RAG tool that manages multiple course collections using separate ChromaDB instances
    Each course now has its own dedicated ChromaDB directory for better isolation
    """
    
    def __init__(self):
        """Initialize RAG tool with per-course ChromaDB clients"""
        self.tool_name = "rag_retrieval"
        self.description = "Retrieve relevant course content using RAG"
        
        # Base directory for all course vector stores (data/chroma_data/<CODE>/)
        self.base_chroma_dir = str(default_registry().chroma_dir)
        
        # Ensure base directory exists
        if not os.path.exists(self.base_chroma_dir):
            logger.debug(f"Base ChromaDB directory not found: {self.base_chroma_dir}")
            # Try alternative base paths if the default doesn't exist
            alt_base_paths = ["./data/chroma_data", "../data/chroma_data", "chroma_data"]
            for alt_path in alt_base_paths:
                if os.path.exists(alt_path):
                    self.base_chroma_dir = alt_path
                    logger.debug(f"Using alternative base ChromaDB path: {alt_path}")
                    break
            else:
                logger.debug(f"Creating base ChromaDB directory: {self.base_chroma_dir}")
                os.makedirs(self.base_chroma_dir, exist_ok=True)
        
        logger.debug(f"Base ChromaDB directory set to: {self.base_chroma_dir}")
        
        # OpenAI embedding function with robust API key loading
        try:
            # Try multiple environment variable names and load .env if needed
            api_key = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY") or os.getenv("openai_api_key")
            
            if not api_key:
                raise ValueError("OpenAI API key not found in environment variables")
            
            logger.debug("OpenAI API key found")
            
            self.embedding_function = embedding_functions.OpenAIEmbeddingFunction(
                api_key=api_key,
                model_name="text-embedding-3-small"
            )
            logger.debug("OpenAI embedding function initialized")
        except Exception as e:
            logger.debug(f"Failed to initialize OpenAI embeddings: {e}")
            raise e
        
        # Cross-encoder for reranking. Its fast tokenizer isn't safe for concurrent use,
        # so predictions are serialised (each takes milliseconds on a few candidates).
        self._rerank_lock = threading.Lock()
        try:
            self.cross_encoder_model_name = "cross-encoder/ms-marco-MiniLM-L-6-v2"
            self.cross_encoder_device = "cuda" if torch.cuda.is_available() else "cpu"
            self.cross_encoder = CrossEncoder(
                self.cross_encoder_model_name, 
                device=self.cross_encoder_device
            )
            logger.debug(f"Cross-encoder initialized on {self.cross_encoder_device}")
        except Exception as e:
            logger.debug(f"Failed to initialize cross-encoder: {e}")
            self.cross_encoder = None
        
        # Course collection mapping - now stores both client and collection
        self.course_collections = {}
        self._initialize_course_collections()
        
        logger.debug(f"RAG Tool initialized with {len(self.course_collections)} course collections")

    def _initialize_course_collections(self):
        """Open every course vector store under the base directory.

        Courses are discovered from disk (``data/chroma_data/<CODE>/chroma.sqlite3``), so a
        newly onboarded course is served without code changes. The collection named after
        the course code is used; a store with a single differently-named collection is
        accepted with a warning.
        """
        registry = default_registry()
        base = Path(self.base_chroma_dir)
        if not base.exists():
            logger.warning(f"No vector stores found: {base} does not exist")
            return

        for course_dir in sorted(p for p in base.iterdir() if p.is_dir()):
            try:
                course_code = validate_course_code(course_dir.name)
            except InvalidIdentifier:
                continue
            if not (course_dir / "chroma.sqlite3").exists():
                continue
            try:
                client = chromadb.PersistentClient(path=str(course_dir))
                names = [c if isinstance(c, str) else c.name for c in client.list_collections()]
                if course_code in names:
                    collection_name = course_code
                elif len(names) == 1:
                    collection_name = names[0]
                    logger.warning(f"{course_code}: using collection '{collection_name}' (expected '{course_code}')")
                else:
                    logger.error(f"{course_code}: expected a collection named '{course_code}', found {names}")
                    continue

                collection = client.get_collection(name=collection_name, embedding_function=self.embedding_function)
                doc_count = collection.count()
                if doc_count == 0:
                    logger.warning(f"{course_code}: vector store is empty; skipping")
                    continue
                self.course_collections[course_code] = {
                    "client": client,
                    "collection": collection,
                    "collection_name": collection_name,
                    "description": registry.profile(course_code).display_name,
                    "document_count": doc_count,
                    "db_path": str(course_dir),
                }
                logger.info(f"RAG: {course_code} ready with {doc_count} chunks")
            except Exception as e:
                logger.error(f"RAG: could not open vector store for {course_code}: {e}")

    def execute(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Execute RAG retrieval with enhanced error handling"""
        try:
            query = parameters.get("query", "").strip()
            course = parameters.get("course", "").strip()
            max_results = parameters.get("max_results", 5)
            use_reranking = parameters.get("use_reranking", True)
            
            logger.debug(f"RAG execute called with query='{query}', course='{course}'")
            logger.debug(f"Available courses: {list(self.course_collections.keys())}")
            
            # Validate inputs
            if not query:
                logger.debug("RAG failed - empty query")
                return {
                    "success": False,
                    "error": "Query parameter is required and cannot be empty"
                }
            
            if not course:
                logger.debug("RAG failed - empty course")
                return {
                    "success": False,
                    "error": "Course parameter is required",
                    "available_courses": list(self.course_collections.keys())
                }
            
            if course not in self.course_collections:
                logger.debug(f"RAG failed - course '{course}' not available")
                return {
                    "success": False,
                    "error": f"Course '{course}' not available. Available courses: {list(self.course_collections.keys())}",
                    "available_courses": list(self.course_collections.keys())
                }
            
            logger.debug(f"RAG retrieval for course '{course}' with query: '{query}'")
            
            # Get the appropriate collection for this course
            course_info = self.course_collections[course]
            collection = course_info["collection"]
            logger.debug(f"Using collection with {course_info['document_count']} documents")
            
            # Perform retrieval using the course-specific collection
            if use_reranking and self.cross_encoder:
                logger.debug("Using two-stage retrieval")
                results = self._two_stage_retrieve(collection, query, max_results)
            else:
                logger.debug("Using simple retrieval")
                results = self._simple_retrieve(collection, query, max_results)
            
            logger.debug(f"RAG retrieval completed with {len(results)} results")
            
            result = {
                "success": True,
                "tool": self.tool_name,
                "course": course,
                "query": query,
                "num_results": len(results),
                "results": results,
                "collection_info": {
                    "total_documents": course_info.get("document_count", 0),
                    "description": course_info.get("description", ""),
                    "collection_name": course_info.get("collection_name", ""),
                }
            }
            
            logger.debug(f"RAG returning result: success={result['success']}, num_results={result['num_results']}")
            return result
            
        except Exception as e:
            logger.error(f"RAG retrieval failed for course {parameters.get('course')!r}: {e}")
            return {
                "success": False,
                "error": f"RAG retrieval failed: {str(e)}",
                "available_courses": list(self.course_collections.keys()) if hasattr(self, 'course_collections') else []
            }
    
    
    def _two_stage_retrieve(self, collection, query: str, max_results: int) -> List[Dict]:
        """Two-stage retrieval: vector similarity + cross-encoder reranking"""
        try:
            # Stage 1: Vector similarity (get more results for reranking)
            # Get 4x more for reranking, but never more than the store holds (Chroma warns otherwise)
            initial_k = max(1, min(max_results * 4, 20, collection.count()))
            
            logger.debug(f"Performing vector search with k={initial_k}")
            
            initial_results = collection.query(
                query_texts=[query],
                n_results=initial_k
            )
            
            # DEBUG BLOCK (Uncomment to see display)
            # print(f"DEBUG: Raw ChromaDB results structure:")
            # print(f"DEBUG: - Keys: {list(initial_results.keys())}")
            # print(f"DEBUG: - Documents type: {type(initial_results.get('documents'))}")
            # print(f"DEBUG: - Documents length: {len(initial_results.get('documents', []))}")
            # if initial_results.get('documents') and initial_results['documents'][0]:
            #     print(f"DEBUG: - First doc preview: {str(initial_results['documents'][0][0])[:200]}...")
            #     print(f"DEBUG: - First doc type: {type(initial_results['documents'][0][0])}")
            # print(f"DEBUG: - IDs: {initial_results.get('ids', [])[:2]}")  # Show first 2 IDs
            # print(f"DEBUG: - Metadatas: {initial_results.get('metadatas', [])[:1]}")  # Show first metadata
            
            if not initial_results["documents"] or not initial_results["documents"][0]:
                logger.debug("No documents returned from vector search")
                return []
            
            # Prepare candidates for reranking
            candidates = []
            for i in range(len(initial_results["ids"][0])):
                doc_text = initial_results["documents"][0][i]
                doc_metadata = initial_results["metadatas"][0][i] or {}
                
                # DEBUG: Show what we're extracting
                # print(f"DEBUG: Doc {i} - Text type: {type(doc_text)}, Text preview: {str(doc_text)[:100]}...")
                
                candidates.append({
                    "id": initial_results["ids"][0][i],
                    "text": doc_text,  # This should be the actual content
                    "metadata": doc_metadata,
                    "vector_distance": initial_results["distances"][0][i]
                })
            
            logger.debug(f"Retrieved {len(candidates)} candidates for reranking")
            
            # Stage 2: Cross-encoder reranking
            if len(candidates) > 1 and self.cross_encoder:
                try:
                    cross_input = [(query, doc["text"]) for doc in candidates]
                    with self._rerank_lock:
                        scores = self.cross_encoder.predict(cross_input)
                    
                    # Attach reranking scores
                    for doc, score in zip(candidates, scores):
                        doc["rerank_score"] = float(score)
                    
                    # Sort by reranking score
                    candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
                    logger.debug(f"Reranked candidates by cross-encoder scores")
                except Exception as e:
                    logger.debug(f"Cross-encoder reranking failed: {e}")
                    # Fallback to vector similarity ranking
                    for doc in candidates:
                        doc["rerank_score"] = 1.0 - doc["vector_distance"]  # Convert distance to score
                    candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
            else:
                # Single result or no cross-encoder, use vector similarity
                for doc in candidates:
                    doc["rerank_score"] = 1.0 - doc["vector_distance"]  # Convert distance to score
            
            # Return top results
            final_results = []
            for doc in candidates[:max_results]:
                final_result = {
                    "chunk_id": doc["id"],
                    "content": doc["text"],  # This is where the problem might be
                    "metadata": doc["metadata"],
                    "vector_distance": doc["vector_distance"],
                    "rerank_score": doc["rerank_score"],
                    "relevance": "high" if doc["rerank_score"] > 0.5 else "medium"
                }
                
                # # DEBUG: Show final result content
                # print(f"DEBUG: Final result content type: {type(final_result['content'])}")
                # print(f"DEBUG: Final result content preview: {str(final_result['content'])[:100]}...")
                
                final_results.append(final_result)
            
            logger.debug(f"Returning {len(final_results)} final results")
            return final_results
            
        except Exception as e:
            # Reranking problems fall back to plain vector search; search errors propagate.
            logger.warning(f"Two-stage retrieval failed ({e}); trying plain vector search")
            return self._simple_retrieve(collection, query, max_results)

    

    def _simple_retrieve(self, collection, query: str, max_results: int) -> List[Dict]:
        """Simple vector similarity retrieval"""
        try:
            logger.debug(f"Performing simple vector search with max_results={max_results}")
            
            results = collection.query(
                query_texts=[query],
                n_results=max(1, min(max_results, collection.count()))
            )
            
            if not results["documents"] or not results["documents"][0]:
                logger.debug("No documents returned from simple search")
                return []
            
            final_results = []
            for i in range(len(results["ids"][0])):
                final_results.append({
                    "chunk_id": results["ids"][0][i],
                    "content": results["documents"][0][i],
                    "metadata": results["metadatas"][0][i] or {},
                    "vector_distance": results["distances"][0][i],
                    "relevance": "medium"
                })
            
            logger.debug(f"Simple retrieval returned {len(final_results)} results")
            return final_results
            
        except Exception as e:
            # Report the failure (e.g. embedding API errors) instead of "success with no results".
            logger.error(f"Vector search failed: {e}")
            raise
    
    def get_schema(self) -> Dict[str, Any]:
        """Return the tool schema for MCP registration"""
        return {
            "name": self.tool_name,
            "description": self.description,
            "parameters": {
                "query": {
                    "type": "string",
                    "description": "Search query for retrieving relevant content",
                    "required": True
                },
                "course": {
                    "type": "string", 
                    "description": f"Course code. Available: {list(self.course_collections.keys())}",
                    "required": True
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 5)",
                    "default": 5
                },
                "use_reranking": {
                    "type": "boolean",
                    "description": "Whether to use cross-encoder reranking (default: True)",
                    "default": True
                }
            }
        }
    
    def get_available_courses(self) -> List[str]:
        """Get list of available course collections"""
        return list(self.course_collections.keys())
    
    def get_collection_stats(self, course: str) -> Dict[str, Any]:
        """Get statistics about a course collection"""
        if course not in self.course_collections:
            return {"error": f"Course '{course}' not found"}
        
        try:
            course_info = self.course_collections[course]
            collection = course_info["collection"]
            count = collection.count()
            
            return {
                "course": course,
                "document_count": count,
                "description": course_info["description"],
                "collection_name": course_info["collection_name"],
                "db_path": course_info["db_path"]
            }
        except Exception as e:
            return {"error": f"Failed to get stats: {str(e)}"}
            

