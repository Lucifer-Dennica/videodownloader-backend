import os
import base64
import json
import traceback
import urllib.parse
import urllib.request

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp


app = FastAPI(title="VideoDownloader Server", version="1.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Мобильный User-Agent — как у настоящего пользователя приложения
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
)

# Браузерный User-Agent для tikwm
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class ResolveRequest(BaseModel):
    url: str
    audio_only: bool = False
    quality: str = "max"


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "VideoDownloader Server",
        "endpoints": ["/api/health", "/api/resolve"],
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "yt-dlp+tikwm"}


def build_format(quality: str, audio_only: bool) -> str:
    if audio_only:
        return "bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio/best"

    if quality == "max":
        return "best[ext=mp4][height<=720]/best[height<=720]/best"

    try:
        max_h = min(int(quality), 720)
    except (ValueError, TypeError):
        max_h = 720

    return f"best[ext=mp4][height<={max_h}]/best[height<={max_h}]/best"


def resolve_tiktok(url: str, audio_only: bool) -> dict:
    """TikTok через tikwm. Используем браузерные заголовки — иначе 403."""
    api = "https://tikwm.com/api/?url=" + urllib.parse.quote(url, safe="")

    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://tikwm.com/",
        "Origin": "https://tikwm.com",
    }

    req = urllib.request.Request(api, headers=headers)

    with urllib.request.urlopen(req, timeout=25) as r:
        data = json.loads(r.read().decode("utf-8"))

    if data.get("code") != 0:
        raise ValueError(f"tikwm: {data.get('msg', 'unknown')}")

    d = data.get("data") or {}

    if audio_only:
        music = d.get("music")
        if not music:
            raise ValueError("tikwm: нет аудио")
        ext = "mp3" if ".mp3" in music.lower() else "m4a"
        return {
            "video_url": music,
            "thumbnail": d.get("cover"),
            "title": d.get("title", "TikTok audio"),
            "ext": ext,
        }

    video = d.get("hdplay") or d.get("play")
    if not video:
        images = d.get("images") or []
        if images:
            return {
                "video_url": None,
                "image_urls": images,
                "thumbnail": d.get("cover"),
                "title": d.get("title", "TikTok photos"),
                "ext": "jpg",
                "is_carousel": True,
            }
        raise ValueError("tikwm: нет ни видео, ни картинок")

    return {
        "video_url": video,
        "thumbnail": d.get("cover"),
        "title": d.get("title", "TikTok video"),
        "ext": "mp4",
    }


def resolve_ytdlp(url: str, audio_only: bool, quality: str) -> dict:
    """YouTube, Rutube, VK, SoundCloud, Reddit и т.д."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "format": build_format(quality, audio_only),
        "skip_download": True,
        "noplaylist": True,
        "http_headers": {"User-Agent": USER_AGENT},
        "retries": 3,
        "socket_timeout": 20,
    }

    # Cookies (если заданы) — для YouTube / VK / Instagram
    cookies_b64 = os.environ.get("YTDLP_COOKIES_B64")
    if cookies_b64:
        try:
            cookies_path = "/tmp/cookies.txt"
            with open(cookies_path, "wb") as f:
                f.write(base64.b64decode(cookies_b64))
            opts["cookiefile"] = cookies_path
        except Exception as e:
            print(f"Cookies decode failed: {e}")

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if "entries" in info and info["entries"]:
        info = info["entries"][0]

    media_url = info.get("url")
    ext = info.get("ext", "mp4")

    if not media_url and info.get("formats"):
        if audio_only:
            for f in reversed(info["formats"]):
                if (f.get("acodec") not in (None, "none")
                        and f.get("vcodec") in (None, "none")):
                    media_url = f.get("url")
                    ext = f.get("ext", "m4a")
                    if media_url:
                        break
        else:
            for f in reversed(info["formats"]):
                if f.get("ext") == "mp4" and f.get("url"):
                    media_url = f["url"]
                    ext = "mp4"
                    break

    if not media_url:
        raise ValueError("No media URL found")

    return {
        "video_url": media_url,
        "thumbnail": info.get("thumbnail"),
        "title": info.get("title", "media"),
        "ext": ext,
        "duration": info.get("duration"),
    }


def resolve_media(url: str, audio_only: bool = False, quality: str = "max") -> dict:
    url = url.strip()
    lower = url.lower()

    if "tiktok.com" in lower or "vt.tiktok" in lower or "vm.tiktok" in lower:
        return resolve_tiktok(url, audio_only)
    return resolve_ytdlp(url, audio_only, quality)


@app.post("/api/resolve")
async def api_resolve(req: ResolveRequest):
    try:
        return resolve_media(req.url, req.audio_only, req.quality)
    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(500, f"Download error: {str(e)[:300]}")
    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}\n{tb[-800:]}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
