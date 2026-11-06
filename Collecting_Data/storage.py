import json
from datetime import datetime
from pathlib import Path
import dateparser
from config import DATA_FILE, URLS_FILE


def load_urls(file_path: Path = URLS_FILE) -> list[str]:
    """Load list of URLs from a text file (stripping inline # comments and whitespace)."""
    if not file_path.exists():
        return []
    urls = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            clean_url = line.split("#")[0].strip()
            if clean_url:
                urls.append(clean_url)
    return urls


def load_existing_posts(file_path: Path = DATA_FILE) -> list[dict]:
    """Load previously scraped post data from JSON file (filtering out invalid/footer posts)."""
    if not file_path.exists():
        return []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return [
                    p for p in data
                    if isinstance(p, dict)
                    and p.get("post_id")
                    and "Tiếng Việt\nEnglish" not in p.get("raw_content", "")
                ]
    except Exception:
        return []
    return []


def save_posts(posts: list[dict], file_path: Path = DATA_FILE):
    """Save list of posts to JSON file formatted with UTF-8 encoding."""
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(posts, f, ensure_ascii=False, indent=2)


def normalize_date(raw_date: str) -> str | None:
    """Normalize post publication date string to ISO 8601 format."""
    if not raw_date or not raw_date.strip():
        return None
    try:
        parsed = dateparser.parse(
            raw_date,
            languages=["vi", "en"],
            settings={
                "RELATIVE_BASE": datetime.now(),
                "PREFER_DATES_FROM": "past",
            },
        )
        if parsed:
            return parsed.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        pass
    return None
