from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "source.json"
URLS_FILE = BASE_DIR / "urls.txt"

# Browser config
HEADLESS = False  # False: display browser window for tracking/debugging
MAX_SCROLLS = 3   # Number of scrolls to load additional content

# MinHash-LSH Deduplication config
SIMILARITY_THRESHOLD = 0.75  # Jaccard similarity threshold (>= 75% considered duplicate/cross-posted)
NUM_PERM = 128               # Number of MinHash permutations (balance between speed & accuracy)
SHINGLE_SIZE = 3             # Word n-gram size (word 3-grams) for Vietnamese

# Facebook DOM Selectors
LOGIN_POPUP_CLOSE_SELECTORS = [
    'div[role="dialog"]:has(input[type="password"]) [aria-label="Đóng"]',
    'div[role="dialog"]:has(input[type="password"]) [aria-label="Close"]',
    'div[role="dialog"]:has(input[name="pass"]) [aria-label="Đóng"]',
    'div[role="dialog"]:has(input[name="pass"]) [aria-label="Close"]',
]

SEE_MORE_SELECTORS = [
    'div[role="button"]:has-text("Xem thêm")',
    'div[role="button"]:has-text("See more")',
    'span[dir="auto"]:has-text("Xem thêm")',
    'span[dir="auto"]:has-text("See more")',
    '[role="button"]:has-text("Xem thêm")',
    '[role="button"]:has-text("See more")',
]

PUBLISHER_SELECTORS = [
    'h2 a[role="link"]',
    'h3 a[role="link"]',
    'h2',
    'h3',
    'h4',
    'strong a[role="link"]',
    'a[role="link"] strong',
]

DATE_SELECTORS = [
    'a[role="link"]',
    'span > a',
    'abbr',
]
