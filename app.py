import os
import traceback
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastsaver import FastSaver, FastSaverError

# --- Импорт vk-video-downloader ---
try:
    from vk_parser import VKDownloader
    VK_DOWNLOADER_ENABLED = True
    print("vk-video-downloader loaded OK")
except Exception as e:
    print(f"vk-video-downloader import error: {e}")
    VK_DOWNLOADER_ENABLED = False

# --- Импорт dankert-download (универсальная альтернатива) ---
try:
    import dankert_download
    DANKERT_ENABLED = True
    print("dankert-download loaded OK")
except Exception as e:
    print(f"dankert-download import error: {e}")
    DANKERT_ENABLED = False

app = FastAPI(title="VideoDownloader Server", version="2.2.0")
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

# --- VK через vk-video-downloader ---
def _resolve_vk_via_vk_dl(url: str, quality: str = "max") -> dict:
    """Скачивание видео с VK через vk-video-downloader (без cookies)."""
    dl = VKDownloader(url)
    meta = dl.get_meta()
    # Выбираем качество
    target_q = "720p"
    if quality != "max":
        try:
            target_q = f"{min(int(quality), 720)}p"
        except (ValueError, TypeError):
            pass
    stream = dl.get_stream(quality=target_q)
    return {
        "video_url": stream["url"],
        "thumbnail": meta.get("thumbnail"),
        "title": meta.get("title", "VK video"),
        "ext": "mp4",
        "duration": meta.get("duration"),
        "platform": "vk",
        "quality": stream.get("quality", target_q),
    }

# --- VK через dankert-download (fallback) ---
def _resolve_vk_via_dankert(url: str, quality: str = "max") -> dict:
    """Скачивание видео с VK через dankert-download (универсальная библиотека)."""
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

# --- FastSaver (TikTok, Rutube, Facebook, Instagram, Pinterest) ---
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

# --- Роутинг ---
def _route(url: str, quality: str = "max") -> dict:
    lower = url.lower()
    # VK — пробуем специализированные библиотеки
    if "vk.com" in lower or "vkvideo.ru" in lower:
        if VK_DOWNLOADER_ENABLED:
            try:
                return _resolve_vk_via_vk_dl(url, quality)
            except Exception as e:
                print(f"vk-video-downloader failed: {e}, trying dankert-download...")
        if DANKERT_ENABLED:
            try:
                return _resolve_vk_via_dankert(url, quality)
            except Exception as e:
                print(f"dankert-download failed: {e}")
        raise HTTPException(500, "VK: все библиотеки не сработали")
    # Всё остальное — через FastSaver
    return _resolve_fastsaver(url)

@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "VideoDownloader Server",
        "libraries": {
            "fastsaver": saver is not None,
            "vk_video_downloader": VK_DOWNLOADER_ENABLED,
            "dankert_download": DANKERT_ENABLED,
        },
    }

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "vk": VK_DOWNLOADER_ENABLED or DANKERT_ENABLED,
        "fastsaver": saver is not None,
    }

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
