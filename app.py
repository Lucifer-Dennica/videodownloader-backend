import os
import traceback
import subprocess
import tempfile
import urllib.parse
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from fastsaver import FastSaver, FastSaverError


app = FastAPI(title="VideoDownloader Server", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

saver = None
try:
    saver = FastSaver()
    print("FastSaver initialized OK")
except Exception as e:
    print(f"FastSaver init failed: {e}")


class ResolveRequest(BaseModel):
    url: str
    audio_only: bool = False
    quality: str = "max"


class InfoRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    url: str


def _build_info(result) -> dict:
    if not result or not result.download_url:
        raise ValueError("Не удалось получить ссылку")
    ext = "mp4"
    if result.type:
        ext = result.type.split("/")[-1]
    return {
        "video_url": result.download_url,
        "thumbnail": result.thumbnail_url,
        "title": result.caption or "media",
        "ext": ext,
        "duration": result.duration,
        "platform": result.source,
    }


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "VideoDownloader Server (FastSaver + ffmpeg)",
        "endpoints": ["/api/health", "/api/info", "/api/resolve", "/api/download"],
    }


@app.get("/api/health")
def health():
    # Проверяем, что ffmpeg доступен
    try:
        subprocess.run(["ffmpeg", "-version"], capture_output=True, timeout=5)
        ffmpeg_ok = True
    except Exception:
        ffmpeg_ok = False
    return {
        "status": "ok",
        "fastsaver": saver is not None,
        "ffmpeg": ffmpeg_ok,
    }


@app.post("/api/info")
async def api_info(req: InfoRequest):
    if saver is None:
        raise HTTPException(500, "FastSaver не инициализирован")
    try:
        return _build_info(saver.fetch(req.url))
    except FastSaverError as e:
        raise HTTPException(500, f"FastSaver error: {str(e)}")
    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}\n{tb[-500:]}")


@app.post("/api/resolve")
async def api_resolve(req: ResolveRequest):
    if saver is None:
        raise HTTPException(500, "FastSaver не инициализирован")
    try:
        return _build_info(saver.fetch(req.url))
    except FastSaverError as e:
        raise HTTPException(500, f"FastSaver error: {str(e)}")
    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}\n{tb[-500:]}")


@app.post("/api/download")
async def api_download(req: DownloadRequest):
    """
    Скачивает видео на сервере (включая HLS) и отдаёт готовый mp4.
    """
    if saver is None:
        raise HTTPException(500, "FastSaver не инициализирован")

    try:
        result = saver.fetch(req.url)
        if not result or not result.download_url:
            raise HTTPException(500, "FastSaver не вернул ссылку")

        source_url = result.download_url
        print(f"Source URL: {source_url}")

        # Если это прямой mp4 — отдаём как есть через redirect
        if source_url.lower().endswith(".mp4") and "m3u8" not in source_url.lower():
            from fastapi.responses import RedirectResponse
            return RedirectResponse(source_url)

        # Иначе — качаем через ffmpeg (HLS, DASH или нестандартные форматы)
        tmp_dir = tempfile.mkdtemp()
        output_path = os.path.join(tmp_dir, "video.mp4")

        # FFmpeg команда: копируем потоки без перекодирования (быстро)
        cmd = [
            "ffmpeg",
            "-y",
            "-loglevel", "error",
            "-user_agent", "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36",
            "-i", source_url,
            "-c", "copy",
            "-bsf:a", "aac_adtstoasc",
            "-movflags", "+faststart",
            output_path,
        ]

        proc = subprocess.run(cmd, capture_output=True, timeout=280)
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="ignore")[:300]
            raise HTTPException(500, f"ffmpeg error: {err}")

        if not os.path.exists(output_path) or os.path.getsize(output_path) < 1000:
            raise HTTPException(500, "ffmpeg вернул пустой файл")

        # Безопасное имя файла
        safe_title = "".join(c for c in (result.caption or "video") if c.isalnum() or c in " _-")[:60].strip() or "video"
        filename = f"{safe_title}.mp4"

        return FileResponse(
            output_path,
            media_type="video/mp4",
            filename=filename,
            background=None,
        )

    except HTTPException:
        raise
    except subprocess.TimeoutExpired:
        raise HTTPException(504, "ffmpeg timeout — видео слишком длинное")
    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}\n{tb[-500:]}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
