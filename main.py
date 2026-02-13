"""MMAE - Music/Media Audio Editor backend."""

import logging
import os
import uuid
import time
import io
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("mmae")

import boto3
from dotenv import load_dotenv

load_dotenv()
from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pydub import AudioSegment
import yt_dlp

DOWNLOADS_DIR = Path(__file__).parent / "downloads"
DOWNLOADS_DIR.mkdir(exist_ok=True)

MAX_AGE_SECONDS = 3600  # 1 hour
ALLOWED_AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".opus", ".webm",
}
PROXY = os.environ.get("MMAE_PROXY", "")

R2_ENDPOINT_URL = os.environ.get("R2_ENDPOINT_URL", "")
R2_ACCESS_KEY_ID = os.environ.get("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.environ.get("R2_SECRET_ACCESS_KEY", "")
R2_BUCKET_NAME = os.environ.get("R2_BUCKET_NAME", "")
R2_PUBLIC_URL = os.environ.get("R2_PUBLIC_URL", "")

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


def upload_to_r2(data: bytes, key: str) -> str:
    """Upload bytes to Cloudflare R2 and return the public URL."""
    logger.info("R2 upload: key=%s size=%d bytes", key, len(data))
    client = boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
    )
    client.put_object(
        Bucket=R2_BUCKET_NAME,
        Key=key,
        Body=data,
        ContentType="audio/wav",
    )
    url = f"{R2_PUBLIC_URL.rstrip('/')}/{key}"
    logger.info("R2 upload done: %s", url)
    return url


# ── Routes ──────────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.post("/api/download")
async def download_audio(req: DownloadRequest):
    # cleanup_old_files()
    logger.info("POST /api/download url=%s", req.url)

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
        "noplaylist": True,
        'lazy_extractors': False,
    }

    if PROXY:
        ydl_opts["proxy"] = PROXY

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=True)
            title = info.get("title", "audio")
            logger.info("yt-dlp done: title=%s file_id=%s", title, file_id)
    except Exception as e:
        logger.error("yt-dlp failed: %s", e)
        raise HTTPException(status_code=400, detail=f"Download failed: {e}")

    if not output_path.exists():
        raise HTTPException(status_code=500, detail="Audio conversion failed")

    audio = AudioSegment.from_wav(str(output_path))
    duration = len(audio) / 1000.0  # seconds
    logger.info("Download complete: file_id=%s duration=%.2fs", file_id, duration)

    return {
        "file_id": file_id,
        "filename": title,
        "duration": duration,
    }


@app.post("/api/upload")
async def upload_audio(files: list[UploadFile] = File(...)):
    logger.info("POST /api/upload files=%d", len(files))
    results = []
    for f in files:
        ext = Path(f.filename or "").suffix.lower()
        logger.info("Processing upload: filename=%s ext=%s", f.filename, ext)
        if ext not in ALLOWED_AUDIO_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{ext}' for '{f.filename}'. "
                       f"Allowed: {', '.join(sorted(ALLOWED_AUDIO_EXTENSIONS))}",
            )

        file_id = uuid.uuid4().hex[:12]
        output_path = DOWNLOADS_DIR / f"{file_id}.wav"

        raw_bytes = await f.read()
        try:
            audio = AudioSegment.from_file(io.BytesIO(raw_bytes))
        except Exception as e:
            logger.error("Decode failed for '%s': %s", f.filename, e)
            raise HTTPException(
                status_code=400,
                detail=f"Could not decode '{f.filename}': {e}",
            )

        audio.export(str(output_path), format="wav")
        duration = len(audio) / 1000.0

        original_name = Path(f.filename or "audio").stem
        logger.info("Upload done: file_id=%s name=%s duration=%.2fs", file_id, original_name, duration)
        results.append({
            "file_id": file_id,
            "filename": original_name,
            "duration": duration,
        })

    return results


@app.get("/api/audio/{file_id}")
async def serve_audio(file_id: str):
    logger.info("GET /api/audio/%s", file_id)
    cleanup_old_files()
    path = get_audio_path(file_id)
    return FileResponse(path, media_type="audio/wav", filename=f"{file_id}.wav")


@app.post("/api/clip")
async def clip_audio(req: ClipRequest):
    logger.info("POST /api/clip file_id=%s regions=%d", req.file_id, len(req.regions))
    cleanup_old_files()
    path = get_audio_path(req.file_id)

    if not req.regions:
        raise HTTPException(status_code=400, detail="No regions specified")

    audio = AudioSegment.from_wav(str(path))
    timestamp = int(time.time())
    clips = []

    for i, region in enumerate(req.regions, start=1):
        start_ms = int(region.start * 1000)
        end_ms = int(region.end * 1000)
        clip = audio[start_ms:end_ms]

        clip_buf = io.BytesIO()
        clip.export(clip_buf, format="wav")
        clip_bytes = clip_buf.getvalue()

        name = f"clip_{i:03d}_{region.start:.3f}s-{region.end:.3f}s.wav"
        key = f"clips/{timestamp}_{req.file_id}/{name}"
        url = upload_to_r2(clip_bytes, key)
        clips.append({"name": name, "url": url})

    return {"clips": clips}


@app.post("/api/clip-multi")
async def clip_multi(req: ClipMultiRequest):
    # cleanup_old_files()
    total_regions = sum(len(t.regions) for t in req.tracks)
    logger.info("POST /api/clip-multi tracks=%d total_regions=%d", len(req.tracks), total_regions)

    if not req.tracks:
        raise HTTPException(status_code=400, detail="No tracks specified")

    timestamp = int(time.time())
    data_items = []

    for track in req.tracks:
        path = get_audio_path(track.file_id)
        if not track.regions:
            logger.info("  Track '%s' has no regions, skipping", track.track_name)
            continue
        logger.info("  Track '%s' file_id=%s regions=%d", track.track_name, track.file_id, len(track.regions))
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
            clip_bytes = clip_buf.getvalue()

            name = f"clip_{i:03d}_{region.start:.3f}s-{region.end:.3f}s.wav"
            key = f"clips/{timestamp}_{safe_name}/{name}"
            url = upload_to_r2(clip_bytes, key)
            logger.info("    Clip %d: %.3fs-%.3fs name=%s", i, region.start, region.end, name)

            data_items.append({"content": name, "type": "TITLE"})
            data_items.append({"content": url, "type": "AUDIO"})
            data_items.append({
                "content": f"start timestamp {region.start:.3f} / end timestamp {region.end:.3f}",
                "type": "TEXT",
            })
            # data_items.append({"content": f"Download URL {url}", "type": "TEXT"})

    logger.info("clip-multi done: %d data items generated", len(data_items))
    return [{"info": {"data": data_items}}]


# Serve static files (CSS, JS, favicon, etc.)
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")


def run():
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)


if __name__ == "__main__":
    run()
