"""Startup wiring and real dispatch, with external side effects replaced."""

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.config.settings import Settings
from app.llm.base import ToolCall
from app.llm.openai import OpenAIProvider
from app.memory.database import Database
from app.memory.repository import MemoryRepository
from app.security.permissions import PermissionEngine


@pytest.fixture
def wired(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from app.agent.orchestrator import AgentOrchestrator
    from app.logging.logger import logger
    from app.main import build_tool_registry

    monkeypatch.setattr(logger, "_write", Mock())
    settings = Settings(
        _env_file=None,
        openai_api_key="unit-test-placeholder",
        github_token="unit-test-placeholder",
        openai_model="gpt-5.2",
        web_search_enabled=False,
        web_search_max_requests_per_turn=1,
    )
    database = Database(tmp_path / "memory.db")
    database.initialize()
    memory = MemoryRepository(database)
    registry = build_tool_registry(settings, memory)
    client = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock()))
    monkeypatch.setattr("app.llm.openai.AsyncOpenAI", Mock(return_value=client))
    provider = OpenAIProvider(settings)
    agent = AgentOrchestrator(provider, registry, PermissionEngine(), memory)
    return agent, client, logger, tmp_path


def test_startup_registers_all_existing_tools(wired):
    agent, _, _, _ = wired
    expected = {
        "open_application",
        "get_system_info",
        "list_directory",
        "read_file",
        "terminal",
        "list_repositories",
        "inspect_repository",
        "remember_preference",
        "get_preference",
        "remember_project",
        "get_project",
        "open_url",
    }
    assert {tool.name for tool in agent.tools.all()} == expected
    schemas = agent.tools.openai_schemas()
    assert len(schemas) == 12
    assert {schema["name"] for schema in schemas} == expected
    for schema in schemas:
        assert schema["type"] == "function" and schema["strict"] is True
        assert schema["parameters"]["additionalProperties"] is False
        assert set(schema["parameters"]["required"]) == set(
            schema["parameters"]["properties"]
        )
    with pytest.raises(ValueError, match="already registered"):
        agent.tools.register(agent.tools.get("open_url"))


@pytest.mark.parametrize("search_enabled", [False, True])
async def test_existing_tools_dispatch_and_continue_with_real_memory(
    wired, monkeypatch, search_enabled
):
    agent, client, logger, tmp_path = wired
    agent.llm.web_search_enabled = search_enabled
    commands = []

    def run(command, **kwargs):
        commands.append(command)
        output = "14.0" if command[0] == "sw_vers" else "mock command result"
        return subprocess.CompletedProcess(command, 0, stdout=output, stderr="")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr("app.tools.filesystem.ALLOWED_ROOTS", [tmp_path])
    monkeypatch.setattr(
        "builtins.input", Mock(side_effect=AssertionError("Unexpected prompt"))
    )
    (tmp_path / "sample.txt").write_text("temporary file content")
    github = agent.tools.get("list_repositories").client
    assert github is agent.tools.get("inspect_repository").client
    github.get = AsyncMock(
        side_effect=[
            [{"full_name": "example/project", "description": "A project"}],
            {"full_name": "example/project", "description": "A project"},
        ]
    )
    cases = [
        ("open_application", {"application_name": "Calculator"}, "Successfully opened"),
        ("get_system_info", {}, "macOS: 14.0"),
        ("list_directory", {"path": str(tmp_path)}, "sample.txt"),
        ("read_file", {"path": str(tmp_path / "sample.txt")}, "temporary file content"),
        (
            "terminal",
            {"command": "pwd", "working_directory": None},
            "mock command result",
        ),
        ("list_repositories", {}, "example/project"),
        (
            "inspect_repository",
            {"owner": "example", "repository": "project"},
            "example/project",
        ),
        (
            "remember_preference",
            {"key": "preferred_editor", "value": "Vim"},
            "preferred_editor",
        ),
        ("get_preference", {"key": "preferred_editor"}, "Vim"),
        (
            "remember_project",
            {"project_name": "example", "description": "Test project"},
            "example",
        ),
        ("get_project", {"project_name": "example"}, "Test project"),
    ]
    for name, arguments, expected_output in cases:
        function = SimpleNamespace(
            type="function_call",
            call_id="call_test",
            name=name,
            arguments=json.dumps(arguments),
        )
        initial = SimpleNamespace(
            id="resp_initial", output=[function], output_text="", usage=None
        )
        final = SimpleNamespace(
            id="resp_final", output=[], output_text="Done", usage=None
        )
        client.responses.create.side_effect = [initial, final]
        client.responses.create.reset_mock()
        assert await agent.run("Run the requested tool") == "Done"
        first_request, next_request = client.responses.create.call_args_list
        assert len(first_request.kwargs["tools"]) == 12 + int(search_enabled)
        assert len(next_request.kwargs["tools"]) == 12
        assert next_request.kwargs["previous_response_id"] == "resp_initial"
        assert (
            next_request.kwargs["instructions"] == first_request.kwargs["instructions"]
        )
        result = next_request.kwargs["input"][0]
        assert result["call_id"] == "call_test"
        assert result["type"] == "function_call_output"
        assert expected_output in result["output"]
        assert not result["output"].startswith("Tool execution failed")
    assert commands == [
        ["open", "-a", "Calculator"],
        ["sw_vers", "-productVersion"],
        ["pwd"],
    ]
    assert github.get.await_count == 2
    assert agent.memory.get_preference("preferred_editor") == "Vim"
    assert agent.memory.get_project("example")["description"] == "Test project"
    with agent.memory.database.connect() as connection:
        assert (
            connection.execute("SELECT count(*) FROM conversations").fetchone()[0] == 22
        )
    usage_events = [
        call.kwargs
        for call in logger._write.call_args_list
        if call.kwargs.get("event") == "model_usage"
    ]
    assert len(usage_events) == 22
    diagnostics = [
        call.kwargs
        for call in logger._write.call_args_list
        if call.kwargs.get("event") == "model_diagnostics"
    ]
    assert len(diagnostics) == 22
    assert [event["web_search_offered"] for event in diagnostics] == [
        search_enabled,
        False,
    ] * 11
    assert all(event["web_search_occurred"] is False for event in diagnostics)
    contexts = [
        call.kwargs
        for call in logger._write.call_args_list
        if call.kwargs.get("event") == "model_context"
    ]
    assert len(contexts) == 11
    assert contexts[0]["memory_chars"] == 0
    assert contexts[-1]["memory_chars"] > 0
    assert all(
        event["conversation_chars"] == len("Run the requested tool")
        for event in contexts
    )


@pytest.mark.parametrize(
    "command, answer, executes, prompts",
    [
        ("pwd", "n", True, False),
        ("mkdir example", "y", True, True),
        ("mkdir example", "n", False, True),
        ("sudo reboot", "y", False, False),
    ],
)
async def test_actual_permission_gate_before_terminal_execution(
    wired, monkeypatch, command, answer, executes, prompts
):
    agent, _, _, _ = wired
    runner = Mock(
        return_value=subprocess.CompletedProcess([], 0, stdout="OK", stderr="")
    )
    monkeypatch.setattr(subprocess, "run", runner)
    prompt = Mock(return_value=answer)
    monkeypatch.setattr("builtins.input", prompt)
    result = await agent._handle_tool_call(
        ToolCall(
            "call_test",
            "terminal",
            json.dumps({"command": command, "working_directory": None}),
        ),
        "request_test",
    )
    assert runner.called is executes
    assert prompt.called is prompts
    assert (result == "OK") is executes


def test_single_message_context_removes_only_redundant_wrapper(wired):
    agent, _, _, _ = wired
    assert agent._build_conversation_context([]) == ""
    assert (
        agent._build_conversation_context(
            [{"role": "user", "content": "Keep this exactly"}]
        )
        == "Keep this exactly"
    )
    context = agent._build_conversation_context(
        [
            {"role": "assistant", "content": "Earlier answer"},
            {"role": "user", "content": "Follow-up"},
        ]
    )
    assert "ASSISTANT: Earlier answer" in context
    assert context.endswith("Current user message:\nFollow-up")
