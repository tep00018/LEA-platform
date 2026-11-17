"""In-process tool server for LEA.

Routes named tool requests to the tool registry and reports timing. (This is LEA's own
tool registry, not the Model Context Protocol.) Calls are synchronous: each request runs
on the caller's thread.
"""
import logging
import time
from typing import Any, Dict

from src.mcp.tool_registry import MCPToolRegistry

logger = logging.getLogger(__name__)


class LEAMCPServer:
    """Dispatches tool requests to the registry."""

    def __init__(self, redis_client=None):
        self.tool_registry = MCPToolRegistry(redis_client)
        logger.debug("LEA tool server initialized with %d tools",
                     len(self.tool_registry.get_available_tools()))

    def handle_tool_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Run one tool.

        Request format: ``{"tool": name, "parameters": {...}, "request_id": optional}``.
        Always returns a dict with ``success``; failures carry ``error``.
        """
        tool_name = request.get("tool")
        request_id = request.get("request_id")
        if not tool_name:
            return {"success": False, "error": "Tool name is required",
                    "available_tools": self.tool_registry.get_available_tools(),
                    "request_id": request_id}
        started = time.perf_counter()
        try:
            result = self.tool_registry.execute_tool(tool_name, request.get("parameters", {}))
        except Exception as e:
            logger.exception("Tool %s failed", tool_name)
            return {"success": False, "error": f"Tool error: {e}", "request_id": request_id}
        if isinstance(result, dict):
            result["execution_time"] = round(time.perf_counter() - started, 3)
            result["request_id"] = request_id
        return result

    def get_available_tools(self) -> Dict[str, Any]:
        registry = self.tool_registry
        return {
            "tools": registry.get_available_tools(),
            "schemas": registry.get_tool_schemas(),
            "total_tools": len(registry.tools),
            "rag_courses": registry.get_rag_courses(),
            "capabilities": {
                "web_search": "web_search" in registry.tools,
                "youtube_search": "youtube_worked_examples" in registry.tools,
                "rag_retrieval": "rag_retrieval" in registry.tools,
                "academic_calendar": "academic_calendar" in registry.tools,
                "kc_models": "kc_model_lookup" in registry.tools,
            },
        }
