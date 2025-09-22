# Youtube Auto Transcripts

Local-first CLI for collecting YouTube metadata, transcripts, and optional top comments without relying on hosted ASR services. It prefers existing captions and otherwise runs [Parakeet MLX](https://huggingface.co/mlx-community/parakeet-tdt-0.6b-v3) offline, keeping only a `.txt` summary by default (extra artifacts are opt-in via `--debug`).

## Highlights

- Fetches metadata via `yt-dlp` without downloading full video payloads.
- Reads captions with `youtube-transcript-api` when they are available.
- Downloads audio-only streams, converts to 16 kHz mono WAV, and transcribes offline with `parakeet-mlx`.
- When `YOUTUBE_API_KEY` is set, automatically pulls up to 20 top comments (overridable via `--comments`).
- Writes a single human readable `.txt` report by default; add `--debug` to keep `.json` and `.log` companions.
- Cleans up temporary audio automatically unless `--debug` is used to retain artefacts for troubleshooting.
- Prints a pre-flight summary so you immediately see dependency status, comment defaults, and cookie sources.

## Prerequisites

| Dependency | Purpose | Install hint |
|------------|---------|--------------|
| Python 3.10+ | Run the CLI | macOS Command Line Tools or `pyenv` |
| [`yt-dlp`](https://github.com/yt-dlp/yt-dlp) | Metadata + audio download | `brew install yt-dlp` |
| [`ffmpeg`](https://ffmpeg.org) | Audio conversion to 16 kHz mono WAV | `brew install ffmpeg` |
| [`pipx`](https://pipx.pypa.io) | Isolated Python CLI installs (recommended) | `brew install pipx` |
| [`parakeet-mlx`](https://github.com/senstella/parakeet-mlx) | Offline ASR | `pipx install parakeet-mlx` |
| (optional) [`huggingface_hub` CLI](https://huggingface.co/docs/huggingface_hub) | Pre-fetch Parakeet weights | `pipx install "huggingface_hub[cli]"` |

Additional preparation:

1. Run `pipx ensurepath` once so `~/.local/bin` is on your `PATH` (new shell required).
2. Export a YouTube Data API v3 key and keep it secret:
   ```bash
   export YOUTUBE_API_KEY="<your key>"
   ```
   With the key present the CLI defaults to fetching up to 20 top comments; without it, comments are skipped.
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
- `--comments N` – limit the number of top comments (default 20 when `YOUTUBE_API_KEY` is set, 0 otherwise).
- `--debug` – keep `.json`/`.log` artifacts and retain temporary audio on failures.
- `--cookies-from-browser safari` – delegate auth to yt-dlp using cookies from the named browser.
- `--cookies /path/to/cookies.txt` – provide an exported cookies file for protected videos.
- `--lang-priority ru,en` – caption language preference order.
- `--parakeet-model mlx-community/parakeet-tdt-0.6b-v3` – override the HF repository.
- `--retries 5` – change retry count for network-bound operations.

### Example

Process URLs from a file, keep diagnostic artifacts, and rely on the default comment pull (20 entries when the key is set):

```bash
export YOUTUBE_API_KEY="<your key>"
youtube-auto-transcripts --file links.txt --debug --lang-priority ru,en
```

Running without installation for quick tests (no comments):

```bash
PYTHONPATH=src youtube-auto-transcripts --stdin --comments 0 <<'EOF'
https://www.youtube.com/watch?v=dQw4w9WgXcQ
EOF
```

## Handling protected videos

If yt-dlp reports `Sign in to confirm you’re not a bot`, pass credentials through one of the new cookie options. Examples:

```bash
youtube-auto-transcripts --cookies-from-browser safari 'https://www.youtube.com/watch?v=ID'
# or
youtube-auto-transcripts --cookies ~/.config/yt-dlp/cookies.txt 'https://www.youtube.com/watch?v=ID'
```

When these flags are absent the CLI makes anonymous requests, which may fail on restricted or age-gated videos.

## Output layout

Every run emits at least one file:

```
DD.MM.YY_HH:MM:SS_<N>UT.txt  # human readable summary per video
```

Add `--debug` to produce companion files:

```
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
- When present, the `.json` payload is ready for downstream tooling and contains sanitized metadata, transcript provenance (`captions` or `parakeet`), collected comments, warnings, and raw log entries.
- The optional `.log` file collates step-by-step status lines, easing troubleshooting for rate limits, missing captions, or runtime failures.

Temporary audio artefacts are deleted automatically after a successful transcription. When transcription fails they are retained only if `--debug` is enabled (the log will mention their location).

## Error handling & retries

- Network-bound actions (metadata, caption fetch, comments) retry up to `--retries` times (default 3).
- Missing captions, private videos, or region locks are recorded as warnings with the reason.
- When `parakeet-mlx` or `ffmpeg` is unavailable, the CLI reports an actionable error and continues to the next URL.
- Comment retrieval automatically drops to zero when `YOUTUBE_API_KEY` is unset.

## Development notes

- Source code lives under `src/youtube_auto_transcripts/` and follows a straightforward modular split (CLI, configuration helpers, processing pipeline, output writers).
- Run `python3 -m compileall src` or your preferred formatter/linter before committing.
- Sample smoke test:
  ```bash
  PYTHONPATH=src YOUTUBE_API_KEY="<key>" python3 -m youtube_auto_transcripts.cli \
  https://www.youtube.com/watch?v=dQw4w9WgXcQ --comments 1 --debug
  ```

Contributions and issue reports are welcome—run with `--debug` and share the resulting `.log` file when reporting issues.

## Readiness checklist

- [ ] `yt-dlp` reachable on `PATH`.
- [ ] `ffmpeg` reachable on `PATH`.
- [ ] `parakeet-mlx --help` works and the `mlx-community/parakeet-tdt-0.6b-v3` weights are cached.
- [ ] `YOUTUBE_API_KEY` exported for comment retrieval.
- [ ] `links.txt` (or another URL source) prepared.
- [ ] ≥6 GB free disk space for HF cache plus temporary audio artefacts.

