"""Client the orchestrator uses to reach LEA's tools (RAG, KC models, mastery)."""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class LEAMCPClient:
    """Thin wrapper that builds tool requests and normalises responses."""

    def __init__(self, mcp_server):
        self.mcp_server = mcp_server

    def _call(self, tool: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        try:
            return self.mcp_server.handle_tool_request({"tool": tool, "parameters": parameters})
        except Exception as e:
            logger.error("Tool request %s failed: %s", tool, e)
            return {"success": False, "error": f"{tool} error: {e}"}

    def get_course_content_via_rag(self, query: str, course: str, max_results: int = 3) -> Dict[str, Any]:
        result = self._call("rag_retrieval", {"query": query, "course": course,
                                              "max_results": max_results, "use_reranking": True})
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "RAG request failed")}
        results = result.get("results", [])
        sources = [{"source": r.get("metadata", {}).get("source") or r.get("metadata", {}).get("source_file", ""),
                    "excerpt": str(r.get("content", ""))[:300]} for r in results]
        return {"success": True, "content": self._format_rag_content(results),
                "num_results": result.get("num_results", 0), "course": course, "sources": sources}

    @staticmethod
    def _format_rag_content(results: List[Dict]) -> str:
        if not results:
            return "No relevant course content found."
        pieces = []
        for i, result in enumerate(results, 1):
            piece = f"Content {i}:\n{result.get('content', '')[:800]}..."
            source = result.get("metadata", {}).get("source")
            if source:
                piece += f"\n(Source: {source})"
            pieces.append(piece)
        return "\n\n".join(pieces)

    def get_kc_model_data(self, course: str, component_id: Optional[str] = None) -> Dict[str, Any]:
        result = self._call("kc_model_lookup", {"module": course, "component": component_id})
        if not result.get("success"):
            return {"success": False, "error": result.get("error", "KC model request failed")}
        return {"success": True, "kc_model": result.get("kc_model", {}),
                "component_data": result.get("component_data"), "summary": result.get("summary", "")}

    def update_mastery(self, username: str, course_code: str, interaction_data: Dict[str, Any]) -> Dict[str, Any]:
        result = self._call("mastery_update", {"username": username, "course_code": course_code,
                                               "interaction_data": interaction_data})
        return result if result.get("success") else {"success": False,
                                                     "error": result.get("error", "Mastery update failed")}

    def get_mastery_summary(self, username: str, course_code: str) -> Dict[str, Any]:
        result = self._call("mastery_summary", {"username": username, "course_code": course_code})
        return result if result.get("success") else {"success": False,
                                                     "error": result.get("error", "Failed to get mastery")}

    def get_available_tools(self) -> Dict[str, Any]:
        return self.mcp_server.get_available_tools()
