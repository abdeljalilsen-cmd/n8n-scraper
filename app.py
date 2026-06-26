from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from main import scrape, PageFetchError

app = FastAPI(
    title="LLM Ready Scraper API",
    version="1.0.0"
)


class ScrapeRequest(BaseModel):
    url: str


@app.get("/")
def root():
    return {
        "status": "online",
        "service": "LLM Ready Scraper API"
    }


@app.post("/scrape")
def scrape_url(request: ScrapeRequest):
    try:
        result = scrape(request.url)

        # Don't return original HTML (too large)
        result.pop("original_html", None)

        return result

    except PageFetchError as e:
        raise HTTPException(status_code=400, detail=str(e))

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))