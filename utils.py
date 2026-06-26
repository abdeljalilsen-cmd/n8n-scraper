"""Shared utilities, constants, and helper functions for the scraping pipeline."""

from __future__ import annotations

import json
import logging
import re
from html import unescape
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

DEFAULT_VIEWPORT: dict[str, int] = {"width": 1920, "height": 1080}

DEFAULT_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

DEFAULT_TIMEOUT_MS: int = 60_000
NETWORK_IDLE_WAIT: str = "networkidle"
MAX_RETRIES: int = 3
RETRY_BACKOFF_SECONDS: float = 2.0

# Tags removed entirely during cleaning.
# Only truly useless media/scripting/tracking tags are listed here.
# Structural tags like nav, aside, footer, form are handled by heuristics
# in cleaner.py so that course-relevant content inside them is preserved.
REMOVE_TAGS: frozenset[str] = frozenset(
    {
        "script",
        "style",
        "noscript",
        "svg",
        "canvas",
        "iframe",
        "picture",
        "source",
        "video",
        "audio",
        "template",
        "link",
        "meta",
        "object",
        "embed",
    }
)

# Semantic tags preserved in the final output
SEMANTIC_TAGS: frozenset[str] = frozenset(
    {
        "main",
        "article",
        "section",
        "div",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "span",
        "ul",
        "ol",
        "li",
        "table",
        "thead",
        "tbody",
        "tr",
        "td",
        "th",
        "strong",
        "b",
        "em",
        "blockquote",
        "pre",
        "code",
        "img",
        "a",
        "figure",
        "figcaption",
        "dl",
        "dt",
        "dd",
        "br",
        "hr",
    }
)

# Attributes kept on surviving elements.
# Keep structural, semantic, microdata, and accessibility attributes.
# Inline event handlers, style, tracking attrs, and integrity attrs are dropped.
ALLOWED_ATTRIBUTES: frozenset[str] = frozenset(
    {
        # Links and media
        "href",
        "src",
        "alt",
        "title",
        # Accessibility
        "aria-label",
        "aria-expanded",
        "aria-controls",
        "aria-describedby",
        "aria-hidden",
        "role",
        # Identity / anchoring
        "id",
        "name",
        # Dates
        "datetime",
        # Microdata / Schema.org
        "content",
        "itemprop",
        "itemscope",
        "itemtype",
        # Table layout
        "colspan",
        "rowspan",
        # Language
        "lang",
        # Form semantics (kept for enrollment/price info)
        "type",
        "value",
        "placeholder",
        # data-* attributes are handled separately in _strip_attributes()
    }
)

# Heuristic patterns for website chrome / boilerplate removal.
# Only UNAMBIGUOUS identifiers are listed here — things that are almost
# never used for actual course content. Broad terms like 'sidebar',
# 'register', 'modal', 'login' are intentionally excluded because many
# education websites use those class names for course-relevant sections.
CHROME_KEYWORDS: tuple[str, ...] = (
    # Cookie / GDPR banners
    "cookiebanner",
    "cookie-banner",
    "cookie-consent",
    "cookieconsent",
    "gdpr-banner",
    "gdpr-notice",
    "consent-banner",
    # Ads
    "ad-container",
    "ad-slot",
    "ad-unit",
    "banner-ad",
    "google-ad",
    "doubleclick",
    # Floating / fixed widgets
    "back-to-top",
    "backtotop",
    "scroll-to-top",
    "floating-button",
    "chat-widget",
    "live-chat-widget",
    "intercom-container",
    "intercom-lightweight-app",
    "crisp-client",
    "zopim",
    "zendesk-widget",
    # Site-level navigation chrome
    "site-header",
    "site-footer",
    "mega-menu",
    "main-nav",
    "top-nav",
    "global-nav",
    "global-header",
    "global-footer",
    "skip-link",
    "skip-to-content",
    # Social share toolbars
    "social-share",
    "share-toolbar",
    "addthis",
    "sharethis",
)

# ARIA roles that indicate website chrome.
# 'complementary' (aside) and 'toolbar' are intentionally excluded because
# many course pages place the syllabus/enrollment widget in an aside.
CHROME_ROLES: frozenset[str] = frozenset(
    {
        "navigation",
        "banner",
        "search",
        "dialog",
        "alertdialog",
        "contentinfo",
    }
)

# Only match truly invisible styles. position:fixed and position:absolute
# are intentionally excluded — they are used by many sticky course-info
# panels and enrollment widgets that are not hidden from the user.
HIDDEN_STYLE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"display\s*:\s*none", re.I),
    re.compile(r"visibility\s*:\s*hidden", re.I),
    re.compile(r"opacity\s*:\s*0\b", re.I),
)

NEWSLETTER_TEXT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"subscribe\s+to\s+(our\s+)?newsletter", re.I),
    re.compile(r"sign\s+up\s+for\s+(our\s+)?newsletter", re.I),
    re.compile(r"receive\s+email\s+from", re.I),
    re.compile(r"get\s+the\s+latest\s+updates", re.I),
)

WHITESPACE_RE = re.compile(r"[ \t]+")
MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
DUPLICATE_BLANK_RE = re.compile(r"(\s*\n){2,}")


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure and return the package logger."""
    logger = logging.getLogger("scraper")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        logger.addHandler(handler)
    logger.setLevel(level)
    return logger


def format_bytes(num_bytes: int) -> str:
    """Return a human-readable byte size string."""
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024**2:
        return f"{num_bytes / 1024:.1f} KB"
    if num_bytes < 1024**3:
        return f"{num_bytes / 1024**2:.1f} MB"
    return f"{num_bytes / 1024**3:.1f} GB"


def compute_statistics(original_html: str, clean_html: str) -> dict[str, Any]:
    """Compute size reduction statistics between original and cleaned HTML."""
    original_size = len(original_html.encode("utf-8"))
    clean_size = len(clean_html.encode("utf-8"))
    if original_size == 0:
        reduction = 0.0
    else:
        reduction = round((1 - clean_size / original_size) * 100, 2)
    return {
        "original_size": original_size,
        "clean_size": clean_size,
        "reduction_percent": reduction,
    }


def save_clean_html(clean_html: str, output_dir: Path, filename: str = "clean.html") -> Path:
    """Write cleaned HTML to disk."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    path.write_text(clean_html, encoding="utf-8")
    return path


def save_original_html(html: str, output_dir: Path, filename: str = "original.html") -> Path:
    """Write the original rendered HTML to disk."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    path.write_text(html, encoding="utf-8")
    return path


def save_json(data: dict[str, Any], output_dir: Path, filename: str = "result.json") -> Path:
    """Serialize pipeline result to JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / filename
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def normalize_text(text: str) -> str:
    """Normalize whitespace and decode HTML entities in plain text."""
    if not text:
        return ""
    text = unescape(text)
    text = WHITESPACE_RE.sub(" ", text)
    return text.strip()


def collapse_whitespace_in_html(html: str) -> str:
    """Collapse redundant whitespace while preserving tag structure."""
    html = WHITESPACE_RE.sub(" ", html)
    html = MULTI_NEWLINE_RE.sub("\n\n", html)
    return html.strip()


def slugify_url(url: str) -> str:
    """Create a filesystem-safe slug from a URL."""
    slug = re.sub(r"^https?://", "", url)
    slug = re.sub(r"[^\w\-.]+", "_", slug)
    return slug[:120] or "page"
