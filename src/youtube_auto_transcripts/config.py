from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional


@dataclass
class CLIOptions:
    urls: List[str]
    url_file: Optional[Path]
    read_stdin: bool
    output_dir: Path
    comment_limit: int
    fallback_whisper: bool
    whisper_model: str
    lang_priority: List[str]
    parakeet_model: str
    retries: int = 3


@dataclass
class TranscriptResult:
    text: Optional[str]
    source: str
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


@dataclass
class VideoProcessingResult:
    url: str
    video_id: Optional[str]
    metadata: Optional[dict]
    transcript: TranscriptResult
    comments: List[dict]
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    log_messages: List[str] = field(default_factory=list)
    temp_files: List[Path] = field(default_factory=list)

    def as_json_serializable(self) -> dict:
        return {
            "url": self.url,
            "video_id": self.video_id,
            "metadata": self.metadata,
            "transcript": {
                "text": self.transcript.text,
                "source": self.transcript.source,
                "warnings": self.transcript.warnings,
                "errors": self.transcript.errors,
            },
            "comments": self.comments,
            "warnings": self.warnings,
            "errors": self.errors,
            "logs": self.log_messages,
        }


@dataclass
class RunContext:
    options: CLIOptions
    started_at: datetime
    youtube_api_key: Optional[str]

    @property
    def output_dir(self) -> Path:
        return self.options.output_dir

    @property
    def lang_priority(self) -> List[str]:
        return self.options.lang_priority

    @property
    def comment_limit(self) -> int:
        return self.options.comment_limit

    @property
    def retries(self) -> int:
        return self.options.retries


def parse_lang_priority(raw: str) -> List[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def collect_urls(argv_urls: Iterable[str], file_path: Optional[Path], read_stdin: bool) -> List[str]:
    urls: List[str] = []
    urls.extend(u.strip() for u in argv_urls if u.strip())

    if file_path:
        urls.extend(
            line.strip()
            for line in file_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )

    if read_stdin:
        import sys

        stdin_data = sys.stdin.read()
        urls.extend(
            line.strip() for line in stdin_data.splitlines() if line.strip()
        )

    # Deduplicate while preserving order
    seen = set()
    ordered_urls: List[str] = []
    for url in urls:
        if url not in seen:
            ordered_urls.append(url)
            seen.add(url)

    return ordered_urls
