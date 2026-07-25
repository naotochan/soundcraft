import argparse
import sys
from pathlib import Path

from soundcraft.config import (
    BACKENDS,
    DEFAULT_BACKEND,
    DEFAULT_DURATION,
    DEFAULT_MODEL,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    MODELS,
)
from soundcraft.pipeline import run_generate


def _build_generate_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("prompt", help="Text prompt or keywords for music generation")
    parser.add_argument(
        "-b", "--backend",
        choices=BACKENDS,
        default=DEFAULT_BACKEND,
        help=f"Generation backend (default: {DEFAULT_BACKEND})",
    )
    parser.add_argument(
        "-m", "--model",
        choices=MODELS,
        default=DEFAULT_MODEL,
        help=f"Model version (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "-d", "--duration",
        type=int,
        default=DEFAULT_DURATION,
        help=f"Duration in seconds (default: {DEFAULT_DURATION})",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "-n", "--count",
        type=int,
        default=3,
        help="Number of variations to generate (default: 3)",
    )
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Skip LLM prompt refinement, use input as-is",
    )


def cmd_generate(args: argparse.Namespace) -> None:
    from soundcraft.prompt import refine_prompt

    if args.raw:
        prompt = args.prompt
    else:
        print(f"Input: {args.prompt}")
        print("Refining prompt via LLM...")
        prompt = refine_prompt(args.prompt)
        print(f"Prompt: {prompt}\n")

    if args.backend == "lyria3":
        if args.model != DEFAULT_MODEL:
            print("Warning: --model is ignored with lyria3 backend.")
        if args.duration != DEFAULT_DURATION:
            print("Warning: --duration is ignored with lyria3 backend (fixed 30s clip).")
        print("Backend: Lyria3 (lyria-3-clip-preview)")
    else:
        print(f"Backend: MusicGen ({args.model})")
        print(f"Duration: {args.duration}s")

    print(f"Generating {args.count} variation(s)...\n")

    result = run_generate(
        prompt,
        backend=args.backend,
        model=args.model,
        duration=args.duration,
        count=args.count,
        output_dir=args.output,
        raw=True,
    )

    for i, path in enumerate(result.files):
        if args.count > 1:
            print(f"[{i + 1}/{args.count}] Saved: {path}")
        else:
            print(f"Saved: {path}")

    print("\nDone!")


def cmd_serve(args: argparse.Namespace) -> None:
    from soundcraft.server import run_server

    run_server(host=args.host, port=args.port, open_browser=False)


def cmd_gui(args: argparse.Namespace) -> None:
    from soundcraft.server import run_server

    run_server(host=args.host, port=args.port, open_browser=not args.no_browser)


def _add_server_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--host",
        default=DEFAULT_SERVER_HOST,
        help=f"Bind address (default: {DEFAULT_SERVER_HOST})",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_SERVER_PORT,
        help=f"Port (default: {DEFAULT_SERVER_PORT})",
    )


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(
        prog="soundcraft",
        description="Generate instrumental music via MusicGen / Lyria3",
    )
    sub = parser.add_subparsers(dest="command")

    gen_parser = sub.add_parser("generate", help="Generate audio from a text prompt")
    _build_generate_parser(gen_parser)
    gen_parser.set_defaults(func=cmd_generate)

    serve_parser = sub.add_parser(
        "serve",
        help="Start local HTTP API + GUI (for TouchDesigner and other tools)",
    )
    _add_server_args(serve_parser)
    serve_parser.set_defaults(func=cmd_serve)

    gui_parser = sub.add_parser(
        "gui",
        help="Start local server and open the browser GUI",
    )
    _add_server_args(gui_parser)
    gui_parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open a browser window",
    )
    gui_parser.set_defaults(func=cmd_gui)

    # Backward compatible: `soundcraft "prompt" ...` → generate
    if argv and argv[0] not in ("generate", "serve", "gui", "-h", "--help"):
        argv = ["generate", *argv]

    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == "__main__":
    main()
