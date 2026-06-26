"""Metadata extraction from raw HTML before DOM cleaning."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger("scraper.metadata")

JSON_LD_TYPE = re.compile(r"application/ld\+json", re.I)


def _meta_content(tag: Tag) -> str | None:
    """Return trimmed meta tag content or None."""
    content = tag.get("content")
    if content is None:
        return None
    value = str(content).strip()
    return value or None


def _first_meta(soup: BeautifulSoup, *, name: str | None = None, prop: str | None = None) -> str | None:
    """Find the first meta tag matching name or property."""
    if name:
        tag = soup.find("meta", attrs={"name": re.compile(rf"^{re.escape(name)}$", re.I)})
        if tag:
            return _meta_content(tag)
    if prop:
        tag = soup.find("meta", attrs={"property": re.compile(rf"^{re.escape(prop)}$", re.I)})
        if tag:
            return _meta_content(tag)
    return None


def _extract_json_ld(soup: BeautifulSoup) -> list[Any]:
    """Extract and parse all JSON-LD script blocks."""
    results: list[Any] = []
    for script in soup.find_all("script", type=JSON_LD_TYPE):
        raw = script.string or script.get_text()
        if not raw or not raw.strip():
            continue
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                results.extend(parsed)
            else:
                results.append(parsed)
        except json.JSONDecodeError as exc:
            logger.warning("Failed to parse JSON-LD block: %s", exc)
    return results


def _flatten_schema_objects(json_ld_items: list[Any]) -> list[dict[str, Any]]:
    """Flatten nested @graph structures into a list of schema.org objects."""
    objects: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if isinstance(node, dict):
            if "@graph" in node and isinstance(node["@graph"], list):
                for item in node["@graph"]:
                    visit(item)
            else:
                objects.append(node)
        elif isinstance(node, list):
            for item in node:
                visit(item)

    for item in json_ld_items:
        visit(item)
    return objects


def extract_metadata(html: str) -> dict[str, Any]:
    """
    Extract page metadata from raw HTML.

    Collects title, description, Open Graph fields, canonical URL,
    language, JSON-LD, and flattened schema.org objects.
    """
    soup = BeautifulSoup(html, "lxml")

    title_tag = soup.find("title")
    page_title = title_tag.get_text(strip=True) if title_tag else None

    html_tag = soup.find("html")
    language = None
    if html_tag and html_tag.get("lang"):
        language = str(html_tag["lang"]).strip() or None

    canonical_tag = soup.find("link", rel=lambda v: v and "canonical" in str(v).lower())
    canonical_url = None
    if canonical_tag and canonical_tag.get("href"):
        canonical_url = str(canonical_tag["href"]).strip() or None

    json_ld = _extract_json_ld(soup)
    schema_objects = _flatten_schema_objects(json_ld)

    metadata: dict[str, Any] = {
        "title": page_title,
        "page_title": page_title,
        "meta_description": _first_meta(soup, name="description"),
        "og_title": _first_meta(soup, prop="og:title"),
        "og_description": _first_meta(soup, prop="og:description"),
        "canonical_url": canonical_url,
        "language": language,
        "json_ld": json_ld,
        "schema_org": schema_objects,
    }

    # Fallback: use first h1 if no title found
    if not metadata["title"]:
        h1 = soup.find("h1")
        if h1:
            metadata["title"] = h1.get_text(strip=True)

    logger.info(
        "Extracted metadata: title=%r, json_ld_blocks=%d, schema_objects=%d",
        metadata.get("title"),
        len(json_ld),
        len(schema_objects),
    )
    return metadata
