# Youtube Auto Transcripts

Local-first CLI for collecting YouTube metadata, transcripts, and optional top comments without relying on hosted ASR services. It prefers existing captions, falls back to locally running [Parakeet MLX](https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v3), and can optionally cascade to [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) when Parakeet fails.

## Highlights

- Fetches metadata via `yt-dlp` without downloading full video payloads.
- Reads captions with `youtube-transcript-api` when they are available.
- Downloads audio-only streams, converts to 16 kHz mono WAV, and transcribes offline with `parakeet-mlx`.
- Optional fallback to `faster-whisper` (CPU friendly) when Parakeet produces no text.
- Pulls top comments through the YouTube Data API v3 when an API key is supplied.
- Emits human readable (`.txt`), machine friendly (`.json`), and diagnostic (`.log`) files using the `DD.MM.YY_HH:MM:SS_<N>UT.*` naming convention.
- Leaves temporary artifacts in place when transcription fails so investigation is easy.

## Prerequisites

| Dependency | Purpose | Install hint |
|------------|---------|--------------|
| Python 3.10+ | Run the CLI | macOS Command Line Tools or `pyenv` |
| [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) | Metadata + audio download | `brew install yt-dlp` |
| [`ffmpeg`](https://ffmpeg.org) | Audio conversion to 16 kHz mono WAV | `brew install ffmpeg` |
| [`pipx`](https://pipx.pypa.io) | Isolated Python CLI installs (recommended) | `brew install pipx` |
| [`parakeet-mlx`](https://github.com/senstella/parakeet-mlx) | Offline ASR | `pipx install parakeet-mlx` |
| (optional) [`huggingface_hub` CLI](https://huggingface.co/docs/huggingface_hub) | Pre-fetch Parakeet weights | `pipx install "huggingface_hub[cli]"` |
| (optional) [`faster-whisper`](https://github.com/SYSTRAN/faster-whisper) | Fallback ASR | `pipx install "youtube-auto-transcripts[whisper]"` |

Additional preparation:

1. Run `pipx ensurepath` once so `~/.local/bin` is on your `PATH` (new shell required).
2. Export a YouTube Data API v3 key and keep it secret:
   ```bash
   export YOUTUBE_API_KEY="<your key>"
   ```
   The CLI refuses to fetch comments when the key is missing.
3. (Optional) Warm up the Parakeet model cache to avoid first-run downloads:
   ```bash
   export HF_HUB_ENABLE_HF_TRANSFER=1
   huggingface-cli download mlx-community/parakeet-tdt-0.6b-v3
   ```
4. Verify Parakeet is functional offline (after the model downloads):
   ```bash
   say -v Milena -o /tmp/test.aiff "Это тестовое предложение."
   ffmpeg -y -i /tmp/test.aiff -ar 16000 -ac 1 /tmp/test.wav
   parakeet-mlx /tmp/test.wav --model mlx-community/parakeet-tdt-0.6b-v3 --output-format txt
   ```

## Installation

Clone the repository and install locally (editable install keeps the entry point updated):

```bash
git clone git@github.com:Lemelson/Youtube-Auto-Transcripts.git
cd Youtube-Auto-Transcripts
pipx install .  # or: python3 -m pip install --user -e .
```

The project defines a console script `youtube-auto-transcripts` exposed by the install step. To run without installing, supply `PYTHONPATH=src` as demonstrated below.

## Usage

```bash
youtube-auto-transcripts [OPTIONS] [URL ...]
```

Key options:

- `--file links.txt` – append URLs from a file (one per line).
- `--stdin` – append URLs streamed through standard input.
- `--outdir /path/to/output` – override the default output directory (`~/Desktop`).
- `--comments 5` – request the top five comments (requires `YOUTUBE_API_KEY`).
- `--fallback-whisper` – enable fallback to `faster-whisper` if Parakeet returns no text.
- `--whisper-model medium` – select the fallback model (defaults to `small`).
- `--lang-priority ru,en` – caption language preference order.
- `--parakeet-model mlx-community/parakeet-tdt-0.6b-v3` – override the HF repository.
- `--retries 5` – change retry count for network-bound operations.

### Example

Process URLs from a file, capture five comments, and enable the fallback model:

```bash
export YOUTUBE_API_KEY="<your key>"
youtube-auto-transcripts --file links.txt --comments 5 --fallback-whisper --lang-priority ru,en
```

Running without installation for quick tests:

```bash
PYTHONPATH=src youtube-auto-transcripts --stdin --comments 0 <<'EOF'
https://www.youtube.com/watch?v=dQw4w9WgXcQ
EOF
```

## Output layout

Each run produces three sibling files sharing the same base name:

```
DD.MM.YY_HH:MM:SS_<N>UT.txt  # human readable summary per video
DD.MM.YY_HH:MM:SS_<N>UT.json # structured data (metadata, transcript, logs)
DD.MM.YY_HH:MM:SS_<N>UT.log  # full warning/error log
```

- Timestamp reflects the run start, `N` equals the number of processed URLs.
- The `.txt` file groups sections like:
  ```
  URL: ...
  ID: ...
  Channel: ...
  Title: ...
  Uploaded: 2024-07-01
  DurationSec: 1234
  Description:
  <first 2000 characters>

  Transcript:
  <plain text or NO_TRANSCRIPT>

  TopComments:
  - <author> | <likes> | <publishedAt>
    <text>
  ---
  ```
- The `.json` payload is ready for downstream tooling and contains sanitized metadata, transcript provenance (`captions`, `parakeet`, or `faster-whisper`), collected comments, warnings, and raw log entries.
- The `.log` file collates step-by-step status lines, easing troubleshooting for rate limits, missing captions, or runtime failures.

Temporary audio artifacts are only deleted when transcription succeeds; otherwise the CLI leaves them intact and records the temp directory path in the log for manual inspection.

## Error handling & retries

- Network-bound actions (metadata, caption fetch, comments) retry up to `--retries` times (default 3).
- Missing captions, private videos, or region locks are recorded as warnings with the reason.
- When `parakeet-mlx` or `ffmpeg` is unavailable, the CLI reports an actionable error and continues to the next URL.
- Comment retrieval silently skips when `YOUTUBE_API_KEY` is unset.

## Development notes

- Source code lives under `src/youtube_auto_transcripts/` and follows a straightforward modular split (CLI, configuration helpers, processing pipeline, output writers).
- Run `python3 -m compileall src` or your preferred formatter/linter before committing.
- Sample smoke test:
  ```bash
  PYTHONPATH=src YOUTUBE_API_KEY="<key>" python3 -m youtube_auto_transcripts.cli \
  https://www.youtube.com/watch?v=dQw4w9WgXcQ --comments 1
  ```

Contributions and issue reports are welcome—please document observed failures in the generated `.log` file to accelerate triage.

## Readiness checklist

- [ ] `yt-dlp` reachable on `PATH`.
- [ ] `ffmpeg` reachable on `PATH`.
- [ ] `parakeet-mlx --help` works and the `mlx-community/parakeet-tdt-0.6b-v3` weights are cached.
- [ ] `YOUTUBE_API_KEY` exported for comment retrieval.
- [ ] `links.txt` (or another URL source) prepared.
- [ ] ≥6 GB free disk space for HF cache plus temporary audio artefacts.

