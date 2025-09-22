from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional

from .config import RunContext, VideoProcessingResult


@dataclass
class OutputArtifacts:
    text_path: Path
    json_path: Optional[Path]
    log_path: Optional[Path]

    @property
    def all_paths(self) -> List[Path]:
        paths: List[Path] = [self.text_path]
        if self.json_path:
            paths.append(self.json_path)
        if self.log_path:
            paths.append(self.log_path)
        return paths


def write_outputs(
    context: RunContext,
    results: Iterable[VideoProcessingResult],
) -> OutputArtifacts:
    results_list = list(results)
    count = len(results_list)

    base_name = build_base_name(context.started_at, count)
    text_path = context.output_dir / f"{base_name}.txt"

    text_path.write_text(render_text_report(results_list), encoding="utf-8")
    json_path: Optional[Path] = None
    log_path: Optional[Path] = None

    if context.debug:
        json_path = context.output_dir / f"{base_name}.json"
        log_path = context.output_dir / f"{base_name}.log"
        json_path.write_text(render_json_report(context, results_list), encoding="utf-8")
        log_path.write_text(render_log(results_list), encoding="utf-8")

    return OutputArtifacts(text_path=text_path, json_path=json_path, log_path=log_path)


def build_base_name(started_at: datetime, count: int) -> str:
    timestamp = started_at.strftime("%d.%m.%y_%H:%M:%S")
    return f"{timestamp}_{count}UT"


def render_text_report(results: List[VideoProcessingResult]) -> str:
    blocks: List[str] = []
    for result in results:
        metadata = result.metadata or {}
        description = metadata.get("description") or ""
        description = sanitize_description(description)
        channel = metadata.get("channel") or metadata.get("uploader") or "" 
        upload_date = metadata.get("upload_date")
        if upload_date and len(upload_date) == 8:
            upload_date = f"{upload_date[0:4]}-{upload_date[4:6]}-{upload_date[6:8]}"
        duration = metadata.get("duration")
        duration_text = str(duration) if duration is not None else "-1"

        transcript_text = result.transcript.text.strip() if result.transcript.text else "NO_TRANSCRIPT"

        block_lines = [
            f"URL: {result.url}",
            f"ID: {result.video_id or ''}",
            f"Channel: {channel}",
            f"Title: {metadata.get('title', '')}",
            f"Uploaded: {upload_date or ''}",
            f"DurationSec: {duration_text}",
            "Description:",
            description,
            "",
            "Transcript:",
            transcript_text,
            "",
            "TopComments:",
        ]

        if result.comments:
            for comment in result.comments:
                author = comment.get("authorDisplayName") or ""
                likes = comment.get("likeCount")
                published_at = comment.get("publishedAt") or ""
                text = comment.get("textDisplay") or ""
                rendered_comment = format_comment(author, likes, published_at, text)
                block_lines.extend(rendered_comment)
        else:
            block_lines.append("- none")

        block_lines.append("---")
        blocks.append("\n".join(block_lines))

    return "\n\n".join(blocks)


def sanitize_description(text: str, limit: int = 2000) -> str:
    import html
    import re

    unescaped = html.unescape(text)
    stripped = re.sub(r"<[^>]+>", "", unescaped)
    normalized = stripped.replace("\r", "")
    return normalized[:limit]


def format_comment(author: str, likes: int | None, published_at: str, text: str) -> List[str]:
    first_line = f"- {author} | {likes if likes is not None else 0} | {published_at}"
    wrapped_text = indent_multiline(text.strip() or "(no text)")
    return [first_line, wrapped_text]


def indent_multiline(text: str) -> str:
    lines = text.splitlines() or [""]
    indented = [f"  {line}" if line else "  " for line in lines]
    return "\n".join(indented)


def render_json_report(context: RunContext, results: List[VideoProcessingResult]) -> str:
    payload = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "video_count": len(results),
        "options": {
            "comment_limit": context.comment_limit,
            "debug": context.debug,
            "lang_priority": context.lang_priority,
            "parakeet_model": context.options.parakeet_model,
        },
        "results": [result.as_json_serializable() for result in results],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def render_log(results: List[VideoProcessingResult]) -> str:
    lines: List[str] = []
    for result in results:
        video_label = result.video_id or result.url
        for message in result.log_messages:
            lines.append(f"{video_label}: {message}")
        for warning in result.warnings:
            lines.append(f"{video_label}: [WARNING] {warning}")
        for error in result.errors:
            lines.append(f"{video_label}: [ERROR] {error}")
    return "\n".join(lines)
