import os
import traceback
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastsaver import FastSaver, FastSaverError


app = FastAPI(title="VideoDownloader Server", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Инициализируем клиент FastSaver.
# API-ключ будет взят из переменной окружения FASTSAVER_API_KEY, которую мы зададим на Render.
try:
    saver = FastSaver()
except Exception as e:
    # Если ключ не задан, сервер всё равно запустится, но запросы будут падать с ошибкой.
    saver = None
    print(f"FastSaver initialization failed: {e}. Please set FASTSAVER_API_KEY.")


class ResolveRequest(BaseModel):
    url: str
    audio_only: bool = False
    quality: str = "max"


@app.get("/")
def root():
    return {
        "status": "ok",
        "service": "VideoDownloader Server (FastSaverAPI)",
        "endpoints": ["/api/health", "/api/resolve"],
    }


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "fastsaver"}


@app.post("/api/resolve")
async def api_resolve(req: ResolveRequest):
    if saver is None:
        raise HTTPException(500, "Сервер не настроен: отсутствует API-ключ FastSaver.")

    try:
        # FastSaver сам определяет платформу по ссылке.
        # Для YouTube, TikTok, Rutube, VK, Instagram и других он вернёт прямую ссылку.
        # Параметр audio_only пока не поддерживается напрямую, но мы можем указать это в запросе.
        # FastSaver вернёт как видео, так и аудио-ссылки, если они есть.
        result = saver.fetch(req.url)

        # Проверяем, что вернул сервис
        if not result or not result.download_url:
            raise ValueError("FastSaver: не удалось получить ссылку на медиа")

        # Формируем ответ в том же формате, что и раньше
        return {
            "video_url": result.download_url,
            "thumbnail": result.thumbnail_url,
            "title": result.caption or "media",
            "ext": result.type.split('/')[-1] if result.type else "mp4",  # video/mp4 -> mp4
            "duration": result.duration,
            "platform": result.source,  # например, "youtube", "tiktok"
        }

    except FastSaverError as e:
        # Обрабатываем специфичные ошибки FastSaver
        raise HTTPException(500, f"FastSaver error: {str(e)}")
    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:300]}\n{tb[-800:]}")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
