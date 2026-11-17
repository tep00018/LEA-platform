"""Every backend module imports cleanly with the locked dependencies."""

import importlib

import pytest

MODULES = [
    "src.auth.auth_service",
    "src.core.academic_calendar",
    "src.core.agent_orchestrator_mcp",
    "src.core.kc_model_loader",
    "src.core.mastery_tracker",
    "src.core.progress_integration",
    "src.core.scaffolding_engine",
    "src.mcp.mcp_client",
    "src.mcp.mcp_server",
    "src.mcp.tool_registry",
    "src.mcp.tools.document_ingestion",
    "src.mcp.tools.rag_retrieval_tool",
    "src.quiz.simple_quiz_system",
    "src.storage.consolidation_worker",
    "src.storage.enhanced_redis_schemas",
    "src.storage.memory_schemas",
    "src.storage.redis_client",
    "src.tutor",
    "src.tutor.simple_tutor_system",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module):
    importlib.import_module(module)
