import asyncio

from app.agent.orchestrator import AgentOrchestrator
from app.config.settings import Settings, get_settings
from app.github.client import GitHubClient
from app.github.tools import InspectRepositoryTool, ListRepositoriesTool
from app.llm.openai import OpenAIProvider
from app.memory.database import Database
from app.memory.repository import MemoryRepository
from app.memory.tools import (
    GetPreferenceTool,
    GetProjectTool,
    RememberPreferenceTool,
    RememberProjectTool,
)
from app.security.permissions import PermissionEngine
from app.tools.filesystem import ListDirectoryTool, ReadFileTool
from app.tools.macos import OpenApplicationTool
from app.tools.registry import ToolRegistry
from app.tools.system import GetSystemInfoTool
from app.tools.terminal import TerminalTool


def build_tool_registry(
    settings: Settings,
    memory: MemoryRepository,
) -> ToolRegistry:
    registry = ToolRegistry()

    registry.register(OpenApplicationTool())
    registry.register(GetSystemInfoTool())
    registry.register(ListDirectoryTool())
    registry.register(ReadFileTool())
    registry.register(TerminalTool())

    github_client = GitHubClient(settings)

    registry.register(ListRepositoriesTool(github_client))
    registry.register(InspectRepositoryTool(github_client))

    registry.register(RememberPreferenceTool(memory))
    registry.register(GetPreferenceTool(memory))
    registry.register(RememberProjectTool(memory))
    registry.register(GetProjectTool(memory))

    return registry


def build_memory() -> MemoryRepository:
    database = Database()
    database.initialize()

    return MemoryRepository(database)


async def main() -> None:
    settings = get_settings()

    provider = OpenAIProvider(settings)
    memory = build_memory()
    tools = build_tool_registry(settings, memory)
    permissions = PermissionEngine()

    agent = AgentOrchestrator(
        llm=provider,
        tools=tools,
        permissions=permissions,
        memory=memory,
    )

    print()
    print("================================")
    print("        J.A.R.V.I.S.")
    print("================================")
    print("JARVIS is online.")
    print(f"Tools loaded: {len(tools.all())}")
    print("Permission system: ONLINE")
    print("Memory system: ONLINE")
    print("GitHub tools: ONLINE")
    print("Type 'exit' to quit.")
    print()

    while True:
        try:
            user_input = input("You > ").strip()

            if not user_input:
                continue

            if user_input.lower() in {
                "exit",
                "quit",
            }:
                print("JARVIS > Goodbye.")
                break

            response = await agent.run(user_input)

            print()
            print(f"JARVIS > {response}")
            print()

        except KeyboardInterrupt:
            print("\nJARVIS > Goodbye.")
            break

        except Exception as exc:  # noqa: BLE001 - top-level REPL guard
            print(f"\nJARVIS ERROR > {exc}\n")


if __name__ == "__main__":
    asyncio.run(main())