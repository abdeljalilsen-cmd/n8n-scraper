"""Aggressive HTML cleaning for LLM-ready semantic content."""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Iterable

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from bs4.element import Doctype

from utils import (
    ALLOWED_ATTRIBUTES,
    CHROME_KEYWORDS,
    CHROME_ROLES,
    HIDDEN_STYLE_PATTERNS,
    NEWSLETTER_TEXT_PATTERNS,
    REMOVE_TAGS,
    SEMANTIC_TAGS,
    collapse_whitespace_in_html,
    normalize_text,
)

logger = logging.getLogger("scraper.cleaner")

AD_KEYWORDS = ("ad", "ads", "advert", "sponsored", "promo", "banner")
TAG_REPLACEMENTS = {
    "header": "section",
    "hgroup": "div",
    "address": "div",
    "details": "div",
    "summary": "div",
    "mark": "span",
    "small": "span",
    "sub": "span",
    "sup": "span",
    "i": "em",
    "cite": "em",
    "q": "span",
    "abbr": "span",
    "time": "span",
    "label": "span",
    "fieldset": "div",
    "legend": "div",
    "output": "span",
    "meter": "span",
    "progress": "span",
    "data": "span",
    "ruby": "span",
    "rt": "span",
    "rp": "span",
    "wbr": "br",
}


def _normalize_tag_attrs(soup: BeautifulSoup) -> None:
    """Ensure every tag has a dict attrs mapping (lxml can yield None)."""
    for tag in soup.find_all(True):
        if tag.attrs is None:
            tag.attrs = {}


def _tag_attr(tag: Tag, key: str, default: str = "") -> str:
    """Safely read a tag attribute."""
    attrs = tag.attrs or {}
    value = attrs.get(key, default)
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value) if value is not None else default


def _attribute_blob(tag: Tag) -> str:
    """Concatenate attribute names and values for heuristic matching."""
    attrs = tag.attrs or {}
    parts: list[str] = []
    for key, value in attrs.items():
        if isinstance(value, list):
            parts.append(" ".join(str(v) for v in value))
        else:
            parts.append(str(value))
        parts.append(str(key))
    return " ".join(parts).lower()


def _is_ad_container(tag: Tag) -> bool:
    """Detect advertisement containers via tag name and attributes."""
    if tag.name in {"ins", "advertisement"}:
        return True
    blob = _attribute_blob(tag)
    return any(re.search(rf"\b{re.escape(keyword)}\b", blob) for keyword in AD_KEYWORDS)


def _is_chrome_element(tag: Tag) -> bool:
    """Heuristically detect layout chrome / boilerplate elements."""
    if not isinstance(tag, Tag):
        return False

    if _is_ad_container(tag):
        return True

    role = _tag_attr(tag, "role").lower()
    if role in CHROME_ROLES:
        return True

    blob = _attribute_blob(tag)
    if any(keyword in blob for keyword in CHROME_KEYWORDS):
        return True

    # Fixed-position overlays often used for popups
    style = _tag_attr(tag, "style").lower()
    if "position:fixed" in style.replace(" ", "") or "position: fixed" in style:
        if any(k in blob for k in ("modal", "popup", "cookie", "consent", "overlay", "dialog")):
            return True

    # Very short nav-like link clusters
    if tag.name in {"nav", "header", "footer"}:
        return True

    aria_hidden = _tag_attr(tag, "aria-hidden").lower()
    if aria_hidden == "true":
        return True

    attrs = tag.attrs or {}
    if "hidden" in attrs:
        return True

    return False


def _is_hidden_element(tag: Tag) -> bool:
    """Detect visually hidden elements."""
    style = _tag_attr(tag, "style")
    if any(pattern.search(style) for pattern in HIDDEN_STYLE_PATTERNS):
        return True

    class_value = _tag_attr(tag, "class")
    classes = class_value.lower()
    hidden_class_tokens = (
        "sr-only",
        "screen-reader",
        "visually-hidden",
        "visuallyhidden",
        "d-none",
        "hidden",
        "invisible",
        "u-hidden",
        "is-hidden",
    )
    if any(token in classes for token in hidden_class_tokens):
        return True

    return _tag_attr(tag, "aria-hidden").lower() == "true"


def _unwrap_tag(tag: Tag) -> None:
    """Replace a tag with its children."""
    tag.unwrap()


def _replace_tag(tag: Tag, new_name: str) -> None:
    """Rename a tag while preserving children."""
    tag.name = new_name


def _remove_document_boilerplate(soup: BeautifulSoup) -> None:
    """Remove head/title elements after metadata has been extracted."""
    for tag_name in ("head", "title", "base"):
        for tag in soup.find_all(tag_name):
            tag.decompose()


def _remove_disallowed_tags(soup: BeautifulSoup) -> None:
    """Delete entire tags that are never useful for LLM extraction."""
    for tag_name in REMOVE_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    for tag in soup.find_all(_is_ad_container):
        tag.decompose()


def _remove_comments(soup: BeautifulSoup) -> None:
    """Strip HTML comments."""
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()


def _remove_newsletter_by_text(soup: BeautifulSoup) -> None:
    """Remove newsletter signup blocks detected by visible text patterns."""
    for tag in list(soup.find_all(True)):
        text = normalize_text(tag.get_text())
        if len(text) > 300:
            continue
        if any(pattern.search(text) for pattern in NEWSLETTER_TEXT_PATTERNS):
            tag.decompose()


def _remove_chrome(soup: BeautifulSoup) -> None:
    """Remove common website chrome using multi-signal heuristics."""
    # Multiple passes because decomposing parents changes the tree
    for _ in range(3):
        for tag in list(soup.find_all(True)):
            if _is_chrome_element(tag):
                tag.decompose()


def _strip_attributes(soup: BeautifulSoup) -> None:
    """Keep only whitelisted attributes on all elements."""
    for tag in soup.find_all(True):
        attrs = dict(tag.attrs or {})
        tag.attrs = attrs
        for attr in list(attrs.keys()):
            if attr not in ALLOWED_ATTRIBUTES:
                del tag[attr]


def _normalize_semantic_tags(soup: BeautifulSoup) -> None:
    """Map non-semantic tags to allowed equivalents or unwrap them."""
    for tag in list(soup.find_all(True)):
        name = tag.name
        if name in SEMANTIC_TAGS:
            continue
        if name in TAG_REPLACEMENTS:
            _replace_tag(tag, TAG_REPLACEMENTS[name])
            continue
        if name in {"body", "html", "head"}:
            _unwrap_tag(tag)
            continue
        # Unknown tags: unwrap but keep text
        _unwrap_tag(tag)


def _remove_hidden_elements(soup: BeautifulSoup) -> None:
    """Remove elements that are hidden from view."""
    for tag in list(soup.find_all(True)):
        if _is_hidden_element(tag):
            tag.decompose()


def _is_empty_node(tag: Tag) -> bool:
    """Return True if a tag has no meaningful text or useful media."""
    if tag.name in {"img", "br", "hr"}:
        return False
    if _tag_attr(tag, "src") or _tag_attr(tag, "href"):
        return False
    text = normalize_text(tag.get_text())
    return not text and not tag.find(["img", "table", "ul", "ol", "pre", "blockquote"])


def _remove_empty_nodes(soup: BeautifulSoup) -> None:
    """Remove empty elements iteratively."""
    changed = True
    while changed:
        changed = False
        for tag in list(soup.find_all(True)):
            if _is_empty_node(tag):
                tag.decompose()
                changed = True


def _collapse_useless_wrappers(soup: BeautifulSoup) -> None:
    """Unwrap div/span wrappers that add no semantic value."""
    changed = True
    while changed:
        changed = False
        for tag in list(soup.find_all(["div", "span"])):
            if _tag_attr(tag, "itemprop"):
                continue
            children = [child for child in tag.children if not (isinstance(child, NavigableString) and not str(child).strip())]
            if len(children) == 1 and isinstance(children[0], Tag) and children[0].name in SEMANTIC_TAGS:
                tag.unwrap()
                changed = True


def _normalize_text_nodes(soup: BeautifulSoup) -> None:
    """Normalize whitespace inside text nodes."""
    for node in soup.find_all(string=True):
        if isinstance(node, (Comment, Doctype)):
            continue
        parent = node.parent
        if parent and parent.name in {"pre", "code"}:
            continue
        cleaned = normalize_text(str(node))
        if cleaned:
            node.replace_with(cleaned)
        else:
            node.extract()


def _deduplicate_blocks(soup: BeautifulSoup) -> None:
    """Remove duplicated paragraphs and list items."""
    seen: set[str] = set()
    for tag in list(soup.find_all(["p", "li", "h1", "h2", "h3", "h4", "h5", "h6"])):
        text = normalize_text(tag.get_text())
        if len(text) < 40:
            continue
        key = text.lower()
        if key in seen:
            tag.decompose()
        else:
            seen.add(key)


def _remove_repeated_menu_text(soup: BeautifulSoup) -> None:
    """Remove short repeated link texts typical of navigation menus."""
    counter: Counter[str] = Counter()
    for a in soup.find_all("a"):
        text = normalize_text(a.get_text())
        if 0 < len(text) <= 30:
            counter[text.lower()] += 1

    repeated = {text for text, count in counter.items() if count >= 4}
    if not repeated:
        return

    for a in list(soup.find_all("a")):
        text = normalize_text(a.get_text()).lower()
        if text in repeated and len(normalize_text(a.get_text())) <= 30:
            parent = a.parent
            a.decompose()
            if parent and _is_empty_node(parent):
                parent.decompose()


def _ensure_document_wrapper(soup: BeautifulSoup) -> BeautifulSoup:
    """Wrap fragments in a minimal html/body structure."""
    if soup.body:
        return soup
    wrapper = BeautifulSoup("<html><body></body></html>", "lxml")
    body = wrapper.body
    assert body is not None
    for child in list(soup.contents):
        body.append(child.extract() if isinstance(child, Tag) else child)
    return wrapper


def apply_readability(html: str) -> str:
    """
    Optionally extract main article HTML using readability-lxml.

    Useful as a pre-cleaning pass on extremely noisy pages.
    """
    try:
        from readability import Document

        document = Document(html)
        summary = document.summary(html_partial=True)
        return summary or html
    except Exception as exc:
        logger.warning("readability extraction failed: %s", exc)
        return html


def clean_html(html: str, *, use_readability: bool = False) -> str:
    """
    Aggressively clean HTML while preserving semantic course/page content.

    Applies tag removal, attribute stripping, chrome heuristics, semantic
    normalization, text cleaning, and token optimization.
    """
    logger.info("Starting HTML cleaning (%d bytes input)", len(html))
    if use_readability:
        html = apply_readability(html)
    soup = BeautifulSoup(html, "lxml")
    _normalize_tag_attrs(soup)

    _remove_comments(soup)
    _remove_document_boilerplate(soup)
    _remove_disallowed_tags(soup)
    _remove_chrome(soup)
    _remove_newsletter_by_text(soup)
    _remove_hidden_elements(soup)
    _normalize_semantic_tags(soup)
    _strip_attributes(soup)
    _remove_repeated_menu_text(soup)
    _deduplicate_blocks(soup)
    _remove_empty_nodes(soup)
    _collapse_useless_wrappers(soup)
    _normalize_text_nodes(soup)
    _remove_empty_nodes(soup)

    soup = _ensure_document_wrapper(soup)
    output = str(soup)
    output = collapse_whitespace_in_html(output)

    # Final pass: emit only body inner HTML for minimal token footprint
    final = BeautifulSoup(output, "lxml")
    if final.body:
        output = "".join(str(child) for child in final.body.contents)
    else:
        output = final.decode_contents()

    # Drop stray root-level text nodes (e.g. leaked title or parser artifacts)
    fragment = BeautifulSoup(f"<div id='__root__'>{output}</div>", "lxml")
    root = fragment.find("div", id="__root__")
    if root:
        for node in list(root.contents):
            if isinstance(node, NavigableString):
                text = normalize_text(str(node))
                if not text or text.lower() in {"html", "head", "body"}:
                    node.extract()
        output = root.decode_contents()

    output = collapse_whitespace_in_html(output)

    logger.info("HTML cleaning complete (%d bytes output)", len(output))
    return output


def extract_text(clean_html: str) -> str:
    """Extract normalized plain text from cleaned HTML."""
    soup = BeautifulSoup(clean_html, "lxml")
    _normalize_text_nodes(soup)
    lines = [normalize_text(line) for line in soup.get_text("\n").splitlines()]
    lines = [line for line in lines if line]
    return "\n".join(lines)


def extract_markdown(clean_html: str) -> str:
    """Convert cleaned HTML into lightweight markdown."""
    soup = BeautifulSoup(clean_html, "lxml")
    parts: list[str] = []

    def render(node: Iterable, depth: int = 0) -> None:
        for child in node:
            if isinstance(child, NavigableString):
                text = normalize_text(str(child))
                if text:
                    parts.append(text)
                continue
            if not isinstance(child, Tag):
                continue

            name = child.name
            if name in {"h1", "h2", "h3", "h4", "h5", "h6"}:
                level = int(name[1])
                text = normalize_text(child.get_text())
                if text:
                    parts.append(f"\n{'#' * level} {text}\n")
            elif name == "p":
                text = normalize_text(child.get_text())
                if text:
                    parts.append(f"\n{text}\n")
            elif name == "li":
                text = normalize_text(child.get_text())
                if text:
                    parts.append(f"\n- {text}")
            elif name == "a":
                text = normalize_text(child.get_text())
                href = child.get("href")
                if text and href:
                    parts.append(f"[{text}]({href})")
                elif text:
                    parts.append(text)
            elif name == "blockquote":
                text = normalize_text(child.get_text())
                if text:
                    parts.append(f"\n> {text}\n")
            elif name in {"pre", "code"}:
                text = child.get_text()
                if text:
                    parts.append(f"\n```\n{text.strip()}\n```\n")
            elif name == "img":
                alt = child.get("alt", "")
                src = child.get("src", "")
                if alt or src:
                    parts.append(f"![{alt}]({src})")
            elif name in {"ul", "ol", "section", "article", "main", "div", "table", "tbody", "thead"}:
                render(child.children, depth + 1)
            else:
                render(child.children, depth + 1)

    render(soup.children)
    markdown = "\n".join(line for line in ("\n".join(parts)).splitlines() if line.strip())
    return collapse_whitespace_in_html(markdown)
