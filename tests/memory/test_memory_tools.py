import pytest

from app.memory.database import Database
from app.memory.repository import MemoryRepository
from app.memory.tools import (
    GetPreferenceTool,
    GetProjectTool,
    RememberPreferenceTool,
    RememberProjectTool,
)


@pytest.fixture
def memory(tmp_path):
    db_path = tmp_path / "test_jarvis.db"
    database = Database(path=db_path)
    database.initialize()
    return MemoryRepository(database)


@pytest.fixture
def remember_tool(memory):
    return RememberPreferenceTool(memory)


@pytest.fixture
def get_tool(memory):
    return GetPreferenceTool(memory)


@pytest.fixture
def remember_project_tool(memory):
    return RememberProjectTool(memory)


@pytest.fixture
def get_project_tool(memory):
    return GetProjectTool(memory)


@pytest.mark.asyncio
async def test_remember_preference_saves_new_key(remember_tool, memory):
    result = await remember_tool.execute(
        {"key": "favorite_project", "value": "smart-waste-sorter"}
    )

    assert result.success is True
    assert "favorite_project" in result.output
    assert memory.get_preference("favorite_project") == "smart-waste-sorter"


@pytest.mark.asyncio
async def test_remember_preference_updates_existing_key(remember_tool, memory):
    await remember_tool.execute(
        {"key": "favorite_project", "value": "smart-waste-sorter"}
    )

    result = await remember_tool.execute(
        {"key": "favorite_project", "value": "jarvis"}
    )

    assert result.success is True
    assert memory.get_preference("favorite_project") == "jarvis"


@pytest.mark.asyncio
async def test_remember_preference_rejects_empty_key(remember_tool):
    result = await remember_tool.execute({"key": "", "value": "something"})

    assert result.success is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_remember_preference_rejects_empty_value(remember_tool):
    result = await remember_tool.execute({"key": "favorite_project", "value": ""})

    assert result.success is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_get_preference_returns_saved_value(remember_tool, get_tool):
    await remember_tool.execute(
        {"key": "favorite_project", "value": "smart-waste-sorter"}
    )

    result = await get_tool.execute({"key": "favorite_project"})

    assert result.success is True
    assert result.output == "smart-waste-sorter"


@pytest.mark.asyncio
async def test_get_preference_missing_key_returns_error(get_tool):
    result = await get_tool.execute({"key": "does_not_exist"})

    assert result.success is False
    assert result.error is not None
    assert "does_not_exist" in result.error


@pytest.mark.asyncio
async def test_get_preference_rejects_empty_key(get_tool):
    result = await get_tool.execute({"key": ""})

    assert result.success is False
    assert result.error is not None


def test_remember_tool_schema_requires_key_and_value(remember_tool):
    schema = remember_tool.schema()

    assert schema["required"] == ["key", "value"]
    assert "key" in schema["properties"]
    assert "value" in schema["properties"]


def test_get_tool_schema_requires_key(get_tool):
    schema = get_tool.schema()

    assert schema["required"] == ["key"]
    assert "key" in schema["properties"]


@pytest.mark.asyncio
async def test_remember_project_saves_new_project(remember_project_tool, memory):
    result = await remember_project_tool.execute(
        {
            "project_name": "smart-waste-sorter",
            "description": "ESP32-CAM based waste classifier capstone project.",
        }
    )

    assert result.success is True
    assert "smart-waste-sorter" in result.output

    stored = memory.get_project("smart-waste-sorter")
    assert stored is not None
    assert stored["description"] == "ESP32-CAM based waste classifier capstone project."


@pytest.mark.asyncio
async def test_remember_project_updates_existing_project(remember_project_tool, memory):
    await remember_project_tool.execute(
        {
            "project_name": "jarvis",
            "description": "First version.",
        }
    )

    result = await remember_project_tool.execute(
        {
            "project_name": "jarvis",
            "description": "Personal AI assistant with tool calling and memory.",
        }
    )

    assert result.success is True

    stored = memory.get_project("jarvis")
    assert stored is not None
    assert stored["description"] == "Personal AI assistant with tool calling and memory."


@pytest.mark.asyncio
async def test_remember_project_rejects_empty_name(remember_project_tool):
    result = await remember_project_tool.execute(
        {"project_name": "", "description": "something"}
    )

    assert result.success is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_remember_project_rejects_empty_description(remember_project_tool):
    result = await remember_project_tool.execute(
        {"project_name": "jarvis", "description": ""}
    )

    assert result.success is False
    assert result.error is not None


@pytest.mark.asyncio
async def test_get_project_returns_saved_description(
    remember_project_tool, get_project_tool
):
    await remember_project_tool.execute(
        {
            "project_name": "smart-waste-sorter",
            "description": "ESP32-CAM based waste classifier capstone project.",
        }
    )

    result = await get_project_tool.execute({"project_name": "smart-waste-sorter"})

    assert result.success is True
    assert "ESP32-CAM" in result.output


@pytest.mark.asyncio
async def test_get_project_missing_project_returns_error(get_project_tool):
    result = await get_project_tool.execute({"project_name": "does-not-exist"})

    assert result.success is False
    assert result.error is not None
    assert "does-not-exist" in result.error


@pytest.mark.asyncio
async def test_get_project_rejects_empty_name(get_project_tool):
    result = await get_project_tool.execute({"project_name": ""})

    assert result.success is False
    assert result.error is not None


def test_remember_project_tool_schema_requires_name_and_description(
    remember_project_tool,
):
    schema = remember_project_tool.schema()

    assert schema["required"] == ["project_name", "description"]
    assert "project_name" in schema["properties"]
    assert "description" in schema["properties"]


def test_get_project_tool_schema_requires_name(get_project_tool):
    schema = get_project_tool.schema()

    assert schema["required"] == ["project_name"]
    assert "project_name" in schema["properties"]