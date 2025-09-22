from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional
from urllib.parse import parse_qs, urlparse

import requests
from youtube_transcript_api import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
)

from .config import RunContext, TranscriptResult, VideoProcessingResult


class ProcessingError(Exception):
    """Raised for errors that should be surfaced to the log but not crash the run."""


def build_ytdlp_base_args(context: RunContext) -> List[str]:
    args = ["yt-dlp"]
    if context.cookies_from_browser:
        args.extend(["--cookies-from-browser", context.cookies_from_browser])
    if context.cookies_file:
        args.extend(["--cookies", str(context.cookies_file)])
    return args


def process_videos(context: RunContext, urls: Iterable[str]) -> List[VideoProcessingResult]:
    results: List[VideoProcessingResult] = []
    for index, url in enumerate(urls, start=1):
        result = process_single_video(context, url, index)
        results.append(result)
    return results


def process_single_video(context: RunContext, url: str, index: int) -> VideoProcessingResult:
    log_messages: List[str] = []
    warnings: List[str] = []
    errors: List[str] = []

    metadata: Optional[dict] = None
    video_id: Optional[str] = None

    safe_url = url.strip()

    try:
        metadata = fetch_metadata(safe_url, context, log_messages)
        if metadata:
            video_id = metadata.get("id")
    except ProcessingError as exc:
        errors.append(str(exc))
        log_messages.append(f"[ERROR] metadata: {exc}")

    if not video_id:
        inferred_id = infer_video_id(safe_url)
        if inferred_id:
            video_id = inferred_id
            log_messages.append(
                f"[INFO] metadata: video_id inferred from URL as '{video_id}'"
            )
        else:
            errors.append("Unable to determine video ID")
            log_messages.append(
                "[ERROR] metadata: Unable to determine video ID; skipping transcript/comment retrieval"
            )

    transcript_result = TranscriptResult(text=None, source="none")

    if video_id:
        transcript_result = attempt_caption_transcript(
            video_id=video_id,
            lang_order=context.lang_priority,
            retries=context.retries,
            log_messages=log_messages,
        )

    temp_dir = Path(tempfile.mkdtemp(prefix="yat_"))
    temp_paths: List[Path] = []

    if not transcript_result.text:
        asr_result, temp_paths = attempt_offline_transcript(
            url=safe_url,
            context=context,
            temp_dir=temp_dir,
            log_messages=log_messages,
        )
        if asr_result.text:
            transcript_result = asr_result
        else:
            transcript_result.errors.extend(asr_result.errors)
            transcript_result.warnings.extend(asr_result.warnings)

    keep_temp_artifacts = context.debug and not transcript_result.text
    if not keep_temp_artifacts:
        cleanup_temp_artifacts(temp_paths, temp_dir, log_messages)
    else:
        log_messages.append(
            f"[INFO] cleanup: keeping temporary artifacts in {temp_dir} for inspection"
        )

    comments: List[dict] = []
    if context.comment_limit > 0 and video_id:
        comments = fetch_comments(
            video_id=video_id,
            api_key=context.youtube_api_key,
            limit=context.comment_limit,
            retries=context.retries,
            log_messages=log_messages,
        )

    combined_warnings = warnings + transcript_result.warnings
    combined_errors = errors + transcript_result.errors

    return VideoProcessingResult(
        url=safe_url,
        video_id=video_id,
        metadata=metadata,
        transcript=transcript_result,
        comments=comments,
        warnings=combined_warnings,
        errors=combined_errors,
        log_messages=log_messages,
        temp_files=temp_paths if keep_temp_artifacts else [],
    )


def fetch_metadata(url: str, context: RunContext, log_messages: List[str]) -> Optional[dict]:
    cmd = build_ytdlp_base_args(context) + ["-J", url]

    last_error: Optional[str] = None
    for attempt in range(1, context.retries + 1):
        try:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise ProcessingError(
                "yt-dlp is not installed or not found in PATH"
            ) from exc

        if result.returncode == 0:
            try:
                raw = json.loads(result.stdout)
            except json.JSONDecodeError as exc:
                last_error = f"yt-dlp returned invalid JSON: {exc}"
                log_messages.append(f"[WARN] metadata attempt {attempt}: {last_error}")
                continue
            metadata = sanitize_metadata(raw)
            log_messages.append("[INFO] metadata: retrieved via yt-dlp")
            return metadata

        last_error = result.stderr.strip() or "Unknown error from yt-dlp"
        log_messages.append(
            f"[WARN] metadata attempt {attempt} failed: {last_error}"
        )

    if last_error:
        raise ProcessingError(f"Failed to fetch metadata: {last_error}")
    return None


def sanitize_metadata(info: dict) -> dict:
    fields = [
        "id",
        "title",
        "uploader",
        "uploader_id",
        "uploader_url",
        "channel",
        "channel_id",
        "channel_url",
        "upload_date",
        "duration",
        "duration_string",
        "view_count",
        "like_count",
        "comment_count",
        "age_limit",
        "live_status",
        "release_timestamp",
        "categories",
        "tags",
        "description",
        "webpage_url",
        "thumbnail",
        "thumbnails",
    ]
    sanitized = {key: info.get(key) for key in fields if key in info}
    return sanitized


def infer_video_id(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if parsed.hostname in {"youtu.be"}:
        return parsed.path.lstrip("/") or None
    if parsed.hostname and parsed.hostname.endswith("youtube.com"):
        query = parse_qs(parsed.query)
        if "v" in query:
            return query["v"][0]
        if parsed.path.startswith("/shorts/"):
            return parsed.path.split("/", 2)[2] if len(parsed.path.split("/")) > 2 else None
        parts = parsed.path.split("/")
        if "embed" in parts and len(parts) > parts.index("embed") + 1:
            return parts[parts.index("embed") + 1]
    return None


def attempt_caption_transcript(
    video_id: str,
    lang_order: List[str],
    retries: int,
    log_messages: List[str],
) -> TranscriptResult:
    warnings: List[str] = []
    errors: List[str] = []

    for attempt in range(1, retries + 1):
        try:
            transcript = YouTubeTranscriptApi.get_transcript(
                video_id, languages=lang_order
            )
            pieces = [segment["text"].strip() for segment in transcript if segment["text"].strip()]
            text = "\n".join(pieces)
            log_messages.append("[INFO] transcript: retrieved existing captions")
            return TranscriptResult(
                text=text,
                source="captions",
                warnings=warnings,
                errors=errors,
            )
        except (TranscriptsDisabled, VideoUnavailable) as exc:
            message = f"captions unavailable: {exc}" if isinstance(exc, TranscriptsDisabled) else f"video unavailable: {exc}"
            warnings.append(message)
            log_messages.append(f"[WARN] transcript attempt {attempt}: {message}")
            break
        except NoTranscriptFound as exc:
            message = f"no transcript found for languages {lang_order}: {exc}"
            warnings.append(message)
            log_messages.append(f"[WARN] transcript attempt {attempt}: {message}")
        except Exception as exc:  # pylint: disable=broad-except
            message = f"caption retrieval failed: {exc}"
            errors.append(message)
            log_messages.append(f"[WARN] transcript attempt {attempt}: {message}")
    return TranscriptResult(text=None, source="none", warnings=warnings, errors=errors)


def attempt_offline_transcript(
    url: str,
    context: RunContext,
    temp_dir: Path,
    log_messages: List[str],
) -> tuple[TranscriptResult, List[Path]]:
    audio_path = download_audio(url, context, temp_dir, log_messages)
    if not audio_path:
        return (
            TranscriptResult(text=None, source="none", errors=["audio download failed"]),
            [],
        )

    wav_path = convert_audio_to_wav(audio_path, temp_dir, log_messages)
    if not wav_path:
        return (
            TranscriptResult(text=None, source="none", errors=["audio conversion failed"]),
            [audio_path],
        )

    transcript = run_parakeet(
        wav_path=wav_path,
        context=context,
        log_messages=log_messages,
    )

    temp_paths = [audio_path, wav_path]
    return transcript, temp_paths


def download_audio(
    url: str,
    context: RunContext,
    temp_dir: Path,
    log_messages: List[str],
) -> Optional[Path]:
    template = temp_dir / "%(id)s.%(ext)s"
    cmd = build_ytdlp_base_args(context) + [
        "--no-progress",
        "-f",
        "ba",
        "-o",
        str(template),
        "--print",
        "after_move:filepath",
        url,
    ]

    last_error: Optional[str] = None
    for attempt in range(1, context.retries + 1):
        try:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError:
            log_messages.append("[ERROR] audio: yt-dlp not found for download")
            return None

        if result.returncode == 0:
            path_str = result.stdout.strip().splitlines()[-1].strip()
            audio_path = Path(path_str)
            log_messages.append(f"[INFO] audio: downloaded to {audio_path}")
            return audio_path

        last_error = result.stderr.strip() or "unknown error"
        log_messages.append(
            f"[WARN] audio download attempt {attempt} failed: {last_error}"
        )

    if last_error:
        log_messages.append(f"[ERROR] audio: failed after retries: {last_error}")
    return None


def convert_audio_to_wav(audio_path: Path, temp_dir: Path, log_messages: List[str]) -> Optional[Path]:
    wav_path = temp_dir / f"{audio_path.stem}.wav"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(audio_path),
        "-ar",
        "16000",
        "-ac",
        "1",
        str(wav_path),
    ]
    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        log_messages.append("[ERROR] ffmpeg not found for conversion")
        return None

    if result.returncode != 0:
        log_messages.append(
            f"[ERROR] ffmpeg conversion failed: {result.stderr.strip() or 'unknown error'}"
        )
        return None

    log_messages.append(f"[INFO] audio: converted to {wav_path}")
    return wav_path


def run_parakeet(
    wav_path: Path,
    context: RunContext,
    log_messages: List[str],
) -> TranscriptResult:
    output_dir = wav_path.parent
    cmd = [
        "parakeet-mlx",
        str(wav_path),
        "--model",
        context.options.parakeet_model,
        "--output-format",
        "txt",
        "--output-dir",
        str(output_dir),
    ]

    try:
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        message = "parakeet-mlx CLI not found"
        log_messages.append(f"[ERROR] {message}")
        return TranscriptResult(text=None, source="parakeet", errors=[message])

    if result.returncode != 0:
        message = result.stderr.strip() or "parakeet-mlx failed"
        log_messages.append(f"[ERROR] parakeet: {message}")
        return TranscriptResult(text=None, source="parakeet", errors=[message])

    transcription_path = output_dir / f"{wav_path.stem}.txt"
    if not transcription_path.exists():
        message = f"expected transcription file {transcription_path} not found"
        log_messages.append(f"[ERROR] parakeet: {message}")
        return TranscriptResult(text=None, source="parakeet", errors=[message])

    text = transcription_path.read_text(encoding="utf-8").strip()
    if not text:
        log_messages.append("[WARN] parakeet produced empty transcript")
        return TranscriptResult(text=None, source="parakeet", warnings=["empty transcript from parakeet"])

    # Clean up Parakeet's output file; we only need the text content.
    try:
        transcription_path.unlink(missing_ok=True)
    except OSError:
        log_messages.append(
            f"[WARN] parakeet: failed to remove intermediate file {transcription_path}"
        )

    log_messages.append("[INFO] parakeet: transcription completed")
    return TranscriptResult(text=text, source="parakeet")


def cleanup_temp_artifacts(
    temp_paths: List[Path],
    temp_dir: Path,
    log_messages: List[str],
) -> None:
    for path in temp_paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            log_messages.append(f"[WARN] cleanup: failed to delete {path}")
    try:
        temp_dir.rmdir()
    except OSError:
        # Directory may already be gone or contain unexpected files; that's fine.
        pass


def fetch_comments(
    video_id: str,
    api_key: Optional[str],
    limit: int,
    retries: int,
    log_messages: List[str],
) -> List[dict]:
    if not api_key:
        log_messages.append(
            "[WARN] comments: YOUTUBE_API_KEY not set; skipping comment retrieval"
        )
        return []

    collected: List[dict] = []
    page_token: Optional[str] = None

    for attempt in range(1, retries + 1):
        params = {
            "part": "snippet",
            "videoId": video_id,
            "maxResults": min(100, limit),
            "order": "relevance",
            "textFormat": "plainText",
            "key": api_key,
        }
        if page_token:
            params["pageToken"] = page_token

        try:
            response = requests.get(
                "https://www.googleapis.com/youtube/v3/commentThreads",
                params=params,
                timeout=20,
            )
            if response.status_code != 200:
                raise ProcessingError(
                    f"HTTP {response.status_code}: {response.text.strip()[:200]}"
                )
            data = response.json()
        except (requests.RequestException, ProcessingError) as exc:
            log_messages.append(
                f"[WARN] comments attempt {attempt} failed: {exc}"
            )
            if attempt == retries:
                log_messages.append(
                    "[ERROR] comments: exhausted retries"
                )
            continue

        for item in data.get("items", []):
            if len(collected) >= limit:
                break
            snippet = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {})
            collected.append(
                {
                    "authorDisplayName": snippet.get("authorDisplayName"),
                    "likeCount": snippet.get("likeCount"),
                    "publishedAt": snippet.get("publishedAt"),
                    "textDisplay": snippet.get("textDisplay"),
                }
            )
        if len(collected) >= limit or not data.get("nextPageToken"):
            break
        page_token = data.get("nextPageToken")

    log_messages.append(
        f"[INFO] comments: collected {len(collected)} entries"
    )
    return collected[:limit]
