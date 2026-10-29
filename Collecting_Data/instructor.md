# Facebook Post Collection & Deduplication Pipeline

A modular Python tool designed to automate the collection of student activity posts from Facebook, extract structured information, and detect cross-posted or duplicate announcements using **MinHash-LSH (Locality Sensitive Hashing)**.

---

## 1. Overview 

The codebase follows the **Separation of Concerns** principle, splitting tasks into dedicated modules for configuration, web automation, data persistence, and similarity indexing:

| File | Purpose |
| :--- | :--- |
| `config.py` | Central configuration storing file paths, browser settings, LSH parameters, and Facebook DOM selectors. |
| `collector.py` | Playwright automation logic (browser interaction, login popup dismissal, "See more" expansion, DOM extraction). |
| `deduplication.py` | Text shingling (n-grams), MinHash signature computation, and LSH index management (`PostDeduplicator`). |
| `storage.py` | File I/O operations for reading `urls.txt`, loading/saving `source.json`, and ISO 8601 date parsing. |
| `datacollecting.py` | Main orchestrator script coordinating the pipeline from reading URLs to deduplication and saving. |
| `requirements.txt` | List of required Python dependencies. |
| `urls.txt` | Input list of Facebook post/share URLs to collect. |
| `source.json` | Output dataset containing collected post records in JSON format. |

---

## 2. Prerequisites

- **Python**: Version `3.10` or higher (tested on Python 3.12).
- **Package Manager**: `pip`.
- **Operating System**: Windows, macOS, or Linux.
- **Internet Connection**: Required to access Facebook and download Playwright browser binaries.

---

## 3. Installation Guide

Follow these steps to set up the environment from scratch:

### Step 1: Create a Virtual Environment

Open a terminal or PowerShell in the project directory and create a virtual environment:

```powershell
python -m venv .venv
```

### Step 2: Activate the Virtual Environment

- **On Windows (PowerShell):**
  ```powershell
  .\.venv\Scripts\Activate.ps1
  ```
  *(If you encounter an execution policy restriction, run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` first).*

- **On Windows (Command Prompt):**
  ```cmd
  .venv\Scripts\activate.bat
  ```

- **On macOS / Linux:**
  ```bash
  source .venv/bin/activate
  ```

### Step 3: Install Required Python Libraries

Install all required dependencies using `requirements.txt`:

```powershell
pip install -r requirements.txt
```

### Step 4: Install Chromium for Playwright

Playwright requires its dedicated Chromium browser binary. Run:

```powershell
playwright install chromium
```

---

## 4. How to Use & Run

### Step 1: Prepare Input URLs

Edit `urls.txt` and add the Facebook URLs you wish to scrape (one URL per line). You can add comments using `#`:

```text
https://www.facebook.com/share/p/1CU2mw5i96/
https://www.facebook.com/osa.hcmus/posts/pfbid02buJY8Rrn2XezSWbCNxpUnfSH... # Fire safety training
https://www.facebook.com/share/p/1T1bkjS9zM/
```

### Step 2: Adjust Settings in `config.py` (Optional)

You can customize runtime settings in `config.py`:
- `HEADLESS = False`: Shows the browser window (recommended for debugging and visual tracking). Set to `True` for silent, background execution.
- `SIMILARITY_THRESHOLD = 0.75`: Jaccard similarity threshold for deduplication (75% or higher is considered a cross-post or duplicate).
- `MAX_SCROLLS = 3`: Number of downward scrolls per post to reveal long texts.

### Step 3: Run the Pipeline

Execute the main script:

```powershell
python datacollecting.py
```

---

## 5. Execution Workflow

When `datacollecting.py` runs, it executes the following pipeline:

1. **URL Loading**: Reads and sanitizes all URLs from `urls.txt`.
2. **Existing Data Loading**: Loads previously scraped posts from `source.json` to prevent re-scraping existing URLs.
3. **LSH Index Construction**: Builds a `MinHashLSH` index in-memory for all existing post contents.
4. **Browser Launch**: Launches Chromium with `playwright-stealth` enabled to evade bot detection.
5. **For Each URL**:
   - Follows redirects (e.g., resolving `/share/p/...` to canonical `/posts/...` URLs).
   - Extracts the canonical `post_id`.
   - Dismisses login popups specifically targeting the password modal without closing the post dialog.
   - Automatically clicks "See more" / "Xem thêm" to reveal full descriptions.
   - Extracts `publisher`, `date_posted` (normalized to ISO 8601), and `raw_content`.
   - **Exact Deduplication**: Skips if `post_id` already exists.
   - **Semantic Near-Duplicate Detection**: Queries the LSH index; if Jaccard similarity $\ge 75\%$, marks as duplicate/cross-post and skips.
   - If unique, appends to the dataset and updates the in-memory LSH index.
6. **Persistence**: Saves the updated list back to `source.json` in UTF-8 format.

---

## 6. Output Data Format (`source.json`)

Each collected entry in `source.json` follows this structure:

```json
{
  "post_id": "pfbid02buJY8Rrn2XezSWbCNxpUnfSHX4yDYWi5EgXbngmL1FKiEE47XQarhqVqb4WjERECl",
  "url": "https://www.facebook.com/osa.hcmus/posts/pfbid02buJY8Rrn2XezSWbCNxpUnfSHX4yDYWi5EgXbngmL1FKiEE47XQarhqVqb4WjERECl",
  "share_url": "https://www.facebook.com/share/p/1CU2mw5i96/",
  "raw_content": "CHUYÊN ĐỀ TẬP HUẤN KIẾN THỨC, KỸ NĂNG VÀ THỰC TẬP PHƯƠNG ÁN PHÒNG CHÁY CHỮA CHÁY...",
  "publisher": "Phòng Công tác Sinh viên - Trường Đại học Khoa học Tự nhiên",
  "platform": "Facebook",
  "date_posted": "2026-10-25T14:00:00"
}
```

---

## 7. Duplicate Detection

The system detects and handles duplicate posts through a two-tiered deduplication mechanism:
1. **Exact Duplicate Detection**: Matching canonical `post_id` or previously collected post URLs.
2. **Near-Duplicate / Cross-Post Detection**: Utilizing **MinHash-LSH** based on word n-gram shingles with a Jaccard similarity threshold $\ge 75\%$.

During execution with the provided URL list in `urls.txt`, the following deduplication scenarios were observed:

### 7.1. Observed Deduplication Cases

| # | Case | Primary URL (Retained) | Duplicate URL (Skipped) | Mechanism | Outcome |
| :--- | :--- | :--- | :--- | :--- | :--- |
| 1 | **Exact Duplicate** | **Link 1**<br>`https://www.facebook.com/share/p/1CU2mw5i96/` | **Link 7**<br>`https://www.facebook.com/share/p/1dt9mMzowP/` | Points to the exact same Facebook post (identical canonical `post_id` / canonical URL). | **Skip 7, retain 1** |
| 2 | **Semantic Near-Duplicate (Cross-post)** | **Link 21**<br>`https://www.facebook.com/share/p/19zV2rjzPN/` | **Link 22**<br>`https://www.facebook.com/share/p/19YiVxvJRh/` | Posts share substantially identical announcement content ("Bản lĩnh IT 2026"), exceeding the MinHash-LSH threshold. | **Skip 22, retain 21** |

---

### 7.2. Case Analysis (Link 21 vs. Link 22) & Publisher Attribution Limitation

While the MinHash-LSH algorithm succeeded in identifying near-duplicate text content, the interaction between **Link 21** and **Link 22** highlights an important limitation in the collection pipeline:

- **Post Origin Context:**
  - **Link 22**: Represents the official primary announcement published directly by the **event organizers** (Youth Union / Student Association - Đoàn khoa).
  - **Link 21**: Represents a cross-posted announcement published by a **media support partner** (prefixed with `[HỖ TRỢ TRUYỀN THÔNG]` from the *Design ITUS* fanpage).
- **Issue Encountered:**
  - Due to the sequential First-In, First-Out (FIFO) processing order of `urls.txt`, **Link 21** was processed and indexed into the LSH structure first.
  - When the pipeline subsequently encountered **Link 22**, MinHash-LSH flagged it as a near-duplicate of Link 21 and promptly **skipped Link 22**.
  - **Resulting Discrepancy:** The stored record in `source.json` attributes the `publisher` field to the media support partner (`Design ITUS`) rather than the actual host/organizing body.

> **Known Limitation & Proposed Mitigations**: The deduplication logic currently operates purely on text similarity using a first-come, first-served policy. To resolve the publisher attribution issue, recommended improvements include:
> 1. **Media Support Detection**: Parse post content for disclaimer prefixes (e.g., `[HỖ TRỢ TRUYỀN THÔNG]`) and assign lower retention priority to promotional cross-posts.
> 2. **Metadata Override Mechanism**: When a near-duplicate post is detected from a primary authoritative organizer, update/override the existing entry's `publisher` and metadata fields instead of discarding the incoming post entirely.