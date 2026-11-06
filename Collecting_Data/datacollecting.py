import io
import sys
from pathlib import Path

# Fix UTF-8 encoding on Windows console
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from config import DATA_FILE, URLS_FILE, HEADLESS, SIMILARITY_THRESHOLD
from deduplication import PostDeduplicator
from storage import load_urls, load_existing_posts, save_posts
from scraper import collect_facebook_post , random_delay


def main():
    # 1. Load URL list from file
    urls = load_urls(URLS_FILE)
    if not urls:
        print(f"  [!] No URLs found in '{URLS_FILE}'. Please add Facebook URLs to this file.", flush=True)
        return

    print(f"  [#] Loaded {len(urls)} URL(s) from '{URLS_FILE}'.", flush=True)

    # 2. Load existing post records
    existing_posts = load_existing_posts(DATA_FILE)
    existing_ids = {p["post_id"] for p in existing_posts}
    print(f"Loaded {len(existing_posts)} existing post(s) from '{DATA_FILE}'.", flush=True)

    # 3. Initialize MinHash-LSH index for cross-posting/near-duplicate detection
    deduplicator = PostDeduplicator(threshold=SIMILARITY_THRESHOLD)
    indexed_count = 0
    for p in existing_posts:
        pid = p.get("post_id")
        content = p.get("raw_content", "")
        if pid and content and deduplicator.index_post(pid, content):
            indexed_count += 1
    print(f"[#] Indexed {indexed_count} post(s) in LSH for near-duplicate detection.", flush=True)

    new_posts = []

    # 4. Initialize Playwright with stealth mode
    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(
            headless=HEADLESS,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1366, "height": 768},
            locale="vi-VN",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        for url in urls:
            # Check if URL was already collected
            if any(url in p.get("url", "") or url == p.get("share_url") for p in existing_posts):
                print(f"\n[>>] Skip (URL already collected): {url}", flush=True)
                continue

            try:
                post_data = collect_facebook_post (page, url)
            except Exception as e:
                print(f"  [X] Error processing {url}: {e}", flush=True)
                continue

            if not post_data:
                print(f"  [X] Post not found: {url}", flush=True)
                continue

            # Check exact duplicate by post_id
            if post_data["post_id"] in existing_ids:
                print(f"  [>>] Skip (post_id '{post_data['post_id']}' already exists).", flush=True)
                continue

            # Check near-duplicate content by MinHash-LSH (cross-posted announcements)
            dup_result = deduplicator.find_duplicate(post_data.get("raw_content", ""))
            if dup_result:
                cand_id, similarity = dup_result
                print(
                    f"  [>>] Skip (Duplicate/cross-posted content with '{cand_id}', "
                    f"similarity: {similarity * 100:.1f}%).",
                    flush=True,
                )
                continue

            # Add valid new post
            new_posts.append(post_data)
            existing_ids.add(post_data["post_id"])
            existing_posts.append(post_data)
            deduplicator.index_post(post_data["post_id"], post_data.get("raw_content", ""))
            random_delay(2, 4)

        browser.close()

    # 5. Save results to JSON file
    if new_posts:
        save_posts(existing_posts, DATA_FILE)
        print(f"\n[#] Saved {len(existing_posts)} post(s) to '{DATA_FILE}' (added {len(new_posts)} new post(s)).", flush=True)
    else:
        print("\n[#] No new post(s).", flush=True)


if __name__ == "__main__":
    main()