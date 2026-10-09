import os
import traceback
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastsaver import FastSaver


app = FastAPI(title="VideoDownloader Server", version="4.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Инициализация библиотек ---

# FastSaver — для Rutube, Facebook, Instagram
saver = None
try:
    saver = FastSaver()
    print("FastSaver initialized OK")
except Exception as e:
    print(f"FastSaver init failed: {e}")

# ydpy — для YouTube (без cookies, без блокировок)
try:
    import ydpy
    YOUTUBE_ENABLED = True
    print("ydpy (YouTube) loaded OK")
except Exception as e:
    print(f"ydpy import error: {e}")
    YOUTUBE_ENABLED = False

# vk-video-downloader — для VK (без cookies, публичные видео)
try:
    from vk_parser import VKDownloader
    VK_ENABLED = True
    print("vk-video-downloader loaded OK")
except Exception as e:
    print(f"vk-video-downloader import error: {e}")
    VK_ENABLED = False

# pybalt — запасной вариант для VK (через cobalt instances)
try:
    from pybalt import download as pybalt_download
    PYBALT_ENABLED = True
    print("pybalt loaded OK")
except Exception as e:
    print(f"pybalt import error: {e}")
    PYBALT_ENABLED = False


class ResolveRequest(BaseModel):
    url: str
    audio_only: bool = False
    quality: str = "max"


class InfoRequest(BaseModel):
    url: str


# --- YouTube через ydpy ---

def _resolve_youtube(url: str, quality: str = "max") -> dict:
    """
    ydpy.fetch() возвращает список playable streams.
    Мы выбираем лучший mp4-поток и отдаём прямую ссылку.
    """
    data = ydpy.PlayableVideo.fetch(url)

    # Ищем лучший mp4-поток (video+audio)
    mp4_formats = [
        f for f in data.formats
        if f.mime_type and "video/mp4" in f.mime_type
    ]
    if not mp4_formats:
        # Если нет mp4 — берём лучший видео-поток
        video_formats = [f for f in data.formats if f.height and f.height > 0]
        if not video_formats:
            raise ValueError("YouTube: нет доступных видео-потоков")
        best = max(video_formats, key=lambda f: (f.height or 0, f.bitrate or 0))
    else:
        # Фильтрация по максимальной высоте (720 по умолчанию)
        max_h = 720
        if quality != "max":
            try:
                max_h = min(int(quality), 720)
            except (ValueError, TypeError):
                pass
        filtered = [f for f in mp4_formats if (f.height or 0) <= max_h]
        pool = filtered if filtered else mp4_formats
        best = max(pool, key=lambda f: (f.height or 0, f.bitrate or 0))

    return {
        "video_url": best.url,
        "thumbnail": None,  # ydpy не отдаёт thumbnail в fetch
        "title": f"YouTube {data.video_id}",
        "ext": "mp4",
        "duration": None,
        "platform": "youtube",
        "quality": f"{best.height}p" if best.height else "unknown",
    }


# --- VK через vk-video-downloader ---

def _resolve_vk(url: str, quality: str = "max") -> dict:
    """
    VKDownloader парсит публичную страницу VK и достаёт прямые ссылки.
    """
    dl = VKDownloader(url)
    meta = dl.get_meta()

    # Пытаемся получить лучший поток
    target_quality = "720p"
    if quality != "max":
        try:
            target_quality = f"{min(int(quality), 720)}p"
        except (ValueError, TypeError):
            pass

    # VKDownloader умеет возвращать список форматов
    streams = dl.get_streams()  # список dict с полями url, quality, ext

    if not streams:
        raise ValueError("VK: не удалось найти видео-потоки")

    # Выбираем лучшее качество ≤ запрошенного
    def qnum(q):
        try:
            return int(q.replace("p", ""))
        except Exception:
            return 0

    max_q = qnum(target_quality)
    pool = [s for s in streams if qnum(s.get("quality", "0p")) <= max_q]
    if not pool:
        pool = streams

    best = max(pool, key=lambda s: qnum(s.get("quality", "0p")))

    return {
        "video_url": best["url"],
        "thumbnail": meta.get("thumbnail"),
        "title": meta.get("title", "VK video"),
        "ext": best.get("ext", "mp4"),
        "duration": meta.get("duration"),
        "platform": "vk",
        "quality": best.get("quality"),
    }


# --- VK через pybalt (fallback) ---

def _resolve_vk_pybalt(url: str) -> dict:
    """
    pybalt использует cobalt instances. Возвращает прямую ссылку.
    """
    result = pybalt_download(url)
    if not result:
        raise ValueError("pybalt: не удалось получить результат")

    # pybalt может вернуть dict или объект
    if isinstance(result, dict):
        return {
            "video_url": result.get("url") or result.get("video_url"),
            "thumbnail": result.get("thumbnail"),
            "title": result.get("title", "VK video"),
            "ext": "mp4",
            "duration": result.get("duration"),
            "platform": "vk",
        }
    # Если вернул путь к файлу — значит скачал, а не отдал ссылку
    raise ValueError("pybalt скачал файл, а не вернул ссылку")


# --- FastSaver (Rutube, Facebook, Instagram, TikTok) ---

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

    # YouTube
    if ("youtube.com" in lower or "youtu.be" in lower):
        if YOUTUBE_ENABLED:
            return _resolve_youtube(url, quality)
        raise HTTPException(500, "YouTube: библиотека ydpy не загружена")

    # VK
    if ("vk.com" in lower or "vkvideo.ru" in lower):
        if VK_ENABLED:
            try:
                return _resolve_vk(url, quality)
            except Exception as e:
                print(f"vk-video-downloader failed: {e}, trying pybalt...")
                if PYBALT_ENABLED:
                    return _resolve_vk_pybalt(url)
                raise
        elif PYBALT_ENABLED:
            return _resolve_vk_pybalt(url)
        raise HTTPException(500, "VK: все библиотеки не загружены")

    # TikTok, Rutube, Facebook, Instagram → FastSaver
    return _resolve_fastsaver(url)


# --- Endpoints ---

@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "VideoDownloader Server",
        "libraries": {
            "fastsaver": saver is not None,
            "youtube_ydpy": YOUTUBE_ENABLED,
            "vk_video_downloader": VK_ENABLED,
            "pybalt": PYBALT_ENABLED,
        },
    }


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "youtube": YOUTUBE_ENABLED,
        "vk": VK_ENABLED or PYBALT_ENABLED,
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
