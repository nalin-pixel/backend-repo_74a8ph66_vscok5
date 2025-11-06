import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
import requests
from typing import Optional, Dict, Any

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TikTokRequest(BaseModel):
    url: HttpUrl


class ResolveRequest(BaseModel):
    url: HttpUrl


@app.get("/")
def read_root():
    return {"message": "Hello from FastAPI Backend!"}


@app.get("/api/hello")
def hello():
    return {"message": "Hello from the backend API!"}


@app.post("/api/tiktok/metadata")
def tiktok_metadata(payload: TikTokRequest):
    """
    Resolve TikTok video metadata and direct no-watermark download URL by calling a
    reliable third-party resolver (tikwm.com). We simply proxy essential data.
    """
    try:
        resp = requests.post(
            "https://www.tikwm.com/api/",
            data={"url": str(payload.url)},
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                "Referer": "https://www.tikwm.com/",
                "Origin": "https://www.tikwm.com",
            },
            timeout=20,
        )
    except requests.RequestException as e:
        raise HTTPException(status_code=502, detail=f"Resolver network error: {e}")

    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail="Resolver error")

    data = resp.json()
    if not data or data.get("code") != 0 or not data.get("data"):
        raise HTTPException(status_code=400, detail=data.get("msg", "Failed to resolve video"))

    d = data["data"]
    # Prefer hdplay (no watermark) if present, fall back to play.
    download_url = d.get("hdplay") or d.get("play")
    if not download_url:
        raise HTTPException(status_code=404, detail="Download URL not found")

    title = d.get("title") or "TikTok Video"
    cover = d.get("cover") or d.get("origin_cover") or d.get("music_info", {}).get("cover")

    return {
        "title": title,
        "cover": cover,
        "download_url": download_url,
        "duration": d.get("duration"),
        "author": d.get("author"),
    }


@app.post("/api/resolve")
def resolve_generic(payload: ResolveRequest):
    """
    Resolve direct media for popular platforms (YouTube, Instagram, TikTok, RED/Rednote, etc.)
    using yt-dlp without downloading. Returns a normalized response.
    """
    try:
        import yt_dlp  # type: ignore
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"yt-dlp not available: {e}")

    ydl_opts: Dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "format": "bv*+ba/b[ext=mp4]/b/bestaudio/best",
        "noplaylist": True,
        "skip_download": True,
        "cachedir": False,
        "http_chunk_size": 10485760,  # 10MB chunks can help some CDNs
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(str(payload.url), download=False)
    except yt_dlp.utils.DownloadError as e:  # type: ignore
        raise HTTPException(status_code=400, detail=f"Failed to extract: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")

    # If a playlist-like object, pick first entry
    if info.get("_type") == "playlist" and info.get("entries"):
        info = info["entries"][0]

    title: str = info.get("title") or "Video"
    cover: Optional[str] = info.get("thumbnail") or info.get("thumbnails", [{}])[0].get("url")
    author: Optional[str] = info.get("uploader") or info.get("channel") or info.get("author")
    duration: Optional[float] = info.get("duration")

    # Determine a streaming URL from requested formats or formats
    download_url: Optional[str] = None
    # When format selection picks merged formats, yt-dlp exposes requested_formats
    requested_formats = info.get("requested_formats") or []
    if requested_formats:
        # Prefer the video part if available else the first
        for f in requested_formats:
            if f.get("vcodec") != "none" and f.get("url"):
                download_url = f.get("url")
                break
        if not download_url and requested_formats[0].get("url"):
            download_url = requested_formats[0].get("url")

    if not download_url:
        # Fall back to the best single format url
        if info.get("url"):
            download_url = info.get("url")
        else:
            formats = info.get("formats") or []
            # Choose best mp4 if possible otherwise last format
            best = None
            for f in formats:
                if f.get("url") and (f.get("ext") == "mp4"):
                    best = f
            if not best and formats:
                best = formats[-1]
            if best:
                download_url = best.get("url")

    if not download_url:
        raise HTTPException(status_code=404, detail="Could not determine a direct media URL")

    return {
        "title": title,
        "cover": cover,
        "download_url": download_url,
        "duration": duration,
        "author": author,
        "source": info.get("extractor_key"),
    }


@app.get("/test")
def test_database():
    """Test endpoint to check if database is available and accessible"""
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    
    try:
        # Try to import database module
        from database import db
        
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Configured"
            response["database_name"] = db.name if hasattr(db, 'name') else "✅ Connected"
            response["connection_status"] = "Connected"
            
            # Try to list collections to verify connectivity
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]  # Show first 10 collections
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
            
    except ImportError:
        response["database"] = "❌ Database module not found (run enable-database first)"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"
    
    # Check environment variables
    import os
    response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
    response["database_name"] = "✅ Set" if os.getenv("DATABASE_NAME") else "❌ Not Set"
    
    return response


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
