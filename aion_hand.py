#!/usr/bin/env python3
"""Quick start script for Aion Hand — interactive chat with graceful fallback."""
import asyncio
import sys

try:
    from aion_core.agent.core import AionHand
except ImportError as exc:
    print(f"[aion] Failed to import AionHand: {exc}", file=sys.stderr)
    print("Try: pip install -e .", file=sys.stderr)
    sys.exit(1)


async def main():
    agent = AionHand()
    try:
        await agent.start()
    except Exception as exc:
        print(f"[aion] Failed to start agent: {exc}", file=sys.stderr)
        sys.exit(1)
    print("Aion Hand is running. Type 'quit' to exit.")
    print(f"  Provider: {agent.config.default_provider} / {agent.config.default_model}")
    print(f"  Home: {agent.config.home_dir}")
    while True:
        try:
            message = input("\nYou: ")
            if message.lower().strip() in ("quit", "exit", "/quit", "/exit"):
                break
            if not message.strip():
                continue
            result = await agent.chat(message)
            content = result.get("content", "") if isinstance(result, dict) else str(result)
            print(f"\nAion: {content}")
            tools = result.get("tools_used", []) if isinstance(result, dict) else []
            if tools:
                print(f"  [tools: {', '.join(tools)}]")
        except KeyboardInterrupt:
            print("\n[aion] Interrupted")
            break
        except EOFError:
            break
        except Exception as exc:
            print(f"[aion] Chat error: {exc}", file=sys.stderr)
    await agent.shutdown()
    print("Goodbye!")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
