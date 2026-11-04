from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from openai.types.responses import Response

from app.browser.tools import OpenURLTool
from app.config.settings import Settings
from app.llm.base import LLMResponse, SourceCitation, TokenUsage, ToolCall
from app.llm.openai import OpenAIProvider
from app.tools.base import PermissionLevel, ToolResult
from app.tools.registry import ToolRegistry


def response(output=(), response_id="resp_test"):
    """Use SDK-validated payloads without constructing a network client."""
    return Response.model_validate(
        {
            "id": response_id,
            "created_at": 0,
            "object": "response",
            "model": "gpt-5.2",
            "output": list(output),
            "parallel_tool_calls": False,
            "tool_choice": "auto",
            "tools": [],
        }
    )


def message(text="An answer.", annotations=()):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [
            {"type": "output_text", "text": text, "annotations": list(annotations)}
        ],
    }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("WEB_SEARCH_ENABLED", raising=False)
    monkeypatch.delenv("WEB_SEARCH_MAX_REQUESTS_PER_TURN", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    fake = SimpleNamespace(responses=SimpleNamespace(create=AsyncMock()))
    monkeypatch.setattr("app.llm.openai.AsyncOpenAI", Mock(return_value=fake))
    return fake


def provider(**kwargs):
    return OpenAIProvider(
        Settings(_env_file=None, openai_api_key="unit-test-placeholder", **kwargs)
    )


def test_settings_default_and_environment(client, monkeypatch):
    assert provider().web_search_enabled is False
    assert provider().model == "gpt-5.2"
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "true")
    assert provider().web_search_enabled is True
    monkeypatch.setenv("WEB_SEARCH_ENABLED", "false")
    assert provider().web_search_enabled is False


@pytest.mark.parametrize("enabled", [False, True])
async def test_initial_and_continuation_requests(client, enabled):
    llm = provider(web_search_enabled=enabled, web_search_max_requests_per_turn=2)
    registry = ToolRegistry()
    registry.register(OpenURLTool())
    schemas = registry.openai_schemas()
    original = deepcopy(schemas)
    client.responses.create.side_effect = [
        response(
            [
                {
                    "type": "function_call",
                    "name": "open_url",
                    "call_id": "call_1",
                    "arguments": '{"url":"https://example.com"}',
                }
            ]
        ),
        response([message()], "resp_next"),
    ]

    first = await llm.generate("System rules", "Question", schemas)
    assert first.tool_calls == [
        ToolCall("call_1", "open_url", '{"url":"https://example.com"}')
    ]
    final = await llm.continue_with_tool_results(
        first, [("call_1", "Page text")], schemas
    )

    expected_tools = schemas + (
        [{"type": "web_search", "search_context_size": "low"}] if enabled else []
    )
    initial, continuation = client.responses.create.call_args_list
    assert initial.kwargs == {
        "model": "gpt-5.2",
        "instructions": "System rules",
        "input": "Question",
        "tools": expected_tools,
        "parallel_tool_calls": False,
    }
    assert continuation.kwargs == {
        "model": "gpt-5.2",
        "instructions": "System rules",
        "previous_response_id": "resp_test",
        "input": [
            {"type": "function_call_output", "call_id": "call_1", "output": "Page text"}
        ],
        "tools": expected_tools,
        "parallel_tool_calls": False,
    }
    assert schemas == original
    assert final.content == final.display_text() == "An answer."
    assert final.system_prompt == "System rules"


@pytest.mark.parametrize("enabled", [False, True])
def test_duplicate_native_tools_and_custom_name(client, enabled):
    llm = provider(web_search_enabled=enabled)
    custom = {"type": "function", "name": "web_search"}
    tools = [
        custom,
        {
            "type": "web_search",
            "search_context_size": "high",
            "filters": {"allowed_domains": ["example.com"]},
        },
        {"type": "web_search_2025_08_26"},
        {"type": "web_search_preview"},
    ]
    original = deepcopy(tools)
    built = llm._build_tools(tools)
    assert tools == original
    assert built == [custom] + (
        [
            {
                "type": "web_search",
                "search_context_size": "low",
                "filters": {"allowed_domains": ["example.com"]},
            }
        ]
        if enabled
        else []
    )


def test_manual_enable_remains_idempotent(client):
    llm = provider()
    llm.enable_web_search()
    llm.enable_web_search()
    assert llm._build_tools(llm._build_tools(None)) == [
        {"type": "web_search", "search_context_size": "low"}
    ]


async def test_mixed_search_citations_and_function_calls(client):
    citation = {
        "type": "url_citation",
        "url": "https://example.com/source",
        "title": "Source",
        "start_index": 0,
        "end_index": 5,
    }
    raw = response(
        [
            {
                "type": "web_search_call",
                "id": "ws_test",
                "status": "completed",
                "action": {"type": "search", "query": "test"},
            },
            message("First."),
            message("Next.", [citation]),
            {
                "type": "function_call",
                "name": "open_url",
                "call_id": "call_2",
                "arguments": '{"url":"https://example.com"}',
            },
        ]
    )
    client.responses.create.return_value = raw
    parsed = await provider(web_search_enabled=True).generate("Rules", "Question")
    assert parsed.raw_response is raw
    assert parsed.content == "First.Next."
    assert parsed.citations == [
        SourceCitation("https://example.com/source", "Source", 6, 11)
    ]
    assert [call.call_id for call in parsed.tool_calls] == ["call_2"]
    assert parsed.display_text() == "First.Next. (https://example.com/source)"


async def test_continuation_preserves_citations(client):
    raw = response(
        [
            message(
                "Fact.",
                [
                    {
                        "type": "url_citation",
                        "url": "https://example.com",
                        "title": "Example",
                        "start_index": 0,
                        "end_index": 5,
                    }
                ],
            )
        ]
    )
    client.responses.create.return_value = raw
    parsed = await provider(web_search_enabled=True).continue_with_tool_results(
        LLMResponse("", "gpt-5.2", raw_response=response()), [("call_1", "OK")]
    )
    assert parsed.content == "Fact."
    assert parsed.citations[0].title == "Example"
    assert parsed.tool_calls == []


def test_empty_and_refusal_outputs():
    assert OpenAIProvider._parse_response(response(), "gpt-5.2").content == ""
    raw = response(
        [
            {
                "id": "msg_refusal",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "refusal", "refusal": "No"}],
            }
        ]
    )
    assert OpenAIProvider._parse_response(raw, "gpt-5.2").citations == []


async def test_missing_previous_response_does_not_call_api(client):
    with pytest.raises(RuntimeError, match="Previous response is missing"):
        await provider().continue_with_tool_results(LLMResponse("", "gpt-5.2"), [])
    client.responses.create.assert_not_awaited()


async def test_errors_propagate_without_silent_model_fallback(client):
    client.responses.create.side_effect = RuntimeError("Unsupported model/tool")
    with pytest.raises(RuntimeError, match="Unsupported model/tool"):
        await provider(web_search_enabled=True).generate("Rules", "Question")
    client.responses.create.assert_awaited_once()


def test_citation_rendering_preserves_offsets_and_original_content():
    result = LLMResponse(
        "One. Two.",
        "gpt-5.2",
        citations=[
            SourceCitation("https://one.example", "One", 0, 4),
            SourceCitation("https://two.example", "Two", 5, 9),
        ],
    )
    assert result.display_text() == (
        "One. (https://one.example) Two. (https://two.example)"
    )
    assert result.content == "One. Two."


@pytest.mark.parametrize("approved", [False, True])
async def test_agent_keeps_custom_permissions_and_displays_citations(
    client, monkeypatch, tmp_path, approved
):
    # Logger initialization and database state must not touch the real workspace.
    monkeypatch.chdir(tmp_path)
    from app.agent.orchestrator import AgentOrchestrator
    from app.logging.logger import logger

    usage_reporter = Mock()
    monkeypatch.setattr(logger, "model_usage", usage_reporter)

    registry = ToolRegistry()
    tool = OpenURLTool()
    tool.permission = PermissionLevel.CONFIRM
    tool.execute = AsyncMock(return_value=ToolResult(True, "Page text"))
    registry.register(tool)
    permissions = Mock()
    permissions.request_confirmation.return_value = approved
    memory = Mock()
    memory.get_preference.return_value = None
    memory.get_conversations.return_value = [{"role": "user", "content": "Question"}]
    client.responses.create.side_effect = [
        response(
            [
                {
                    "type": "web_search_call",
                    "id": "ws_test",
                    "status": "completed",
                    "action": {"type": "search", "query": "test"},
                },
                {
                    "type": "function_call",
                    "name": "open_url",
                    "call_id": "call_1",
                    "arguments": '{"url":"https://example.com"}',
                },
            ]
        ),
        response(
            [
                message(
                    "Fact.",
                    [
                        {
                            "type": "url_citation",
                            "url": "https://example.com",
                            "title": "Example",
                            "start_index": 0,
                            "end_index": 5,
                        }
                    ],
                )
            ],
            "resp_final",
        ),
    ]
    agent = AgentOrchestrator(
        provider(web_search_enabled=True), registry, permissions, memory
    )
    final = await agent.run("Question")
    assert usage_reporter.call_count == 2
    assert (
        usage_reporter.call_args_list[0].args == usage_reporter.call_args_list[1].args
    )
    assert usage_reporter.call_args.args[1] is None
    assert [
        any(tool["type"] == "web_search" for tool in call.kwargs["tools"])
        for call in client.responses.create.call_args_list
    ] == [True, False]
    assert final == "Fact. (https://example.com)"
    assert memory.save_conversation.call_args.args[1:] == ("assistant", final)
    permissions.request_confirmation.assert_called_once()
    if approved:
        tool.execute.assert_awaited_once_with({"url": "https://example.com"})
    else:
        tool.execute.assert_not_awaited()
    continuation = client.responses.create.call_args.kwargs
    assert continuation["input"] == [
        {
            "type": "function_call_output",
            "call_id": "call_1",
            "output": "Page text"
            if approved
            else "The user denied the requested action.",
        }
    ]


def test_search_limit_configuration(client, monkeypatch):
    from pydantic import ValidationError

    assert provider().web_search_max_requests_per_turn == 1
    monkeypatch.setenv("WEB_SEARCH_MAX_REQUESTS_PER_TURN", "3")
    assert provider().web_search_max_requests_per_turn == 3
    with pytest.raises(ValidationError):
        provider(web_search_max_requests_per_turn=-1)


@pytest.mark.parametrize(
    "enabled, limit", [(False, 2), (True, 0), (True, 1), (True, 2)]
)
async def test_search_request_limit_preserves_functions(client, enabled, limit):
    llm = provider(web_search_enabled=enabled, web_search_max_requests_per_turn=limit)
    # Offering search consumes the allowance even if the model never searches.
    client.responses.create.return_value = response([message()])
    custom = {"type": "function", "name": "web_search"}
    schemas = [custom, {"type": "web_search"}]
    result = await llm.generate("Rules", "Question", schemas)
    for index in range(3):
        expected_count = min(index + 1, limit) if enabled else 0
        assert result.web_search_requests == expected_count
        if index < 2:
            result = await llm.continue_with_tool_results(
                result, [("call_1", "tool result")], schemas
            )
    for index, call in enumerate(client.responses.create.call_args_list):
        expected = [custom]
        if enabled and index < limit:
            expected += [{"type": "web_search", "search_context_size": "low"}]
        assert call.kwargs["tools"] == expected


async def test_turn_counters_are_independent(client):
    llm = provider(web_search_enabled=True)
    client.responses.create.return_value = response([message()])
    first = await llm.generate("Rules", "First")
    second = await llm.generate("Rules", "Second")
    await llm.continue_with_tool_results(first, [("a", "OK")])
    await llm.continue_with_tool_results(second, [("b", "OK")])
    third = await llm.generate("Rules", "Third")
    assert third.web_search_requests == 1
    assert [
        bool(call.kwargs["tools"]) for call in client.responses.create.call_args_list
    ] == [True, True, False, False, True]


async def test_actual_sdk_usage_is_extracted_on_each_response(client):
    from openai.types.responses.response_usage import ResponseUsage

    raw = response([message("Sensitive answer")])
    raw.usage = ResponseUsage.model_validate(
        {
            "input_tokens": 120,
            "output_tokens": 30,
            "total_tokens": 150,
            "input_tokens_details": {"cached_tokens": 80, "cache_write_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 20},
        }
    )
    client.responses.create.return_value = raw
    llm = provider()
    first = await llm.generate("Sensitive instructions", "Sensitive question")
    final = await llm.continue_with_tool_results(
        first, [("call_1", "Sensitive result")]
    )
    # Do not add cached/reasoning subtotals again or estimate from text length.
    assert first.usage == final.usage == TokenUsage(120, 30, 150)


@pytest.mark.parametrize(
    "usage, expected",
    [
        (None, None),
        (
            SimpleNamespace(input_tokens=0, output_tokens=0, total_tokens=0),
            TokenUsage(0, 0, 0),
        ),
        (SimpleNamespace(input_tokens=12), TokenUsage(input_tokens=12)),
    ],
)
def test_usage_missing_partial_and_zero(usage, expected):
    raw = SimpleNamespace(output=[], output_text="", usage=usage)
    assert OpenAIProvider._parse_response(raw, "gpt-5.2").usage == expected


def test_usage_logging_has_only_allowlisted_counts(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    from app.logging.logger import StructuredLogger

    log = StructuredLogger.__new__(StructuredLogger)
    log._write = Mock()
    log.model_usage("request-test", TokenUsage(12, 3, 15))
    log._write.assert_called_once_with(
        event="model_usage",
        request_id="request-test",
        input_tokens=12,
        output_tokens=3,
        total_tokens=15,
    )
    log.model_usage("request-test", None)
    assert log._write.call_args.kwargs == {
        "event": "model_usage",
        "request_id": "request-test",
        "input_tokens": None,
        "output_tokens": None,
        "total_tokens": None,
    }


@pytest.mark.parametrize(
    "content",
    [
        "See [release](https://example.com/release).",
        "See <https://example.com/release>.",
        "See https://example.com/release.",
        "See (https://example.com/release).",
    ],
)
def test_existing_citation_urls_are_not_appended(content):
    result = LLMResponse(
        content,
        "gpt-5.2",
        citations=[
            SourceCitation("https://example.com/release", "Release", 0, len(content))
        ],
    )
    assert result.display_text() == content
    assert result.content == content


def test_repeated_annotations_add_one_missing_url_without_changing_metadata():
    citation = SourceCitation("https://example.com/source", "Source", 0, 4)
    result = LLMResponse(
        "One. Two.",
        "gpt-5.2",
        citations=[
            citation,
            citation,
            SourceCitation(citation.url, "Source", 5, 9),
        ],
    )
    assert result.display_text() == "One. (https://example.com/source) Two."
    assert len(result.citations) == 3
    assert result.content == "One. Two."
    assert result.display_text() == result.display_text()


def test_url_prefix_is_not_mistaken_for_same_citation():
    result = LLMResponse(
        "See https://example.com/release-next",
        "gpt-5.2",
        citations=[SourceCitation("https://example.com/release", "Release", 0, 3)],
    )
    assert (
        result.display_text()
        == "See (https://example.com/release) https://example.com/release-next"
    )


async def test_search_diagnostics_distinguish_offered_from_occurred(client):
    llm = provider(web_search_enabled=True, web_search_max_requests_per_turn=2)
    client.responses.create.side_effect = [
        response([message("No search needed")]),
        response(
            [
                {
                    "type": "web_search_call",
                    "id": "ws_1",
                    "status": "completed",
                    "action": {"type": "search", "query": "PRIVATE QUERY"},
                },
                message("Answer"),
            ]
        ),
        response([message("No more search allowance")]),
    ]
    first = await llm.generate("PRIVATE RULES", "PRIVATE INPUT")
    assert first.web_search_call_count == 0
    assert first.request_metrics.web_search_offered is True
    second = await llm.continue_with_tool_results(first, [("call_1", "PRIVATE RESULT")])
    assert second.web_search_call_count == second.web_search_completed_count == 1
    assert second.request_metrics.continuation is True
    assert second.request_metrics.web_search_offered is True
    assert second.web_search_requests == 2
    third = await llm.continue_with_tool_results(second, [("call_2", "Result")])
    assert third.request_metrics.web_search_offered is False
    assert third.web_search_call_count == 0
    assert third.web_search_requests == 2


async def test_disabled_search_diagnostics_and_request_sizes(client):
    client.responses.create.return_value = response([message()])
    tools = [
        {"type": "function", "name": "private_tool", "parameters": {"type": "object"}}
    ]
    result = await provider().generate("Rules", "Question", tools)
    import json

    assert result.web_search_call_count == 0
    assert result.request_metrics.web_search_offered is False
    assert result.request_metrics.instructions_chars == len("Rules")
    assert result.request_metrics.input_json_chars == len(json.dumps("Question"))
    assert result.request_metrics.custom_tool_count == 1
    assert result.request_metrics.custom_tool_schema_json_chars == len(
        json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
    )


def test_incomplete_search_is_not_reported_as_completed():
    raw = SimpleNamespace(
        output=[
            SimpleNamespace(type="web_search_call", status="failed"),
            SimpleNamespace(type="web_search_call", status="completed"),
            SimpleNamespace(
                type="function_call", name="web_search", call_id="fn", arguments="{}"
            ),
        ],
        output_text="",
        usage=None,
    )
    result = OpenAIProvider._parse_response(raw, "gpt-5.2")
    assert result.web_search_call_count == 2
    assert result.web_search_completed_count == 1
    assert len(result.tool_calls) == 1


def test_diagnostic_logging_never_serializes_content_or_queries(monkeypatch, tmp_path):
    import json

    from app.llm.base import RequestMetrics

    monkeypatch.chdir(tmp_path)
    from app.logging.logger import StructuredLogger

    log = StructuredLogger.__new__(StructuredLogger)
    log._write = Mock()
    result = LLMResponse(
        "SECRET ANSWER",
        "SECRET MODEL",
        raw_response={"query": "SECRET QUERY"},
        system_prompt="SECRET RULES",
        web_search_call_count=1,
        web_search_completed_count=1,
        citations=[SourceCitation("https://secret.example", "SECRET TITLE", 0, 1)],
        request_metrics=RequestMetrics(12, 34, 56, 1, True, False),
    )
    log.model_diagnostics("request-test", result)
    assert log._write.call_args.kwargs == {
        "event": "model_diagnostics",
        "request_id": "request-test",
        "web_search_occurred": True,
        "web_search_call_count": 1,
        "web_search_completed_count": 1,
        "web_search_offered": True,
        "continuation": False,
        "instructions_chars": 12,
        "custom_tool_schema_json_chars": 34,
        "custom_tool_count": 1,
        "input_json_chars": 56,
    }
    assert "SECRET" not in json.dumps(log._write.call_args.kwargs)
    log.model_context(
        "request-test", memory_chars=10, conversation_chars=20, user_message_chars=20
    )
    assert log._write.call_args.kwargs == {
        "event": "model_context",
        "request_id": "request-test",
        "memory_chars": 10,
        "conversation_chars": 20,
        "user_message_chars": 20,
    }
