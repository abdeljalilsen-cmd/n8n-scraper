"""Conservative HTML cleaning for LLM-ready semantic content.

The goal is to preserve the maximum amount of course/training information
while removing only definitive website chrome (ads, cookie banners, chat
widgets, global nav, etc.).  We intentionally prefer false negatives
(keeping some chrome) over false positives (deleting course content).
"""

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

# Popup/overlay keywords used to decide whether a hidden element is noise.
POPUP_KEYWORDS: frozenset[str] = frozenset(
    {
        "cookie",
        "consent",
        "gdpr",
        "modal",
        "popup",
        "overlay",
        "dialog",
        "newsletter",
        "subscribe",
        "intercom",
        "crisp",
        "zendesk",
        "livechat",
        "chat-widget",
    }
)

# Ad identifiers — tight patterns only.
AD_TAG_NAMES: frozenset[str] = frozenset({"ins", "advertisement"})
AD_ATTR_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bad-slot\b", re.I),
    re.compile(r"\bad-unit\b", re.I),
    re.compile(r"\bad-container\b", re.I),
    re.compile(r"\bbanner-ad\b", re.I),
    re.compile(r"\bgoogle-ad\b", re.I),
    re.compile(r"\bdoubleclick\b", re.I),
)

# Tags that are renamed but kept (structure preserved, tag name normalised).
TAG_REPLACEMENTS: dict[str, str] = {
    "hgroup": "div",
    "address": "div",
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
    # details/summary are kept as-is (accordion/expandable sections)
}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _normalize_tag_attrs(soup: BeautifulSoup) -> None:
    """Ensure every tag has a dict attrs mapping (lxml can yield None)."""
    for tag in soup.find_all(True):
        if tag.attrs is None:
            tag.attrs = {}


def _tag_attr(tag: Tag, key: str, default: str = "") -> str:
    """Safely read a tag attribute as a string."""
    attrs = tag.attrs or {}
    value = attrs.get(key, default)
    if isinstance(value, list):
        return " ".join(str(v) for v in value)
    return str(value) if value is not None else default


def _attribute_blob(tag: Tag) -> str:
    """Concatenate all attribute names and values for heuristic matching."""
    attrs = tag.attrs or {}
    parts: list[str] = []
    for key, value in attrs.items():
        parts.append(str(key))
        if isinstance(value, list):
            parts.append(" ".join(str(v) for v in value))
        else:
            parts.append(str(value))
    return " ".join(parts).lower()


# ---------------------------------------------------------------------------
# Text-density heuristic
# ---------------------------------------------------------------------------


def _text_density(tag: Tag) -> dict[str, float]:
    """
    Return a dict of signals used to distinguish content from chrome.

    High text_len + low link_ratio  → likely content
    Low  text_len + high link_ratio → likely navigation / chrome
    """
    text = normalize_text(tag.get_text())
    links = tag.find_all("a")
    descendants = tag.find_all(True)
    headings = tag.find_all(["h1", "h2", "h3", "h4", "h5", "h6"])
    desc_count = len(descendants)
    return {
        "text_len": float(len(text)),
        "link_count": float(len(links)),
        "descendant_count": float(desc_count),
        "heading_count": float(len(headings)),
        "link_ratio": len(links) / max(desc_count, 1),
    }


def _is_nav_like(tag: Tag) -> bool:
    """
    Return True only when a tag looks like a pure navigation bar.

    Criteria (all must hold):
    - Very little visible text  (< 200 chars)
    - High proportion of link descendants  (> 50 %)
    - No headings
    """
    density = _text_density(tag)
    return (
        density["text_len"] < 200
        and density["link_ratio"] > 0.5
        and density["heading_count"] == 0
    )


# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def _is_ad_container(tag: Tag) -> bool:
    """Detect advertisement containers via tag name and tight attribute patterns."""
    if tag.name in AD_TAG_NAMES:
        return True
    blob = _attribute_blob(tag)
    return any(p.search(blob) for p in AD_ATTR_PATTERNS)


def _matches_chrome_keyword(tag: Tag) -> bool:
    """Return True if the tag's attributes mention any chrome keyword."""
    blob = _attribute_blob(tag)
    return any(keyword in blob for keyword in CHROME_KEYWORDS)


def _is_popup_element(tag: Tag) -> bool:
    """Return True if the tag looks like a popup/overlay/banner."""
    blob = _attribute_blob(tag)
    return any(kw in blob for kw in POPUP_KEYWORDS)


def _is_chrome_element(tag: Tag) -> bool:
    """
    Heuristically decide whether a tag is website chrome to be removed.

    Rules (in order):
    1. Always remove ad containers.
    2. Always remove elements with a chrome ARIA role.
    3. Elements matching chrome keywords are only removed when they also
       look like navigation (low text, high link ratio).
    4. Fixed-position overlays with popup keywords → remove.
    5. <nav> and <header> → remove only if they are nav-like.
    6. <footer> → remove only if very short text (< 300 chars).
    7. Everything else → keep.
    """
    if not isinstance(tag, Tag):
        return False

    # 1. Hard ad removal
    if _is_ad_container(tag):
        return True

    # 2. Chrome ARIA roles
    role = _tag_attr(tag, "role").lower()
    if role in CHROME_ROLES:
        return True

    # 3. Chrome keywords — remove if element is nav-like (link-heavy bar)
    #    OR if it is a popup/banner (cookie, consent, chat widgets, etc.)
    if _matches_chrome_keyword(tag):
        if _is_nav_like(tag) or _is_popup_element(tag):
            return True

    # 4. Fixed-position overlays that also carry popup keywords
    style = _tag_attr(tag, "style").lower().replace(" ", "")
    if "position:fixed" in style and _is_popup_element(tag):
        return True

    # 5. <nav> / <header> — remove only when they are pure navigation bars
    if tag.name in {"nav", "header"} and _is_nav_like(tag):
        return True

    # 6. <footer> — remove when very short (global footer chrome),
    #    but keep large footers that may contain instructor / legal / price info
    if tag.name == "footer":
        density = _text_density(tag)
        if density["text_len"] < 300:
            return True

    return False


def _is_hidden_noise(tag: Tag) -> bool:
    """
    Return True only for hidden elements that are clearly noise.

    We no longer remove every hidden element because many course pages
    use display:none / hidden classes for accordion/tab panels that
    contain syllabus, FAQ, and module descriptions.

    We remove a hidden element only when it is both:
    - invisible via CSS  AND
    - looks like a popup / overlay / banner
    """
    style = _tag_attr(tag, "style")
    css_hidden = any(pattern.search(style) for pattern in HIDDEN_STYLE_PATTERNS)
    if not css_hidden:
        return False

    # Only remove if it also looks like a popup/noise element
    return _is_popup_element(tag)


# ---------------------------------------------------------------------------
# Removal passes
# ---------------------------------------------------------------------------


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

    for tag in list(soup.find_all(_is_ad_container)):
        tag.decompose()


def _remove_comments(soup: BeautifulSoup) -> None:
    """Strip HTML comments."""
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()


def _remove_newsletter_by_text(soup: BeautifulSoup) -> None:
    """
    Remove newsletter signup blocks detected by visible text patterns.

    Threshold is kept tight (< 150 chars) so that longer sections
    mentioning subscriptions in a course context are not removed.
    """
    for tag in list(soup.find_all(True)):
        text = normalize_text(tag.get_text())
        if len(text) > 150:
            continue
        if any(pattern.search(text) for pattern in NEWSLETTER_TEXT_PATTERNS):
            tag.decompose()


def _remove_chrome(soup: BeautifulSoup) -> None:
    """Remove website chrome using the conservative multi-signal heuristic."""
    # Two passes are enough; decomposing parents already eliminates children.
    for _ in range(2):
        for tag in list(soup.find_all(True)):
            if _is_chrome_element(tag):
                tag.decompose()


def _remove_hidden_noise(soup: BeautifulSoup) -> None:
    """
    Remove hidden elements that are clearly popups / overlays.

    We intentionally keep hidden accordion/tab sections, because they
    often contain course syllabus and FAQ content.
    """
    for tag in list(soup.find_all(True)):
        if _is_hidden_noise(tag):
            tag.decompose()


# ---------------------------------------------------------------------------
# Attribute stripping
# ---------------------------------------------------------------------------


def _strip_attributes(soup: BeautifulSoup) -> None:
    """
    Keep whitelisted attributes and all data-* attributes.

    Drops: inline event handlers, style, nonce, integrity, crossorigin,
           and any tracking attribute not in ALLOWED_ATTRIBUTES.
    """
    for tag in soup.find_all(True):
        attrs = dict(tag.attrs or {})
        tag.attrs = attrs
        for attr in list(attrs.keys()):
            # Keep all data-* attributes (used by many frameworks for
            # course metadata, accordion state, pricing info, etc.)
            if attr.startswith("data-"):
                continue
            if attr not in ALLOWED_ATTRIBUTES:
                del tag[attr]


# ---------------------------------------------------------------------------
# Structural normalisation
# ---------------------------------------------------------------------------


def _normalize_semantic_tags(soup: BeautifulSoup) -> None:
    """Map non-semantic tags to allowed equivalents or unwrap them."""
    for tag in list(soup.find_all(True)):
        name = tag.name
        if name in SEMANTIC_TAGS:
            continue
        if name in TAG_REPLACEMENTS:
            tag.name = TAG_REPLACEMENTS[name]
            continue
        if name in {"body", "html", "head"}:
            tag.unwrap()
            continue
        # Keep details/summary as semantic expandable sections
        if name in {"details", "summary"}:
            continue
        # Unknown tags: unwrap but keep text
        tag.unwrap()


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


# ---------------------------------------------------------------------------
# Content deduplication
# ---------------------------------------------------------------------------


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
    """
    Remove short repeated link texts typical of navigation menus.

    Threshold raised to 6 repetitions (was 4) to avoid killing
    legitimate section labels that appear several times on course pages.
    """
    counter: Counter[str] = Counter()
    for a in soup.find_all("a"):
        text = normalize_text(a.get_text())
        if 0 < len(text) <= 30:
            counter[text.lower()] += 1

    repeated = {text for text, count in counter.items() if count >= 6}
    if not repeated:
        return

    for a in list(soup.find_all("a")):
        text = normalize_text(a.get_text()).lower()
        if text in repeated and len(normalize_text(a.get_text())) <= 30:
            parent = a.parent
            a.decompose()
            if parent and _is_empty_node(parent):
                parent.decompose()


# ---------------------------------------------------------------------------
# Empty-node cleanup
# ---------------------------------------------------------------------------


def _is_empty_node(tag: Tag) -> bool:
    """Return True if a tag has no meaningful text or useful media."""
    if tag.name in {"img", "br", "hr", "details", "summary"}:
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
    """Unwrap div/span wrappers that contain exactly one semantic child."""
    changed = True
    while changed:
        changed = False
        for tag in list(soup.find_all(["div", "span"])):
            if _tag_attr(tag, "itemprop") or _tag_attr(tag, "itemscope"):
                continue
            children = [
                child
                for child in tag.children
                if not (isinstance(child, NavigableString) and not str(child).strip())
            ]
            if (
                len(children) == 1
                and isinstance(children[0], Tag)
                and children[0].name in SEMANTIC_TAGS
            ):
                tag.unwrap()
                changed = True


# ---------------------------------------------------------------------------
# Main content root detection
# ---------------------------------------------------------------------------


def _find_main_content_root(soup: BeautifulSoup) -> Tag | None:
    """
    Locate the primary content container of the page.

    Priority order:
      1. <main>
      2. <article>
      3. [role="main"]
      4. Largest content block by text length among <div> / <section>
    """
    main = soup.find("main")
    if main and isinstance(main, Tag):
        return main

    article = soup.find("article")
    if article and isinstance(article, Tag):
        return article

    role_main = soup.find(attrs={"role": "main"})
    if role_main and isinstance(role_main, Tag):
        return role_main

    # Fallback: largest block by visible text length
    best: Tag | None = None
    best_len = 0
    for tag in soup.find_all(["div", "section"]):
        text_len = len(normalize_text(tag.get_text()))
        if text_len > best_len:
            best_len = text_len
            best = tag

    return best if best_len > 200 else None


# ---------------------------------------------------------------------------
# Document wrapper
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


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
    Conservatively clean HTML while preserving semantic course/page content.

    Applies tag removal, chrome heuristics (with text-density guards),
    selective hidden-element removal, attribute stripping (preserving
    data-* and microdata attrs), semantic normalisation, text cleaning,
    and deduplication.

    The priority is to maximise useful semantic content for downstream
    LLM extraction rather than to achieve the smallest possible HTML.
    """
    logger.info("Starting HTML cleaning (%d bytes input)", len(html))
    if use_readability:
        html = apply_readability(html)

    soup = BeautifulSoup(html, "lxml")
    _normalize_tag_attrs(soup)

    # Phase 1: Hard removals (scripts, media, ads)
    _remove_comments(soup)
    _remove_document_boilerplate(soup)
    _remove_disallowed_tags(soup)

    # Phase 2: Chrome heuristics (conservative — text-density guarded)
    _remove_chrome(soup)
    _remove_newsletter_by_text(soup)
    _remove_hidden_noise(soup)

    # Phase 3: Attribute cleaning
    _strip_attributes(soup)

    # Phase 4: Structural normalisation
    _normalize_semantic_tags(soup)

    # Phase 5: Content deduplication and cleanup
    _remove_repeated_menu_text(soup)
    _deduplicate_blocks(soup)
    _remove_empty_nodes(soup)
    _collapse_useless_wrappers(soup)
    _normalize_text_nodes(soup)
    _remove_empty_nodes(soup)

    soup = _ensure_document_wrapper(soup)
    output = str(soup)
    output = collapse_whitespace_in_html(output)

    # Emit only body inner HTML
    final = BeautifulSoup(output, "lxml")
    if final.body:
        output = "".join(str(child) for child in final.body.contents)
    else:
        output = final.decode_contents()

    # Drop stray root-level text nodes
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
            elif name in {
                "ul", "ol", "section", "article", "main", "div", "table",
                "tbody", "thead", "details", "summary", "aside", "figure",
            }:
                render(child.children, depth + 1)
            else:
                render(child.children, depth + 1)

    render(soup.children)
    markdown = "\n".join(line for line in ("\n".join(parts)).splitlines() if line.strip())
    return collapse_whitespace_in_html(markdown)
