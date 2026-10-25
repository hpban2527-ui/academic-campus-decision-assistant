import random
import re
import time
from datetime import datetime
import dateparser
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from config import (
    LOGIN_POPUP_CLOSE_SELECTORS,
    SEE_MORE_SELECTORS,
    PUBLISHER_SELECTORS,
    DATE_SELECTORS,
    MAX_SCROLLS,
)
from storage import normalize_date


def random_delay(min_sec: float = 1.0, max_sec: float = 2.5):
    """Simulate random human delay to prevent rate-limiting."""
    time.sleep(random.uniform(min_sec, max_sec))


def extract_post_id_from_url(url: str) -> str | None:
    """Extract post_id from various Facebook URL formats."""
    patterns = [
        r"/posts/([a-zA-Z0-9]+)",
        r"story_fbid=([a-zA-Z0-9]+)",
        r"/permalink/([a-zA-Z0-9]+)",
        r"fbid=([a-zA-Z0-9]+)",
        r"/share/p/([a-zA-Z0-9]+)",
        r"/share/v/([a-zA-Z0-9]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def close_login_popup(page: Page) -> bool:
    """Close Facebook login popup (specifically targeting dialogs containing password fields)."""
    for selector in LOGIN_POPUP_CLOSE_SELECTORS:
        try:
            close_btn = page.locator(selector).first
            if close_btn.is_visible(timeout=1500):
                close_btn.click()
                print("  -> Successfully closed login pop-up.", flush=True)
                random_delay(0.5, 1.0)
                return True
        except Exception:
            continue
    return False


def expand_see_more(page: Page) -> int:
    """Click 'See more' / 'Xem thêm' buttons to reveal full post content."""
    clicked = 0
    for selector in SEE_MORE_SELECTORS:
        try:
            buttons = page.locator(selector).all()
            for btn in buttons[:5]:
                try:
                    if btn.is_visible():
                        btn.click(timeout=1500)
                        clicked += 1
                        random_delay(0.2, 0.4)
                except Exception:
                    continue
        except Exception:
            continue
    return clicked


def extract_content(page: Page, article) -> str:
    """Extract post text content, with fallback to avoid capturing footer elements."""
    raw_content = ""
    try:
        content_el = article.locator('[data-ad-preview="message"]').first
        if not content_el.is_visible(timeout=1000):
            content_el = page.locator('[data-ad-preview="message"]').first

        if content_el.is_visible(timeout=1000):
            raw_content = content_el.inner_text()
        else:
            raw_content = article.inner_text()
    except Exception:
        raw_content = article.inner_text()

    raw_content = raw_content.strip()

    # Check if footer text (language selector / privacy policy) was captured accidentally
    if "Tiếng Việt\nEnglish (UK)" in raw_content or "Chính sách quyền riêng tư" in raw_content:
        dialog_el = page.locator('div[role="dialog"]:not(:has(input[type="password"]))').first
        if dialog_el.is_visible():
            msg_el = dialog_el.locator('[data-ad-preview="message"]').first
            if msg_el.is_visible():
                raw_content = msg_el.inner_text().strip()

    return raw_content


def extract_publisher(article) -> str:
    """Extract page or author name."""
    for sel in PUBLISHER_SELECTORS:
        try:
            for el in article.locator(sel).all()[:3]:
                txt = el.inner_text().strip()
                if txt and len(txt) > 2 and "\n" not in txt:
                    return txt
        except Exception:
            continue
    return ""


def extract_date(article, publisher: str) -> str:
    """Extract post publication timestamp string."""
    for sel in DATE_SELECTORS:
        try:
            for el in article.locator(sel).all()[:15]:
                try:
                    txt = el.inner_text().strip()
                    if txt and len(txt) < 35 and not txt.startswith("http") and not txt.isdigit():
                        if publisher and txt in publisher:
                            continue
                        parsed = dateparser.parse(
                            txt,
                            languages=["vi", "en"],
                            settings={"RELATIVE_BASE": datetime.now()},
                        )
                        if parsed:
                            return txt
                except Exception:
                    continue
        except Exception:
            continue
    return ""


def collect_facebook_post (page: Page, url: str) -> dict | None:
    """
    Navigate to a Facebook post URL and extract post data.
    Returns a dictionary containing post details or None if not found/invalid.
    """
    print(f"\n~ Processing: {url}", flush=True)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)
    random_delay(2, 3)

    # 1. Wait for URL redirect (if share link)
    try:
        page.wait_for_url(lambda u: "/share/p/" not in u, timeout=6000)
        print(f"  -> URL after redirect: {page.url}", flush=True)
    except PlaywrightTimeoutError:
        print("  [!] No redirect detected, continuing with current URL.", flush=True)

    current_url = page.url
    post_id = extract_post_id_from_url(current_url) or extract_post_id_from_url(url)
    if not post_id:
        print("  [X] Unable to extract post_id from the URL.", flush=True)
        return None

    print(f"  -> Detect post_id: {post_id}", flush=True)

    # 2. Close login popup
    close_login_popup(page)

    # 3. Expand post text ('See more')
    clicked = expand_see_more(page)
    if clicked:
        print(f"  -> Clicked {clicked} 'Xem thêm'/'See more' buttons.", flush=True)

    # 4. Scroll page to reveal remaining content
    for _ in range(MAX_SCROLLS):
        page.mouse.wheel(0, 600)
        random_delay(0.5, 1.0)

    # 5. Locate post element
    article = page.locator('[role="article"]').first
    if not article.is_visible(timeout=3000):
        article = page.locator('div[role="dialog"]:not(:has(input[type="password"]))').first
        if not article.is_visible(timeout=2000):
            article = page.locator('[role="main"]').first
            if not article.is_visible(timeout=2000):
                print("  [X] Post not found.", flush=True)
                return None

    # 6. Extract post content
    raw_content = extract_content(page, article)

    # 7. Extract publisher name
    publisher = extract_publisher(article)

    # 8. Extract publication date
    raw_date = extract_date(article, publisher)
    date_posted = normalize_date(raw_date)

    result = {
        "post_id": post_id,
        "url": current_url,
        "share_url": url,
        "raw_content": raw_content,
        "publisher": publisher,
        "platform": "Facebook",
        "date_posted": date_posted,
    }

    print(f"  [#] Extracted: {publisher or '(none)'} | {date_posted or '(none)'}", flush=True)
    return result
