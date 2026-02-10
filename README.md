# MMAE - Music/Media Audio Editor

A web-based audio editor for downloading, visualizing, and clipping audio from YouTube or local files.

## Features

- Download audio from YouTube URLs via yt-dlp
- Upload local audio files (mp3, wav, flac, ogg, m4a, aac, wma, opus, webm)
- Multi-track support
- Spectrogram visualization (STFT + viridis colormap)
- Zoom & pan, click-to-seek, play/pause with playhead
- Multi-region selection with drag handles
- Export selected regions as WAV clips, uploaded to Cloudflare R2

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- [ffmpeg](https://ffmpeg.org/) installed and available in PATH

## Quick Start

```bash
uv sync
uv run python main.py
```

Open http://localhost:8000

## Environment Variables

| Variable | Description |
|---|---|
| `MMAE_PROXY` | HTTP proxy for yt-dlp |
| `R2_ENDPOINT_URL` | S3-compatible endpoint, e.g. `https://<account_id>.r2.cloudflarestorage.com` |
| `R2_ACCESS_KEY_ID` | R2 access key ID |
| `R2_SECRET_ACCESS_KEY` | R2 secret access key |
| `R2_BUCKET_NAME` | R2 bucket name |
| `R2_PUBLIC_URL` | Bucket public access domain, e.g. `https://r2.example.com` |

## Usage

1. Paste YouTube URL(s) or upload local audio files
2. Click **Process All** to download/upload and load tracks
3. Browse the spectrogram — scroll to zoom, click to seek
4. Click **+ Add Region** to mark clips, drag edges to adjust
5. Click **Clip All** to export all selected regions (uploaded to R2, returns URLs)

## Project Structure

```
MMAE/
├── pyproject.toml      # Dependencies
├── main.py             # FastAPI backend
├── static/
│   └── index.html      # Frontend (single-page app)
└── downloads/          # Temporary audio files (auto-cleaned)
```

## API

| Endpoint | Method | Description |
|---|---|---|
| `/` | GET | Serve frontend |
| `/api/download` | POST | Download audio from URL |
| `/api/upload` | POST | Upload local audio files |
| `/api/audio/{file_id}` | GET | Serve WAV file |
| `/api/clip` | POST | Clip regions, upload to R2, return URLs |
| `/api/clip-multi` | POST | Clip regions from multiple tracks, upload to R2, return URLs |
