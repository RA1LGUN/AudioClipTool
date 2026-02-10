"""MMAE - Music/Media Audio Editor backend."""

import os
import uuid
import time
import zipfile
import io
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pydub import AudioSegment
import yt_dlp

DOWNLOADS_DIR = Path(__file__).parent / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

MAX_AGE_SECONDS = 3600  # 1 hour
PROXY = os.environ.get("MMAE_PROXY", "")

app = FastAPI(title="MMAE")


# ── Models ──────────────────────────────────────────────────────────────────

class DownloadRequest(BaseModel):
    url: str


class Region(BaseModel):
    start: float
    end: float


class ClipRequest(BaseModel):
    file_id: str
    regions: list[Region]


class TrackClipRequest(BaseModel):
    file_id: str
    track_name: str
    regions: list[Region]


class ClipMultiRequest(BaseModel):
    tracks: list[TrackClipRequest]


# ── Helpers ─────────────────────────────────────────────────────────────────

def cleanup_old_files() -> None:
    """Delete files in downloads/ older than MAX_AGE_SECONDS."""
    now = time.time()
    for entry in DOWNLOADS_DIR.iterdir():
        if entry.is_file() and (now - entry.stat().st_mtime) > MAX_AGE_SECONDS:
            entry.unlink(missing_ok=True)


def get_audio_path(file_id: str) -> Path:
    """Return the path for a given file_id, raise 404 if missing."""
    path = DOWNLOADS_DIR / f"{file_id}.wav"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Audio file not found")
    return path


# ── Routes ──────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.post("/api/download")
async def download_audio(req: DownloadRequest):
    # cleanup_old_files()

    file_id = uuid.uuid4().hex[:12]
    output_path = DOWNLOADS_DIR / f"{file_id}.wav"

    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": str(DOWNLOADS_DIR / f"{file_id}.%(ext)s"),
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "wav",
                "preferredquality": "0",
            }
        ],
        "quiet": True,
        "no_warnings": True,
    }

    if PROXY:
        ydl_opts["proxy"] = PROXY

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=True)
            title = info.get("title", "audio")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Download failed: {e}")

    if not output_path.exists():
        raise HTTPException(status_code=500, detail="Audio conversion failed")

    audio = AudioSegment.from_wav(str(output_path))
    duration = len(audio) / 1000.0  # seconds

    return {
        "file_id": file_id,
        "filename": title,
        "duration": duration,
    }


@app.get("/api/audio/{file_id}")
async def serve_audio(file_id: str):
    cleanup_old_files()
    path = get_audio_path(file_id)
    return FileResponse(path, media_type="audio/wav", filename=f"{file_id}.wav")


@app.post("/api/clip")
async def clip_audio(req: ClipRequest):
    cleanup_old_files()
    path = get_audio_path(req.file_id)

    if not req.regions:
        raise HTTPException(status_code=400, detail="No regions specified")

    audio = AudioSegment.from_wav(str(path))

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, region in enumerate(req.regions, start=1):
            start_ms = int(region.start * 1000)
            end_ms = int(region.end * 1000)
            clip = audio[start_ms:end_ms]

            clip_buf = io.BytesIO()
            clip.export(clip_buf, format="wav")
            clip_buf.seek(0)
            zf.writestr(f"clip_{i:03d}_{region.start:.2f}s-{region.end:.2f}s.wav", clip_buf.read())

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=clips.zip"},
    )


@app.post("/api/clip-multi")
async def clip_multi(req: ClipMultiRequest):
    cleanup_old_files()

    if not req.tracks:
        raise HTTPException(status_code=400, detail="No tracks specified")

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for track in req.tracks:
            path = get_audio_path(track.file_id)
            if not track.regions:
                continue
            audio = AudioSegment.from_wav(str(path))
            safe_name = "".join(
                c if c.isalnum() or c in (" ", "-", "_") else "_"
                for c in track.track_name
            ).strip() or track.file_id
            for i, region in enumerate(track.regions, start=1):
                start_ms = int(region.start * 1000)
                end_ms = int(region.end * 1000)
                clip = audio[start_ms:end_ms]
                clip_buf = io.BytesIO()
                clip.export(clip_buf, format="wav")
                clip_buf.seek(0)
                zf.writestr(
                    f"{safe_name}/clip_{i:03d}_{region.start:.2f}s-{region.end:.2f}s.wav",
                    clip_buf.read(),
                )

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=clips_multi.zip"},
    )


# Serve static files (CSS, JS, favicon, etc.)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


def run():
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    run()
