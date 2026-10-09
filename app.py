import os
import traceback
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastsaver import FastSaver, FastSaverError
import yt_dlp

try:
    import dankert_download
    DANKERT_ENABLED = True
except Exception as e:
    print(f"dankert-download import error: {e}")
    DANKERT_ENABLED = False

app = FastAPI(title="VideoDownloader Server", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False, allow_methods=["*"], allow_headers=["*"])

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

def _resolve_youtube(url: str, quality: str = "max") -> dict:
    """YouTube через yt-dlp с PO Token Provider."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        # Указываем POT-провайдеру, что мы используем его
        "extractor_args": {
            "youtube": {
                "player_client": ["web", "mweb", "tv"],
                "po_token_provider": ["http://127.0.0.1:4416"],
            }
        },
        "format": "best[ext=mp4][height<=720]/best[height<=720]/best",
    }
    if quality != "max":
        try:
            max_h = min(int(quality), 720)
            opts["format"] = f"best[ext=mp4][height<={max_h}]/best[height<={max_h}]/best"
        except (ValueError, TypeError):
            pass

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if "entries" in info and info["entries"]:
        info = info["entries"][0]

    media_url = info.get("url")
    ext = info.get("ext", "mp4")
    if not media_url and info.get("formats"):
        for f in reversed(info["formats"]):
            if f.get("ext") == "mp4" and f.get("url"):
                media_url = f["url"]
                ext = "mp4"
                break

    if not media_url:
        raise ValueError("YouTube: не удалось получить ссылку")

    return {
        "video_url": media_url,
        "thumbnail": info.get("thumbnail"),
        "title": info.get("title", "YouTube video"),
        "ext": ext,
        "duration": info.get("duration"),
        "platform": "youtube",
    }

def _resolve_vk_dankert(url: str, quality: str = "max") -> dict:
    """VK через dankert-download (fallback)."""
    result = dankert_download.download(url, quality=quality)
    if not result or not result.get("url"):
        raise ValueError("dankert-download: не удалось получить ссылку")
    return {
        "video_url": result["url"],
        "thumbnail": result.get("thumbnail"),
        "title": result.get("title", "VK video"),
        "ext": "mp4",
        "duration": result.get("duration"),
        "platform": "vk",
    }

def _resolve_fastsaver(url: str) -> dict:
    if saver is None:
        raise ValueError("FastSaver не инициализирован")
    result = saver.fetch(url)
    if not result or not result.download_url:
        raise ValueError("FastSaver: нет ссылки на медиа")
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

def _route(url: str, quality: str = "max") -> dict:
    lower = url.lower()
    if ("youtube.com" in lower or "youtu.be" in lower):
        return _resolve_youtube(url, quality)
    if "vk.com" in lower or "vkvideo.ru" in lower:
        if DANKERT_ENABLED:
            return _resolve_vk_dankert(url, quality)
        raise HTTPException(500, "VK: библиотека dankert-download не загружена")
    return _resolve_fastsaver(url)

@app.get("/")
def root():
    return {"status": "ok", "service": "VideoDownloader Server", "youtube": True, "vk": DANKERT_ENABLED, "fastsaver": saver is not None}

@app.get("/api/health")
def health():
    return {"status": "ok", "youtube": True, "vk": DANKERT_ENABLED, "fastsaver": saver is not None}

@app.post("/api/info")
async def api_info(req: InfoRequest):
    try:
        return _route(req.url)
    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}\n{tb[-500:]}")

@app.post("/api/resolve")
async def api_resolve(req: ResolveRequest):
    try:
        return _route(req.url, req.quality)
    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}\n{tb[-500:]}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
