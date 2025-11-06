import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
import requests

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
