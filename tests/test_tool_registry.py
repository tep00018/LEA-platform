"""The in-process tool registry: which tools exist, so one silently failing to register is noticed."""

EXPECTED = {
    "academic_calendar", "rag_retrieval", "document_ingestion", "web_search",
    "youtube_worked_examples", "kc_model_lookup", "mastery_summary", "mastery_update",
}


def registry(services):
    return services.orchestrator.mcp_client.mcp_server.tool_registry


def test_the_registry_holds_exactly_the_expected_tools(services):
    assert set(registry(services).tools) == EXPECTED


def test_there_are_no_weather_tools_or_capability_flag(services):
    tools = registry(services).tools
    assert not [name for name in tools if "weather" in name]
    assert "weather_services" not in services.orchestrator.mcp_client.mcp_server.get_available_tools()["capabilities"]
