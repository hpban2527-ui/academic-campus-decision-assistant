"""Write reproducible aggregate N0/N1 metrics for the SP1 development split."""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sp1.devdata import dev_ids, dev_posts
from sp1.preprocess import preprocess
from sp1.segment import LABELS, segment

REPORT_PATH = ROOT / "reports/sp1_segmentation_dev.md"
INJECTION_IDS = ("ignore_instructions", "role_marker", "prompt_terms", "delimiter", "code_fence")


def _title_key(value: str) -> str:
    return " ".join(unicodedata.normalize("NFC", value).split())


def render_report() -> str:
    posts = dev_posts()
    gold_ids = set(dev_ids(include_extra=False))
    gold = json.loads((ROOT / "data/gold/source_gold.json").read_bytes())
    gold_titles = {
        row["post_id"]: row["activities"][0]["title"]
        for row in gold if row["post_id"] in gold_ids
        and row["activities"] and row["activities"][0].get("title")
    }
    fields: Counter[str] = Counter()
    title_counts: Counter[int] = Counter()
    flags: Counter[str] = Counter()
    no_fields = masked = flagged = matched = 0
    for post in posts:
        pre = preprocess(post["raw_content"])
        segments = segment(pre)
        fields.update({field.key for field in segments.fields})
        no_fields += not segments.fields
        masked += bool(pre.masked)
        flagged += bool(pre.flags)
        flags.update(pre.flags)
        title_counts[len(segments.title_candidates)] += 1
        title = gold_titles.get(post["post_id"])
        if title and segments.title_candidates:
            matched += _title_key(segments.title_candidates[0].text) == _title_key(title)

    size = len(posts)

    def row(label: str, count: int, total: int = size) -> str:
        percentage = f"{100 * count / total:.1f}%" if total else "n/a"
        return f"| {label} | {count} / {total} | {percentage} |"

    lines = [
        "# SP1 segmentation coverage on dev",
        "",
        f"N0 and N1 were run on {size} development posts. Label counts measure posts with at least",
        "one matching field. They measure coverage of the configured headings.",
        "",
        "| Measure | Posts | Share |",
        "| --- | ---: | ---: |",
        *(row(f"`{key}`", fields[key]) for key in LABELS),
        row("No label line", no_fields),
        row("At least one phone masked", masked),
        row("At least one injection flag", flagged),
        *(row(f"`injection_suspected:{key}`", flags[f"injection_suspected:{key}"]) for key in INJECTION_IDS),
        *(row(f"{number} title candidates", title_counts[number]) for number in range(4)),
        row("First candidate equals v1 gold title", matched, len(gold_titles)),
        "",
        "The title comparison is case-sensitive after NFC and whitespace normalisation. The denominator",
        "includes retained dev gold posts with a v1 title. This compares candidate ranking against v1",
        "titles, which may use different prefix and decoration conventions.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=REPORT_PATH, help="Destination Markdown file")
    path = parser.parse_args().output
    content = render_report().encode("utf-8")
    if path.exists() and path.read_bytes().replace(b"\r\n", b"\n") == content:
        return
    path.write_bytes(content)


if __name__ == "__main__":
    main()
