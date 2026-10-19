"""Command line: `python -m assistant console` or `python -m assistant demo`."""

from __future__ import annotations

import argparse

from .adapters.console import DEMO_FOLDER, run_console, run_demo


def main() -> None:
    parser = argparse.ArgumentParser(prog="assistant", description="AI chat assistant for a business.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in [("console", "chat in the terminal"), ("demo", "run a scripted conversation")]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--business", default=DEMO_FOLDER, help="folder with business.json and knowledge/")
    args = parser.parse_args()
    if args.command == "console":
        run_console(args.business)
    else:
        run_demo(args.business)


if __name__ == "__main__":
    main()
