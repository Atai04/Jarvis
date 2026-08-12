import asyncio

from app.agent.orchestrator import AgentOrchestrator
from app.config.settings import get_settings
from app.llm.openai import OpenAIProvider


async def main():
    settings = get_settings()

    provider = OpenAIProvider(settings)
    agent = AgentOrchestrator(provider)

    print()
    print("================================")
    print("        J.A.R.V.I.S.")
    print("================================")
    print("JARVIS is online.")
    print("Type 'exit' to quit.")
    print()

    while True:
        try:
            user_input = input("You > ").strip()

            if not user_input:
                continue

            if user_input.lower() in {"exit", "quit"}:
                print("JARVIS > Goodbye.")
                break

            response = await agent.run(user_input)

            print(f"\nJARVIS > {response}\n")

        except KeyboardInterrupt:
            print("\nJARVIS > Goodbye.")
            break

        except Exception as exc:
            print(f"\nJARVIS ERROR > {exc}\n")


if __name__ == "__main__":
    asyncio.run(main())
