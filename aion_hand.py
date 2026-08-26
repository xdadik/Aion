#!/usr/bin/env python3
"""Quick start script for Aion Hand."""
import asyncio

from aion_core.agent.core import AionHand


async def main():
    agent = AionHand()
    await agent.start()
    print("Aion Hand is running. Type 'quit' to exit.")
    while True:
        try:
            message = input("\nYou: ")
            if message.lower() in ('quit', 'exit', '/quit'):
                break
            result = await agent.chat(message)
            print(f"\nAion: {result.get('content', '')}")
        except KeyboardInterrupt:
            break
    await agent.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
