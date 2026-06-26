"""
LLM-ready web scraping pipeline.

Primary entry point for n8n, CLI, or programmatic use:

    from main import scrape
    result = scrape("https://example.com/course")
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from cleaner import clean_html, extract_markdown, extract_text
from metadata import extract_metadata
from scraper import PageFetchError, fetch_rendered_html
from utils import (
    compute_statistics,
    format_bytes,
    save_clean_html,
    save_json,
    save_original_html,
    setup_logging,
    slugify_url,
)

# Re-export bonus helpers for n8n / API consumers
__all__ = [
    "scrape",
    "PageFetchError",
    "fetch_rendered_html",
    "extract_metadata",
    "clean_html",
    "extract_text",
    "extract_markdown",
    "compute_statistics",
    "save_clean_html",
    "save_original_html",
    "save_json",
]

logger = logging.getLogger("scraper.main")


def scrape(
    url: str,
    *,
    headless: bool = True,
    timeout_ms: int = 60_000,
    max_retries: int = 3,
) -> dict[str, Any]:
    """
    Scrape a URL and return cleaned HTML plus extracted metadata.

    Args:
        url: Target page URL (training/course page or any content page).
        headless: Run Chromium headless (default True).
        timeout_ms: Playwright timeout in milliseconds.
        max_retries: Number of fetch attempts before failing.

    Returns:
        Dictionary with keys: metadata, clean_html, stats.

    Raises:
        PageFetchError: If the page cannot be rendered after retries.
    """
    logger.info("Scraping URL: %s", url)

    original_html = fetch_rendered_html(
        url,
        headless=headless,
        timeout_ms=timeout_ms,
        max_retries=max_retries,
    )

    metadata = extract_metadata(original_html)
    metadata["source_url"] = url

    cleaned = clean_html(original_html)
    stats = compute_statistics(original_html, cleaned)

    result: dict[str, Any] = {
        "metadata": metadata,
        "clean_html": cleaned,
        "original_html": original_html,
        "stats": stats,
    }

    logger.info(
        "Scrape complete: %s -> %s (%.1f%% reduction)",
        format_bytes(stats["original_size"]),
        format_bytes(stats["clean_size"]),
        stats["reduction_percent"],
    )
    return result


def run_cli(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Scrape and clean a webpage for LLM extraction."
    )
    parser.add_argument("url", help="URL to scrape")
    parser.add_argument(
        "-o",
        "--output",
        default="output",
        help="Output directory (default: output/)",
    )
    parser.add_argument(
        "--save-original",
        action="store_true",
        help="Also save the original rendered HTML",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Also save extracted markdown",
    )
    parser.add_argument(
        "--text",
        action="store_true",
        help="Also save extracted plain text",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    args = parser.parse_args(argv)

    setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    output_dir = Path(args.output)

    try:
        result = scrape(args.url)
    except PageFetchError as exc:
        logger.error("%s", exc)
        return 1
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        return 1

    stats = result["stats"]
    slug = slugify_url(args.url)

    save_clean_html(result["clean_html"], output_dir, f"{slug}_clean.html")
    # Exclude bulky original HTML from JSON artifact by default
    json_payload = {k: v for k, v in result.items() if k != "original_html"}
    save_json(json_payload, output_dir, f"{slug}_result.json")

    if args.save_original:
        save_original_html(result["original_html"], output_dir, f"{slug}_original.html")

    if args.markdown:
        md_path = output_dir / f"{slug}_clean.md"
        output_dir.mkdir(parents=True, exist_ok=True)
        md_path.write_text(extract_markdown(result["clean_html"]), encoding="utf-8")

    if args.text:
        txt_path = output_dir / f"{slug}_clean.txt"
        output_dir.mkdir(parents=True, exist_ok=True)
        txt_path.write_text(extract_text(result["clean_html"]), encoding="utf-8")

    print(f"Original HTML: {format_bytes(stats['original_size'])}")
    print(f"Clean HTML: {format_bytes(stats['clean_size'])}")
    print(f"Reduction: {stats['reduction_percent']:.0f}%")
    print(f"Saved to {output_dir.resolve()}/")
    return 0


def main() -> None:
    """Script entry point."""
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
