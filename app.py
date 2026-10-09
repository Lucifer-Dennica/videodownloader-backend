import os
import traceback
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastsaver import FastSaver, FastSaverError


app = FastAPI(title="VideoDownloader Server", version="2.1.0")
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
        "service": "VideoDownloader Server (FastSaver)",
        "endpoints": ["/api/health", "/api/info", "/api/resolve"],
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "fastsaver", "ready": saver is not None}


@app.post("/api/info")
async def api_info(req: InfoRequest):
    if saver is None:
        raise HTTPException(500, "Сервер не настроен: нет FASTSAVER_API_KEY")
    try:
        result = saver.fetch(req.url)
        return _build_response(result)
    except FastSaverError as e:
        raise HTTPException(500, f"FastSaver error: {str(e)}")
    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}\n{tb[-500:]}")


@app.post("/api/resolve")
async def api_resolve(req: ResolveRequest):
    if saver is None:
        raise HTTPException(500, "Сервер не настроен: нет FASTSAVER_API_KEY")
    try:
        result = saver.fetch(req.url)
        return _build_response(result)
    except FastSaverError as e:
        raise HTTPException(500, f"FastSaver error: {str(e)}")
    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}\n{tb[-500:]}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
