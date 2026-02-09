# MMAE - Music/Media Audio Editor

A web-based audio editor for downloading, visualizing, and clipping audio from YouTube.

## Features

- Download audio from YouTube URLs via yt-dlp
- Spectrogram visualization (STFT + viridis colormap)
- Zoom & pan, click-to-seek, play/pause with playhead
- Multi-region selection with drag handles
- Export selected regions as WAV clips (ZIP download)

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

## Usage

1. Paste a YouTube URL and click **Download**
2. Browse the spectrogram — scroll to zoom, click to seek
3. Click **+ Add Region** to mark clips, drag edges to adjust
4. Click **Clip All** to download a ZIP of all selected regions

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
| `/api/audio/{file_id}` | GET | Serve WAV file |
| `/api/clip` | POST | Clip regions, return ZIP |
