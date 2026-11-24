"""CLI: ``python -m agent_resolution_workflow demo`` or ``... chat``."""

from __future__ import annotations

import argparse
import sys

from .agent import ResolutionAgent
from .demo import main as demo_main


def chat_main(argv: list[str] | None = None) -> int:
    """Interactive chat: free-form conversation with the resolution agent."""
    parser = argparse.ArgumentParser(description="Chat with the Northstar Goods resolution agent.")
    parser.add_argument("--live", action="store_true", help="Use live Gemini instead of the scripted mock.")
    args = parser.parse_args(argv)
    agent = ResolutionAgent(live=args.live)
    print("Northstar Goods support — type your message, or 'quit' to stop.")
    print("(Try: 'My order CM-1042 arrived damaged.')")
    while True:
        try:
            message = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            return 0
        if message.lower() in ("quit", "exit", "bye"):
            print("Goodbye.")
            return 0
        if not message:
            continue
        print(f"Agent: {agent.run(message)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Dispatch to the demo or the interactive chat."""
    parser = argparse.ArgumentParser(
        description="Northstar Goods customer resolution agent.",
        epilog="Commands: demo (scripted CM-1042 conversation), chat (interactive).",
    )
    parser.add_argument("command", choices=["demo", "chat"], help="What to run.")
    parser.add_argument("--live", action="store_true", help="Use live Gemini instead of the scripted mock.")
    args = parser.parse_args(argv)
    if args.command == "demo":
        return demo_main(["--live"] if args.live else [])
    return chat_main(["--live"] if args.live else [])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
