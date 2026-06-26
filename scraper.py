"""Playwright-based page fetching with retries and full JS rendering."""

from __future__ import annotations

import logging
import time
from typing import Any

from playwright.sync_api import Browser, Page, Playwright, sync_playwright

from utils import (
    DEFAULT_TIMEOUT_MS,
    DEFAULT_USER_AGENT,
    DEFAULT_VIEWPORT,
    MAX_RETRIES,
    NETWORK_IDLE_WAIT,
    RETRY_BACKOFF_SECONDS,
)

logger = logging.getLogger("scraper.fetcher")


class PageFetchError(Exception):
    """Raised when a page cannot be fetched after all retries."""


def _configure_page(page: Page) -> None:
    """Apply realistic browser settings to a Playwright page."""
    page.set_viewport_size(DEFAULT_VIEWPORT)
    page.set_extra_http_headers(
        {
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
    )


def _wait_for_page_ready(page: Page, timeout_ms: int) -> None:
    """Wait until the page is fully loaded and network is idle."""
    page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    page.wait_for_load_state("load", timeout=timeout_ms)
    try:
        page.wait_for_load_state(NETWORK_IDLE_WAIT, timeout=timeout_ms)
    except Exception:
        # Some SPAs never reach networkidle; load state is sufficient fallback.
        logger.debug("networkidle not reached; continuing with loaded DOM")


def fetch_rendered_html(
    url: str,
    *,
    headless: bool = True,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    max_retries: int = MAX_RETRIES,
) -> str:
    """
    Launch Playwright, render JavaScript, and return the final DOM HTML.

    Uses Chromium in headless mode with a realistic user-agent, viewport,
    timeout handling, networkidle wait, and automatic retries.
    """
    last_error: Exception | None = None

    for attempt in range(1, max_retries + 1):
        playwright: Playwright | None = None
        browser: Browser | None = None
        try:
            logger.info("Fetching %s (attempt %d/%d)", url, attempt, max_retries)
            playwright = sync_playwright().start()
            browser = playwright.chromium.launch(headless=headless)
            context = browser.new_context(
                user_agent=DEFAULT_USER_AGENT,
                viewport=DEFAULT_VIEWPORT,
                java_script_enabled=True,
            )
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            _configure_page(page)

            response = page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            if response and response.status >= 400:
                raise PageFetchError(f"HTTP {response.status} for {url}")

            _wait_for_page_ready(page, timeout_ms)

            # Scroll to trigger lazy-loaded content
            page.evaluate(
                """async () => {
                    await new Promise((resolve) => {
                        let total = 0;
                        const step = window.innerHeight;
                        const timer = setInterval(() => {
                            window.scrollBy(0, step);
                            total += step;
                            if (total >= document.body.scrollHeight) {
                                clearInterval(timer);
                                window.scrollTo(0, 0);
                                resolve();
                            }
                        }, 150);
                    });
                }"""
            )
            page.wait_for_timeout(500)
            _wait_for_page_ready(page, timeout_ms)

            html = page.content()
            context.close()
            browser.close()
            playwright.stop()

            if not html or len(html.strip()) < 100:
                raise PageFetchError(f"Rendered HTML too short for {url}")

            logger.info("Fetched %d bytes of rendered HTML from %s", len(html), url)
            return html

        except Exception as exc:
            last_error = exc
            logger.warning("Attempt %d failed for %s: %s", attempt, url, exc)
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            if playwright:
                try:
                    playwright.stop()
                except Exception:
                    pass
            if attempt < max_retries:
                sleep_for = RETRY_BACKOFF_SECONDS * attempt
                logger.info("Retrying in %.1fs...", sleep_for)
                time.sleep(sleep_for)

    raise PageFetchError(f"Failed to fetch {url} after {max_retries} attempts: {last_error}")


def fetch_page_info(url: str, **kwargs: Any) -> dict[str, str]:
    """Convenience wrapper returning URL and rendered HTML."""
    html = fetch_rendered_html(url, **kwargs)
    return {"url": url, "html": html}
