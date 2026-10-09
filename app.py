import os
import traceback
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastsaver import FastSaver, FastSaverError

# Импорты бесплатных библиотек
try:
    import ydpy
    import vk_parser
    from parth_dl import InstagramDownloader
    from fdown_api import Fdown
    YOUTUBE_ENABLED = True
    VK_ENABLED = True
    INSTAGRAM_ENABLED = True
    FACEBOOK_ENABLED = True
    print("All free libraries imported successfully")
except Exception as e:
    print(f"Import error: {e}")
    YOUTUBE_ENABLED = False
    VK_ENABLED = False
    INSTAGRAM_ENABLED = False
    FACEBOOK_ENABLED = False


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


def _resolve_youtube(url: str) -> dict:
    """YouTube через ydpy — без cookies."""
    video = ydpy.Video(url)
    data = video.fetch()
    # Ищем лучший mp4 поток
    best = max(
        (f for f in data.formats if f.mime_type and "video/mp4" in f.mime_type),
        key=lambda f: (f.height or 0, f.bitrate or 0)
    )
    return {
        "video_url": best.url,
        "thumbnail": None,
        "title": f"YouTube video {data.video_id}",
        "ext": "mp4",
        "duration": None,
        "platform": "youtube",
    }


def _resolve_vk(url: str) -> dict:
    """VK через vk-video-downloader — без cookies."""
    dl = vk_parser.VKDownloader(url)
    info = dl.get_meta()
    # Получаем прямую ссылку
    stream = dl.get_stream(quality="720p")
    return {
        "video_url": stream.url,
        "thumbnail": info.get("thumbnail"),
        "title": info.get("title", "VK video"),
        "ext": "mp4",
        "duration": info.get("duration"),
        "platform": "vk",
    }


def _resolve_instagram(url: str) -> dict:
    """Instagram через parth-dl — только публичный контент."""
    dl = InstagramDownloader()
    info = dl.get_info(url)
    return {
        "video_url": info["video_url"],
        "thumbnail": info.get("thumbnail"),
        "title": info.get("title", "Instagram media"),
        "ext": "mp4",
        "duration": info.get("duration"),
        "platform": "instagram",
    }


def _resolve_facebook(url: str) -> dict:
    """Facebook через fdown-api — без cookies."""
    f = Fdown()
    links = f.get_links(url)
    return {
        "video_url": links["hd"] or links["normal"],
        "thumbnail": None,
        "title": "Facebook video",
        "ext": "mp4",
        "duration": None,
        "platform": "facebook",
    }


def _build_response(result) -> dict:
    if not result or not result.download_url:
        raise ValueError("Не удалось получить ссылку на медиа")
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
        "service": "VideoDownloader Server (Free + FastSaver)",
        "libraries": {
            "youtube": YOUTUBE_ENABLED,
            "vk": VK_ENABLED,
            "instagram": INSTAGRAM_ENABLED,
            "facebook": FACEBOOK_ENABLED,
            "fastsaver": saver is not None,
        },
    }


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "youtube": YOUTUBE_ENABLED,
        "vk": VK_ENABLED,
        "instagram": INSTAGRAM_ENABLED,
        "facebook": FACEBOOK_ENABLED,
        "fastsaver": saver is not None,
    }


def _route_by_url(url: str) -> dict:
    """Роутинг по домену."""
    lower = url.lower()

    # TikTok — через FastSaver (работает, но платно). Если хотите бесплатно — раскомментируйте tikwm.
    if "tiktok.com" in lower or "vt.tiktok" in lower or "vm.tiktok" in lower:
        if saver:
            return _build_response(saver.fetch(url))
        raise HTTPException(500, "TikTok: FastSaver недоступен")

    # YouTube — через ydpy (бесплатно)
    if ("youtube.com" in lower or "youtu.be" in lower) and YOUTUBE_ENABLED:
        return _resolve_youtube(url)

    # VK — через vk-video-downloader (бесплатно)
    if ("vk.com" in lower or "vkvideo.ru" in lower) and VK_ENABLED:
        return _resolve_vk(url)

    # Instagram — через parth-dl (бесплатно, только публичное)
    if "instagram.com" in lower and INSTAGRAM_ENABLED:
        return _resolve_instagram(url)

    # Facebook — через fdown-api (бесплатно)
    if "facebook.com" in lower and FACEBOOK_ENABLED:
        return _resolve_facebook(url)

    # Rutube и всё остальное — через FastSaver
    if saver:
        return _build_response(saver.fetch(url))

    raise HTTPException(500, "Сервис не поддерживается")


@app.post("/api/info")
async def api_info(req: InfoRequest):
    try:
        return _route_by_url(req.url)
    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}\n{tb[-500:]}")


@app.post("/api/resolve")
async def api_resolve(req: ResolveRequest):
    try:
        return _route_by_url(req.url)
    except HTTPException:
        raise
    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}\n{tb[-500:]}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
