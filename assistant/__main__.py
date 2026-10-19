"""Command line: `python -m assistant console | demo | web`."""

from __future__ import annotations

import argparse

from .adapters.console import DEMO_FOLDER, run_console, run_demo


def main() -> None:
    parser = argparse.ArgumentParser(prog="assistant", description="AI chat assistant for a business.")
    sub = parser.add_subparsers(dest="command", required=True)
    commands = [
        ("console", "chat in the terminal"),
        ("demo", "run a scripted conversation"),
        ("web", "serve the website chat window and the demo page"),
    ]
    for name, help_text in commands:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--business", default=DEMO_FOLDER, help="folder with business.json and knowledge/")
        if name == "web":
            p.add_argument("--host", default="127.0.0.1")
            p.add_argument("--port", type=int, default=8000)
            p.add_argument("--origins", default="", help="comma-separated websites allowed to embed the widget")
    args = parser.parse_args()
    if args.command == "console":
        run_console(args.business)
    elif args.command == "demo":
        run_demo(args.business)
    else:
        run_web(args.business, args.host, args.port, [o.strip() for o in args.origins.split(",") if o.strip()])


def run_web(folder: str, host: str, port: int, origins: list[str]) -> None:
    # Imported here so the console and the tests of the core run without web dependencies.
    import uvicorn

    from .adapters.console import build
    from .adapters.web import create_app

    assistant, _, _ = build(folder)
    print(f"Demo page: http://{host}:{port}/  (MOCK model, no API key needed)")
    uvicorn.run(create_app(assistant, allowed_origins=origins), host=host, port=port, log_level="warning")


if __name__ == "__main__":
    main()
