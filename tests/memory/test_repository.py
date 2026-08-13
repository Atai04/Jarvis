from app.memory.database import Database
from app.memory.repository import MemoryRepository


def test_save_and_get_conversations(tmp_path):
    database = Database(tmp_path / "jarvis.db")
    database.initialize()

    repository = MemoryRepository(database)

    first_id = repository.save_conversation(
        "request-123",
        "user",
        "Hello JARVIS",
    )

    second_id = repository.save_conversation(
        "request-123",
        "assistant",
        "Hello. How can I help?",
    )

    conversations = repository.get_conversations("request-123")

    assert first_id == 1
    assert second_id == 2
    assert len(conversations) == 2

    assert conversations[0]["role"] == "user"
    assert conversations[0]["content"] == "Hello JARVIS"

    assert conversations[1]["role"] == "assistant"
    assert conversations[1]["content"] == "Hello. How can I help?"


def test_get_conversations_filters_by_request_id(tmp_path):
    database = Database(tmp_path / "jarvis.db")
    database.initialize()

    repository = MemoryRepository(database)

    repository.save_conversation(
        "request-1",
        "user",
        "First request",
    )

    repository.save_conversation(
        "request-2",
        "user",
        "Second request",
    )

    conversations = repository.get_conversations("request-1")

    assert len(conversations) == 1
    assert conversations[0]["content"] == "First request"


def test_save_project(tmp_path):
    database = Database(tmp_path / "jarvis.db")
    database.initialize()

    repository = MemoryRepository(database)

    project_id = repository.save_project(
        "JARVIS",
        "Personal AI assistant",
    )

    assert project_id == 1


def test_save_preference(tmp_path):
    database = Database(tmp_path / "jarvis.db")
    database.initialize()

    repository = MemoryRepository(database)

    preference_id = repository.save_preference(
        "language",
        "tr",
    )

    assert preference_id == 1


def test_get_project(tmp_path):
    database = Database(tmp_path / "jarvis.db")
    database.initialize()

    repository = MemoryRepository(database)

    repository.save_project(
        "JARVIS",
        "Personal AI assistant",
    )

    project = repository.get_project("JARVIS")

    assert project is not None
    assert project["name"] == "JARVIS"
    assert project["description"] == "Personal AI assistant"


def test_get_project_returns_none_for_missing_project(tmp_path):
    database = Database(tmp_path / "jarvis.db")
    database.initialize()

    repository = MemoryRepository(database)

    assert repository.get_project("Unknown") is None


def test_update_project(tmp_path):
    database = Database(tmp_path / "jarvis.db")
    database.initialize()

    repository = MemoryRepository(database)

    repository.save_project(
        "JARVIS",
        "Old description",
    )

    updated = repository.update_project(
        "JARVIS",
        "New description",
    )

    assert updated is True

    project = repository.get_project("JARVIS")

    assert project is not None
    assert project["description"] == "New description"


def test_get_preference(tmp_path):
    database = Database(tmp_path / "jarvis.db")
    database.initialize()

    repository = MemoryRepository(database)

    repository.save_preference(
        "language",
        "tr",
    )

    assert repository.get_preference("language") == "tr"


def test_get_missing_preference(tmp_path):
    database = Database(tmp_path / "jarvis.db")
    database.initialize()

    repository = MemoryRepository(database)

    assert repository.get_preference("language") is None


def test_update_preference(tmp_path):
    database = Database(tmp_path / "jarvis.db")
    database.initialize()

    repository = MemoryRepository(database)

    repository.save_preference(
        "language",
        "tr",
    )

    updated = repository.update_preference(
        "language",
        "en",
    )

    assert updated is True
    assert repository.get_preference("language") == "en"


def test_update_missing_project_returns_false(tmp_path):
    database = Database(tmp_path / "jarvis.db")
    database.initialize()

    repository = MemoryRepository(database)

    updated = repository.update_project(
        "Unknown",
        "New description",
    )

    assert updated is False


def test_update_missing_preference_returns_false(tmp_path):
    database = Database(tmp_path / "jarvis.db")
    database.initialize()

    repository = MemoryRepository(database)

    updated = repository.update_preference(
        "language",
        "en",
    )

    assert updated is False


def test_conversations_preserve_insert_order(tmp_path):
    database = Database(tmp_path / "jarvis.db")
    database.initialize()

    repository = MemoryRepository(database)

    repository.save_conversation(
        "request-123",
        "user",
        "Message 1",
    )

    repository.save_conversation(
        "request-123",
        "assistant",
        "Message 2",
    )

    repository.save_conversation(
        "request-123",
        "user",
        "Message 3",
    )

    conversations = repository.get_conversations("request-123")

    assert [item["content"] for item in conversations] == [
        "Message 1",
        "Message 2",
        "Message 3",
    ]


def test_save_project_without_description(tmp_path):
    database = Database(tmp_path / "jarvis.db")
    database.initialize()

    repository = MemoryRepository(database)

    repository.save_project("JARVIS")

    project = repository.get_project("JARVIS")

    assert project is not None
    assert project["name"] == "JARVIS"
    assert project["description"] is None