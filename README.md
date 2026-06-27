# LLM-Ready Course Web Scraper API

A production-ready web scraping API that renders JavaScript-heavy websites using Playwright, extracts structured metadata, and produces clean, LLM-optimized HTML for downstream information extraction.

The project is designed primarily for AI workflows, allowing Large Language Models to accurately extract information such as course prerequisites, curriculum, duration, instructors, certificates, learning outcomes, pricing, and other educational content from modern training websites.

---

# Features

* JavaScript rendering using Playwright (Chromium)
* FastAPI REST API
* Production deployment on Railway
* Compatible with n8n workflows
* Intelligent DOM cleaning while preserving semantic content
* Metadata extraction
* JSON-LD extraction
* Open Graph extraction
* Schema.org extraction
* Canonical URL extraction
* HTML optimization for LLM consumption
* Plain text extraction
* Markdown extraction
* Automatic retry mechanism
* Lazy-loaded content support
* Content statistics
* Modular architecture

---

# Technology Stack

* Python 3.12+
* FastAPI
* Playwright
* BeautifulSoup4
* lxml
* Readability-lxml
* html5lib
* Uvicorn
* Railway

---

# Installation

Clone the repository

```bash
git clone <repository-url>

cd scraper
```

Create a virtual environment

```bash
python -m venv .venv
```

Activate it

Windows

```bash
.venv\Scripts\activate
```

Linux / macOS

```bash
source .venv/bin/activate
```

Install dependencies

```bash
pip install -r requirements.txt
```

Install Playwright browser

```bash
playwright install chromium
```

---

# Running Locally

Start the API

```bash
uvicorn app:app --reload
```

The API will be available at

```
http://127.0.0.1:8000
```

Swagger Documentation

```
http://127.0.0.1:8000/docs
```

---

# Production Deployment

The application is containerized using Docker and deployed on Railway.

The deployment automatically:

* Builds the Docker image
* Installs Python dependencies
* Uses the Playwright base image
* Starts the FastAPI server using Uvicorn

This is the URL: "https://n8n-scraper-production.up.railway.app/"
---

# API Endpoints

## Health Check

```
GET /
```

Response

```json
{
  "status": "online",
  "service": "LLM Ready Scraper API"
}
```

---

## Scrape a Webpage

```
POST /scrape
```

Request

```json
{
  "url": "https://www.coursera.org/learn/machine-learning"
}
```

Example Response

```json
{
    "metadata": {
        "title": "...",
        "page_title": "...",
        "meta_description": "...",
        "canonical_url": "...",
        "language": "...",
        "json_ld": [...],
        "schema_org": [...],
        "source_url": "..."
    },

    "clean_html": "<article>...</article>",

    "stats": {
        "original_size": 4123856,
        "clean_size": 694231,
        "reduction_percent": 83.17
    }
}
```

---

# Project Architecture

```
scraper/

│
├── app.py             # FastAPI application
├── main.py            # Main scraping pipeline
├── scraper.py         # Playwright renderer
├── cleaner.py         # DOM cleaning and optimization
├── metadata.py        # Metadata extraction
├── utils.py           # Utility functions
├── requirements.txt
├── Dockerfile
└── README.md
```

---

# Scraping Pipeline

## 1. Render

* Launch Chromium
* Execute JavaScript
* Wait for network idle
* Trigger lazy loading

↓

## 2. Extract Metadata

* Page title
* Description
* Open Graph
* Canonical URL
* JSON-LD
* Schema.org

↓

## 3. Clean HTML

Remove only unnecessary website chrome such as:

* Headers
* Footers
* Navigation menus
* Cookie banners
* Login/Register popups
* Chat widgets
* Advertisements
* Tracking scripts
* Analytics scripts

Preserve important educational content including:

* Course descriptions
* Prerequisites
* Learning outcomes
* Skills
* Curriculum
* Modules
* FAQ
* Pricing
* Reviews
* Ratings
* Certificates
* Instructor information
* Requirements
* Images
* Tables
* Lists
* Semantic HTML structure

↓

## 4. Optimize

* Remove unnecessary attributes
* Normalize whitespace
* Preserve semantic tags
* Reduce token count while maximizing useful information

↓

## 5. Return

Return

* Metadata
* Clean HTML
* Statistics

---

# n8n Integration

Use an HTTP Request node.

Method

```
POST
```

URL

```
https://YOUR-RAILWAY-DOMAIN/scrape
```

Headers

```
Content-Type: application/json
```

Body

```json
{
    "url": "{{$json.url}}"
}
```

The API returns cleaned HTML ready to be passed directly into an LLM node for structured information extraction.

---

# Output Format

```python
{
    "metadata": {...},
    "clean_html": "...",
    "stats": {
        "original_size": int,
        "clean_size": int,
        "reduction_percent": float
    }
}
```

---

# Error Handling

The scraper includes:

* Automatic retries
* Exponential backoff
* Playwright timeout handling
* HTTP status validation
* JavaScript rendering failure detection
* Structured API error responses

---

# Primary Use Cases

* AI-powered course prerequisite extraction
* Educational platform indexing
* Knowledge base generation
* LLM preprocessing
* RAG pipelines
* n8n automation workflows
* Training catalog aggregation
* Structured information extraction from modern educational websites

---

# License

MIT License
