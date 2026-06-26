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


def _first_meta(
    soup: BeautifulSoup,
    *,
    name: str | None = None,
    prop: str | None = None,
    itemprop: str | None = None,
) -> str | None:
    """Find the first meta tag matching name, property, or itemprop."""
    if name:
        tag = soup.find("meta", attrs={"name": re.compile(rf"^{re.escape(name)}$", re.I)})
        if tag:
            return _meta_content(tag)
    if prop:
        tag = soup.find("meta", attrs={"property": re.compile(rf"^{re.escape(prop)}$", re.I)})
        if tag:
            return _meta_content(tag)
    if itemprop:
        tag = soup.find("meta", attrs={"itemprop": re.compile(rf"^{re.escape(itemprop)}$", re.I)})
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


def _extract_microdata(soup: BeautifulSoup) -> list[dict[str, Any]]:
    """
    Extract Microdata items (itemscope / itemprop) from the DOM.

    Returns a list of dicts, each representing one itemscope root with
    its itemtype and a flat mapping of itemprop → text value.
    """
    items: list[dict[str, Any]] = []
    for root in soup.find_all(attrs={"itemscope": True}):
        if not isinstance(root, Tag):
            continue
        itemtype = root.get("itemtype", "")
        if isinstance(itemtype, list):
            itemtype = " ".join(str(v) for v in itemtype)
        props: dict[str, Any] = {}
        for prop_tag in root.find_all(attrs={"itemprop": True}):
            if not isinstance(prop_tag, Tag):
                continue
            prop_name = prop_tag.get("itemprop", "")
            if isinstance(prop_name, list):
                prop_name = " ".join(str(v) for v in prop_name)
            prop_name = str(prop_name).strip()
            if not prop_name:
                continue
            # Prefer content attribute (meta tags), then href/src, then text
            value: str = ""
            if prop_tag.get("content"):
                value = str(prop_tag["content"]).strip()
            elif prop_tag.get("href"):
                value = str(prop_tag["href"]).strip()
            elif prop_tag.get("src"):
                value = str(prop_tag["src"]).strip()
            else:
                value = prop_tag.get_text(strip=True)
            if value:
                if prop_name in props:
                    existing = props[prop_name]
                    if isinstance(existing, list):
                        existing.append(value)
                    else:
                        props[prop_name] = [existing, value]
                else:
                    props[prop_name] = value
        items.append({"itemtype": str(itemtype), "properties": props})
    return items


def extract_metadata(html: str) -> dict[str, Any]:
    """
    Extract page metadata from raw HTML.

    Collects:
    - Page title and H1 fallback
    - Meta description and keywords
    - Open Graph tags (og:title, og:description, og:image, og:type, og:url)
    - Twitter Card tags
    - Canonical URL and language
    - JSON-LD blocks and flattened schema.org objects
    - Microdata (itemscope / itemprop) items
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
    microdata = _extract_microdata(soup)

    metadata: dict[str, Any] = {
        # Core title
        "title": page_title,
        "page_title": page_title,
        # Standard meta
        "meta_description": _first_meta(soup, name="description"),
        "meta_keywords": _first_meta(soup, name="keywords"),
        # Open Graph
        "og_title": _first_meta(soup, prop="og:title"),
        "og_description": _first_meta(soup, prop="og:description"),
        "og_image": _first_meta(soup, prop="og:image"),
        "og_type": _first_meta(soup, prop="og:type"),
        "og_url": _first_meta(soup, prop="og:url"),
        # Twitter Cards
        "twitter_card": _first_meta(soup, name="twitter:card"),
        "twitter_title": _first_meta(soup, name="twitter:title"),
        "twitter_description": _first_meta(soup, name="twitter:description"),
        "twitter_image": _first_meta(soup, name="twitter:image"),
        # Navigation
        "canonical_url": canonical_url,
        "language": language,
        # Structured data
        "json_ld": json_ld,
        "schema_org": schema_objects,
        "microdata": microdata,
    }

    # Fallback: use first h1 if no title found
    if not metadata["title"]:
        h1 = soup.find("h1")
        if h1:
            metadata["title"] = h1.get_text(strip=True)

    logger.info(
        "Extracted metadata: title=%r, json_ld_blocks=%d, schema_objects=%d, microdata_items=%d",
        metadata.get("title"),
        len(json_ld),
        len(schema_objects),
        len(microdata),
    )
    return metadata
