from __future__ import annotations

import argparse
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import List

from .config import (
    CLIOptions,
    RunContext,
    collect_urls,
    parse_lang_priority,
)
from .processor import process_videos
from .writer import write_outputs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="youtube-auto-transcripts",
        description="Download YouTube metadata, transcripts, comments, and offline ASR transcripts.",
    )
    parser.add_argument(
        "urls",
        nargs="*",
        help="YouTube video URLs to process",
    )
    parser.add_argument(
        "--file",
        dest="url_file",
        type=Path,
        help="Path to a file containing YouTube URLs (one per line)",
    )
    parser.add_argument(
        "--stdin",
        dest="read_stdin",
        action="store_true",
        help="Also read YouTube URLs from standard input",
    )
    parser.add_argument(
        "--outdir",
        type=Path,
        default=Path.home() / "Desktop",
        help="Directory to store output files (default: ~/Desktop)",
    )
    parser.add_argument(
        "--comments",
        dest="comment_limit",
        type=int,
        default=None,
        help="Number of top comments to fetch (default: 20 when YOUTUBE_API_KEY is set, otherwise 0)",
    )
    parser.add_argument(
        "--debug",
        dest="debug",
        action="store_true",
        help="Keep auxiliary artifacts (.json, .log) and temporary audio on failure",
    )
    parser.add_argument(
        "--cookies-from-browser",
        dest="cookies_from_browser",
        help="Forward credentials to yt-dlp via --cookies-from-browser (e.g. safari,chrome)",
    )
    parser.add_argument(
        "--cookies",
        dest="cookies_file",
        type=Path,
        help="Path to a cookies.txt file to pass to yt-dlp",
    )
    parser.add_argument(
        "--lang-priority",
        dest="lang_priority",
        default="ru,en",
        help="Comma-separated list of language codes to request transcripts (default: ru,en)",
    )
    parser.add_argument(
        "--parakeet-model",
        dest="parakeet_model",
        default="mlx-community/parakeet-tdt-0.6b-v3",
        help="Hugging Face repo ID for the Parakeet MLX model",
    )
    parser.add_argument(
        "--retries",
        dest="retries",
        type=int,
        default=3,
        help="Number of retries for transient network operations",
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.comment_limit is not None and args.comment_limit < 0:
        raise SystemExit("--comments must be zero or a positive integer")
    if args.retries < 1:
        raise SystemExit("--retries must be >= 1")
    if args.cookies_file and not args.cookies_file.exists():
        raise SystemExit(f"--cookies file not found: {args.cookies_file}")


def build_options(args: argparse.Namespace) -> CLIOptions:
    urls = collect_urls(args.urls, args.url_file, args.read_stdin)
    if not urls:
        raise SystemExit("No video URLs provided. Pass URLs, --file, or --stdin.")

    output_dir = args.outdir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    comment_limit = args.comment_limit
    if comment_limit is None:
        comment_limit = 20 if os.environ.get("YOUTUBE_API_KEY") else 0

    return CLIOptions(
        urls=list(urls),
        url_file=args.url_file,
        read_stdin=args.read_stdin,
        output_dir=output_dir,
        comment_limit=comment_limit,
        lang_priority=parse_lang_priority(args.lang_priority),
        parakeet_model=args.parakeet_model,
        debug=args.debug,
        cookies_from_browser=args.cookies_from_browser,
        cookies_file=args.cookies_file,
        retries=args.retries,
    )


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(args)

    options = build_options(args)
    context = RunContext(
        options=options,
        started_at=datetime.now(),
        youtube_api_key=os.environ.get("YOUTUBE_API_KEY"),
    )

    print_preflight_summary(context)

    results = process_videos(context, options.urls)
    artifacts = write_outputs(context, results)

    print(f"Processed {len(results)} videos.")
    print(f"Artifacts:")
    for path in artifacts.all_paths:
        print(f" - {path}")

    return 0


def print_preflight_summary(context: RunContext) -> None:
    dependencies = {
        "yt-dlp": shutil.which("yt-dlp"),
        "ffmpeg": shutil.which("ffmpeg"),
        "parakeet-mlx": shutil.which("parakeet-mlx"),
    }
    print("Pre-flight checks:")
    for name, path in dependencies.items():
        status = "OK" if path else "MISSING"
        detail = path or "not found in PATH"
        print(f" - {name}: {status} ({detail})")

    comment_info = (
        f"defaulting to {context.comment_limit} comments"
        if context.comment_limit > 0
        else "comments disabled"
    )
    comment_reason = (
        "YOUTUBE_API_KEY detected"
        if context.comment_limit > 0
        else "no YOUTUBE_API_KEY"
    )
    print(f" - comments: {comment_info} ({comment_reason})")
    if context.cookies_from_browser:
        print(
            f" - yt-dlp cookies: from browser '{context.cookies_from_browser}'"
        )
    if context.cookies_file:
        print(f" - yt-dlp cookies: file {context.cookies_file}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

