"""Command line interface.

Backend-specific flags are not hardcoded: `--param name=value` accepts anything
the chosen provider declares, and `soundcraft providers` prints what is
available. `-d`/`-m` remain as shorthands for the two most common parameters.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, NoReturn

from soundcraft.config import (
    APP_VERSION,
    DEFAULT_COUNT,
    DEFAULT_SERVER_HOST,
    DEFAULT_SERVER_PORT,
    default_output_dir,
)

#: CLI flags that map straight onto a parameter of the same name, when the
#: chosen provider declares one.
SHORTHAND_PARAMS = ("duration", "model")

#: Matches the HTTP API's limit, so the same request fails the same way.
MAX_COUNT = 10


def _count(raw: str) -> int:
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected a number, got {raw!r}") from None
    if not 1 <= value <= MAX_COUNT:
        raise argparse.ArgumentTypeError(f"count must be between 1 and {MAX_COUNT}")
    return value


def _parse_params(pairs: list[str] | None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep:
            raise SystemExit(f"--param expects name=value, got {pair!r}")
        params[key.strip()] = value.strip()
    return params


def _fail(message: str) -> NoReturn:
    print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


# -- generate -----------------------------------------------------------------


def cmd_generate(args: argparse.Namespace) -> None:
    from soundcraft.pipeline import run_generate
    from soundcraft.prompt import refine_prompt, refiner_available
    from soundcraft.providers import registry
    from soundcraft.providers.base import ProviderError

    backend = args.backend or registry.default_id()
    if not backend:
        _fail("No generation backends are available.")

    try:
        provider = registry.get(backend)
    except ProviderError as e:
        _fail(str(e))

    status = provider.availability()
    if not status.ready:
        _fail(f"{provider.label} is not ready. {status.reason} {status.fix}".strip())

    params = _parse_params(args.param)
    for name in SHORTHAND_PARAMS:
        value = getattr(args, name, None)
        if value is not None and provider.param(name) is not None:
            params.setdefault(name, value)

    if args.raw:
        prompt = args.prompt
    else:
        if refiner_available():
            print(f"Input:   {args.prompt}")
            print("Refining prompt…")
        prompt = refine_prompt(args.prompt)
        if prompt != args.prompt:
            print(f"Prompt:  {prompt}")

    print(f"Backend: {provider.label}")
    print(f"Making {args.count} variation(s)…\n")

    def on_progress(done: int, total: int, path: Path) -> None:
        prefix = f"[{done}/{total}] " if total > 1 else ""
        print(f"{prefix}Saved: {path}")

    try:
        run_generate(
            prompt,
            backend=backend,
            params=params,
            count=args.count,
            output_dir=args.output or default_output_dir(),
            raw=True,  # Already refined above.
            progress=on_progress,
        )
    except (ProviderError, ValueError) as e:
        _fail(str(e))
    except KeyboardInterrupt:
        print("\nCancelled.", file=sys.stderr)
        raise SystemExit(130) from None

    print("\nDone.")


# -- introspection ------------------------------------------------------------


def cmd_providers(args: argparse.Namespace) -> None:
    from soundcraft.providers import registry

    for provider in registry.all_providers():
        status = provider.availability()
        mark = "ready" if status.ready else "not ready"
        print(f"{provider.id:<12} {provider.label:<20} [{mark}]")
        print(f"{'':<12} {provider.summary}")
        if not status.ready:
            print(f"{'':<12} → {status.reason} {status.fix}".rstrip())
        if args.verbose and provider.params:
            for spec in provider.params:
                bits = [spec.type]
                if spec.default is not None:
                    bits.append(f"default={spec.default}")
                if spec.options:
                    bits.append("|".join(o.value for o in spec.options))
                print(f"{'':<12}   --param {spec.name}=…  ({', '.join(bits)})")
        print()


def cmd_doctor(args: argparse.Namespace) -> None:
    """Check that this install can actually generate something."""
    from soundcraft import settings
    from soundcraft.config import is_app_mode
    from soundcraft.paths import app_env_path, workflows_dir
    from soundcraft.prompt import refiner_available
    from soundcraft.providers import registry

    out = default_output_dir().expanduser().resolve()
    print(f"soundcraft {APP_VERSION}")
    print(f"  Python        {sys.version.split()[0]}")
    print(f"  App mode      {is_app_mode()}")
    print(f"  Settings file {app_env_path()}")
    print(f"  Output dir    {out}")
    print(f"  Workflows     {workflows_dir()}")
    print(f"  Prompt refine {'enabled' if refiner_available() else 'off (raw prompts)'}")
    auth = "on" if settings.is_set("SOUNDCRAFT_API_TOKEN") else "off (localhost only)"
    print(f"  API auth      {auth}")

    try:
        out.mkdir(parents=True, exist_ok=True)
        probe = out / ".soundcraft-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        print("  Output dir    writable")
    except OSError as e:
        print(f"  Output dir    NOT WRITABLE — {e}")

    print("\nBackends:")
    ready = []
    for provider in registry.all_providers():
        status = provider.availability()
        if status.ready:
            ready.append(provider.id)
            print(f"  ✓ {provider.id:<12} {provider.label}")
        else:
            print(f"  ✗ {provider.id:<12} {status.reason} {status.fix}".rstrip())

    if ready:
        print(f"\nReady to generate with: {', '.join(ready)}")
    else:
        print("\nNo backend is configured yet.")
        print("Run `soundcraft config set …`, or open Settings in the GUI.")
        raise SystemExit(1)


def cmd_config(args: argparse.Namespace) -> None:
    from soundcraft import settings

    if args.action == "list":
        public = settings.read_public()
        for spec in settings.all_specs():
            entry = public["values"][spec.key]
            if spec.secret:
                shown = entry.get("masked") or "(not set)"
            else:
                shown = entry.get("value") or "(empty)"
            print(f"{spec.key:<26} {shown}")
            if args.verbose and spec.help:
                print(f"{'':<26} {spec.help}")
        return

    if args.action == "get":
        if not args.name:
            _fail("config get needs a setting name")
        spec = settings.spec_for(args.name)
        if spec is None:
            _fail(f"Unknown setting: {args.name}")
        value = settings.get(args.name)
        print(settings.mask(value) if spec.secret else value)
        return

    # set
    if not args.name or args.value is None:
        _fail("config set needs NAME VALUE")
    try:
        settings.save({args.name: args.value})
    except ValueError as e:
        _fail(str(e))
    print(f"Saved {args.name}")


# -- servers ------------------------------------------------------------------


def cmd_serve(args: argparse.Namespace) -> None:
    from soundcraft.server import run_server

    run_server(host=args.host, port=args.port, open_browser=False)


def cmd_gui(args: argparse.Namespace) -> None:
    from soundcraft.server import run_server

    run_server(host=args.host, port=args.port, open_browser=not args.no_browser)


def cmd_app(args: argparse.Namespace) -> None:
    from soundcraft.app import run_desktop_app

    run_desktop_app(host=args.host, port=args.port)


# -- parser -------------------------------------------------------------------


def _add_server_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default=DEFAULT_SERVER_HOST, help="Bind address")
    parser.add_argument("--port", type=int, default=DEFAULT_SERVER_PORT, help="Port")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="soundcraft",
        description="Generate music from text with pluggable backends",
    )
    parser.add_argument("--version", action="version", version=f"soundcraft {APP_VERSION}")
    sub = parser.add_subparsers(dest="command")

    gen = sub.add_parser("generate", help="Generate audio from a text prompt")
    gen.add_argument("prompt", help="Text prompt or keywords")
    gen.add_argument("-b", "--backend", help="Backend id (see `soundcraft providers`)")
    gen.add_argument(
        "-p", "--param", action="append", metavar="NAME=VALUE",
        help="Backend parameter; repeatable",
    )
    gen.add_argument("-d", "--duration", type=int, help="Shorthand for --param duration=…")
    gen.add_argument("-m", "--model", help="Shorthand for --param model=…")
    gen.add_argument(
        "-n", "--count", type=_count, default=DEFAULT_COUNT,
        help=f"Variations (1-{MAX_COUNT})",
    )
    gen.add_argument("-o", "--output", type=Path, help="Output directory")
    gen.add_argument("--raw", action="store_true", help="Skip LLM prompt refinement")
    gen.set_defaults(func=cmd_generate)

    providers = sub.add_parser("providers", help="List backends and their readiness")
    providers.add_argument("-v", "--verbose", action="store_true", help="Show parameters")
    providers.set_defaults(func=cmd_providers)

    doctor = sub.add_parser("doctor", help="Check this install for problems")
    doctor.set_defaults(func=cmd_doctor)

    config = sub.add_parser("config", help="Read and write saved settings")
    config.add_argument("action", choices=("list", "get", "set"))
    config.add_argument("name", nargs="?")
    config.add_argument("value", nargs="?")
    config.add_argument("-v", "--verbose", action="store_true")
    config.set_defaults(func=cmd_config)

    serve = sub.add_parser("serve", help="Start the HTTP API (no browser)")
    _add_server_args(serve)
    serve.set_defaults(func=cmd_serve)

    gui = sub.add_parser("gui", help="Start the server and open the browser GUI")
    _add_server_args(gui)
    gui.add_argument("--no-browser", action="store_true", help="Do not open a browser")
    gui.set_defaults(func=cmd_gui)

    desktop = sub.add_parser("app", help="Open the desktop window")
    _add_server_args(desktop)
    desktop.set_defaults(func=cmd_app)

    return parser


KNOWN_COMMANDS = {
    "generate", "providers", "doctor", "config", "serve", "gui", "app",
    "-h", "--help", "--version",
}


def main(argv: list[str] | None = None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)

    # Backward compatible: `soundcraft "prompt" …` still means generate.
    if argv and argv[0] not in KNOWN_COMMANDS:
        argv = ["generate", *argv]

    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        raise SystemExit(1)
    args.func(args)


if __name__ == "__main__":
    main()
