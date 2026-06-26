# LLM-Ready Web Scraper

Production-quality scraping pipeline that renders JavaScript-heavy pages with Playwright, extracts metadata, and produces aggressively cleaned HTML optimized for LLM information extraction.

## Features

- Full JavaScript rendering via Playwright (Chromium, headless)
- Metadata extraction (title, description, Open Graph, canonical URL, JSON-LD)
- Aggressive DOM cleaning with semantic preservation
- Website chrome removal via multi-signal heuristics
- Token optimization targeting 70%+ size reduction
- Modular architecture for n8n, CLI, or API integration
- Bonus utilities: plain text, markdown, file export, statistics

## Requirements

- Python 3.12+
- Chromium (installed via Playwright)

## Installation

```bash
cd scraper
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
playwright install chromium
```

## Usage

### Python API (n8n / FastAPI)

```python
from main import scrape

result = scrape("https://example.com/course")

print(result["clean_html"])
print(result["metadata"])
print(result["stats"])
```

Or import individual modules:

```python
from scraper import fetch_rendered_html
from metadata import extract_metadata
from cleaner import clean_html, extract_text, extract_markdown
from utils import compute_statistics, save_clean_html, save_json
```

### CLI

```bash
python main.py https://example.com/course
```

With options:

```bash
python main.py https://example.com/course -o output --markdown --text -v
```

Example output:

```
Original HTML: 4.8 MB
Clean HTML: 380 KB
Reduction: 92%
Saved to output/
```

## Output Format

```python
{
    "metadata": {
        "title": "...",
        "page_title": "...",
        "meta_description": "...",
        "og_title": "...",
        "og_description": "...",
        "canonical_url": "...",
        "language": "en",
        "json_ld": [...],
        "schema_org": [...],
        "source_url": "..."
    },
    "clean_html": "<article>...</article>",
    "stats": {
        "original_size": 4800000,
        "clean_size": 380000,
        "reduction_percent": 92.08
    }
}
```

## Pipeline Steps

1. **Fetch** — Playwright renders the page with retries, networkidle wait, and lazy-load scrolling
2. **Metadata** — Extract structured metadata before any DOM mutation
3. **Clean** — Remove scripts, styles, chrome, hidden elements, and non-semantic tags
4. **Optimize** — Strip attributes, deduplicate text, collapse wrappers
5. **Return** — Minimized semantic HTML + metadata + statistics

## n8n Integration

Use an **Execute Command** node:

```bash
cd /path/to/scraper && .venv/bin/python -c "import json; from main import scrape; print(json.dumps(scrape('{{$json.url}}')))"
```

Or wrap `scrape()` in a FastAPI endpoint for HTTP-based integration.

## Project Structure

```
scraper/
    main.py          # scrape() entry point + CLI
    scraper.py       # Playwright fetching
    cleaner.py       # DOM cleaning + text/markdown export
    metadata.py      # Metadata extraction
    utils.py         # Constants, helpers, file I/O
    requirements.txt
    README.md
```

## Error Handling

- Automatic retries with exponential backoff on fetch failures
- `PageFetchError` raised when all retries are exhausted
- JSON-LD parse failures are logged and skipped (non-fatal)

## License

MIT
