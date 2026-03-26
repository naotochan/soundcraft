import argparse
from pathlib import Path

from soundcraft.config import DEFAULT_DURATION, DEFAULT_MODEL, DEFAULT_OUTPUT_DIR, MODELS
from soundcraft.generate import generate_music
from soundcraft.prompt import refine_prompt


def main():
    parser = argparse.ArgumentParser(
        description="Generate instrumental music with MusicGen via Replicate API",
    )
    parser.add_argument("prompt", help="Text prompt or keywords for music generation")
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
    args = parser.parse_args()

    if args.raw:
        prompt = args.prompt
    else:
        print(f"Input: {args.prompt}")
        print("Refining prompt via LLM...")
        prompt = refine_prompt(args.prompt)
        print(f"Prompt: {prompt}\n")

    print(f"Model: musicgen-{args.model}")
    print(f"Duration: {args.duration}s")
    print(f"Generating {args.count} variation(s)...\n")

    for i in range(args.count):
        if args.count > 1:
            print(f"[{i + 1}/{args.count}] Generating...")
        else:
            print("Generating...")

        path = generate_music(
            prompt=prompt,
            model_version=args.model,
            duration=args.duration,
            output_dir=args.output,
        )
        print(f"  Saved: {path}")

    print("\nDone!")


if __name__ == "__main__":
    main()
