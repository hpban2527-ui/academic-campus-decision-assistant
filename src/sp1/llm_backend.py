"""LLM backend for SP1 extraction.

The model is reached through an injected callable `client(prompt) -> str`, so
the same code runs with a Kaggle GPU model, a local model or a fake client in
tests. This module only builds the prompt and parses the reply into raw
activities (same format as regex_baseline). All checks happen in extractor.py.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

LLMClient = Callable[[str], str]

PROMPT_VERSION = "extraction_v1"
PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / f"{PROMPT_VERSION}.txt"
PLACEHOLDER = "{{ANNOUNCEMENT}}"
DELIMITER_RX = re.compile(r"</?\s*announcement\s*>", re.IGNORECASE)

RAW_KEYS = (
    "URL_registration", "title", "domain", "time", "registration_deadline", "mode", "location", "points",
    "drl_recognized", "mandatory", "audience", "fee", "completion_requirements",
)


class LLMOutputError(ValueError):
    """The model reply is not valid JSON in the expected shape."""


def build_prompt(text: str, prompt_path: Path = PROMPT_PATH) -> str:
    """The prompt template with the announcement inserted, its delimiter tags neutralised."""
    template = prompt_path.read_text(encoding="utf-8")
    # The announcement must not be able to close our delimiter.
    safe = DELIMITER_RX.sub("[removed-delimiter]", text)
    return template.replace(PLACEHOLDER, safe)


def contains_delimiter(text: str) -> bool:
    """True if the text contains an <announcement> tag (a sign of prompt injection)."""
    return bool(DELIMITER_RX.search(text))


def parse_reply(reply: str) -> list[dict[str, dict[str, Any]]]:
    """Model reply -> raw activities {field: {value, evidence}}; raises LLMOutputError if malformed."""
    start, end = reply.find("{"), reply.rfind("}")
    if start == -1 or end <= start:
        raise LLMOutputError("no JSON object in the reply")
    try:
        obj = json.loads(reply[start:end + 1])
    except json.JSONDecodeError as e:
        raise LLMOutputError(f"invalid JSON: {e.msg}") from e
    if not isinstance(obj, dict) or not isinstance(obj.get("activities"), list):
        raise LLMOutputError('expected {"activities": [...]}')

    activities = []
    for item in obj["activities"]:
        if not isinstance(item, dict):
            raise LLMOutputError("an activity is not an object")
        raw: dict[str, dict[str, Any]] = {}
        for key in RAW_KEYS:
            cell = item.get(key)
            if cell is None:
                raw[key] = {"value": None, "evidence": None}
            elif isinstance(cell, dict) and set(cell) <= {"value", "evidence"}:
                raw[key] = {"value": cell.get("value"), "evidence": cell.get("evidence")}
            else:
                raise LLMOutputError(f"field {key!r} is not {{value, evidence}}")
        activities.append(raw)
    return activities


def extract_raw(text: str, client: LLMClient) -> list[dict[str, dict[str, Any]]]:
    """LLM extraction of one announcement: raw activities; raises LLMOutputError or the client's error."""
    return parse_reply(client(build_prompt(text)))


def make_hf_client(model_id: str, max_new_tokens: int = 1536) -> LLMClient:  # pragma: no cover
    """Greedy (temperature 0) client for a Hugging Face chat model, e.g. on Kaggle.

    NOT RUN in the environment where this file was written (no GPU). Test it on
    Kaggle before use and record the model id, quantisation and prompt version.
    """
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

    tok = AutoTokenizer.from_pretrained(model_id)
    model = AutoModelForCausalLM.from_pretrained(
        model_id,
        device_map="auto",
        quantization_config=BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_compute_dtype=torch.float16),
    )

    def client(prompt: str) -> str:
        msgs = [{"role": "user", "content": prompt}]
        ids = tok.apply_chat_template(msgs, add_generation_prompt=True, return_tensors="pt").to(model.device)
        out = model.generate(ids, max_new_tokens=max_new_tokens, do_sample=False)
        return tok.decode(out[0][ids.shape[-1]:], skip_special_tokens=True)

    return client
