"""Integration tests — full pipeline against real data and API.

These tests require:
  1. ~/.chatsense/config.json with valid API key
  2. WeChat data directory with accessible encrypted DBs

Skipped gracefully when prerequisites are missing.
"""

import json
import pytest
import sys
import os

# Ensure ChatSense-PC is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import load_config
from engine.api_client import ApiClient, ApiError


def _require_api():
    """Return ApiClient or skip.  Read api_key/model from config."""
    cfg = load_config()
    key = cfg.get("api_key")
    url = cfg.get("api_url")
    model = cfg.get("model")
    fmt = cfg.get("api_format", "openai")

    if not key or not url:
        pytest.skip("API not configured (missing api_key or api_url)")

    return ApiClient(
        api_url=url, api_key=key, model=model,
        temperature=0.3, api_format=fmt,
    )


def _require_real_data():
    """Return (WeChatAccount, key, chat_history) or skip."""
    try:
        from engine.wechat_scanner import WeChatScanner
        from engine.key_extractor import KeyExtractor
        from engine.db_reader import DBReader
    except ImportError:
        pytest.skip("Engine modules unavailable")

    s = WeChatScanner()
    accounts = s.find_accounts()
    if not accounts:
        pytest.skip("No WeChat data directories found")

    e = KeyExtractor()
    key = e.extract_key()
    if not key:
        pytest.skip("Key extraction failed")

    acc = accounts[0]
    reader = DBReader(acc, key=key)
    msgs = reader.load_messages("wxid_amgk5fydhdth22", limit=30)
    text = [m for m in msgs if m.is_text]
    if len(text) < 5:
        pytest.skip("Insufficient text messages for analysis")

    chat = "\n".join(
        f"[{'我' if m.is_from_me else '对方'}] {m.content}" for m in text
    )
    return acc, key, chat


class TestFullPipeline:
    """Three-stage pipeline end-to-end on real data and API."""

    def test_annotation_stage(self):
        """Stage 1: LLM annotation produces valid JSON with messages."""
        c = _require_api()
        _, _, chat = _require_real_data()

        from engine.analysis_engine import ANNOTATION_PROMPT
        prompt = ANNOTATION_PROMPT.format(chat_history=chat)

        resp = c.chat_completion(prompt)
        content = resp["choices"][0]["message"]["content"]

        data = json.loads(content)
        assert "messages" in data, "Annotation missing 'messages' key"
        assert len(data["messages"]) > 0, "Annotation returned 0 messages"
        assert "stage" in data, "Annotation missing 'stage' key"

    def test_scoring_stage(self):
        """Stage 2: scoring produces varied (not all-50) 8-dimension results."""
        c = _require_api()
        _, _, chat = _require_real_data()

        from engine.analysis_engine import ANNOTATION_PROMPT
        prompt = ANNOTATION_PROMPT.format(chat_history=chat)
        resp = c.chat_completion(prompt)
        annotated = json.loads(resp["choices"][0]["message"]["content"])

        from engine.scoring import calculate_scores
        scores = calculate_scores(annotated)

        assert len(scores) == 8, f"Expected 8 dimensions, got {len(scores)}"
        assert all(0 <= v <= 100 for v in scores.values()), "Scores out of 0-100 range"

        # Must not be all default values
        defaults = (50, 55, 65, 70, 75)
        varied = sum(1 for v in scores.values() if v not in defaults)
        assert varied >= 1, (
            f"Scores are all defaults: {scores} — "
            "annotation or scoring pipeline likely broken"
        )

    def test_feedback_stage(self):
        """Stage 3: feedback returns structured strengths/improvements/warnings."""
        c = _require_api()
        _, _, chat = _require_real_data()

        from engine.analysis_engine import ANNOTATION_PROMPT, FEEDBACK_PROMPT
        from engine.scoring import calculate_scores

        prompt = ANNOTATION_PROMPT.format(chat_history=chat)
        resp = c.chat_completion(prompt)
        annotated = json.loads(resp["choices"][0]["message"]["content"])
        scores = calculate_scores(annotated)

        scores_summary = {k: {"score": v} for k, v in scores.items()}
        fb_prompt = FEEDBACK_PROMPT.format(
            annotated_messages=json.dumps(
                annotated["messages"], ensure_ascii=False
            ),
            scores_summary=json.dumps(scores_summary, ensure_ascii=False),
            stage=annotated.get("stage", "熟悉期"),
        )

        resp2 = c.chat_completion(fb_prompt)
        feedback = json.loads(resp2["choices"][0]["message"]["content"])

        assert isinstance(feedback.get("strengths"), list)
        assert isinstance(feedback.get("improvements"), list)
        assert isinstance(feedback.get("warnings"), list)


class TestFallbackPipeline:
    """Fallback path when annotation JSON fails."""

    def test_fallback_scores_extracted(self):
        """Fallback: flat scores (without 'scores' wrapper) are extracted."""
        c = _require_api()
        _, _, chat = _require_real_data()

        from engine.analysis_engine import FALLBACK_PROMPT
        prompt = FALLBACK_PROMPT.format(chat_history=chat)
        resp = c.chat_completion(prompt)
        data = json.loads(resp["choices"][0]["message"]["content"])

        # Simulate _fallback_analyze logic
        scores = data.get("scores", {})
        if not scores:
            dim_keys = {"boundary", "empathy", "interaction", "self_disclosure",
                       "naturalness", "initiative", "authenticity", "escalation"}
            flat = {k: v for k, v in data.items() if k in dim_keys}
            scores = flat

        assert len(scores) == 8, f"Fallback: expected 8 scores, got {len(scores)}"
        assert all(0 <= v <= 100 for v in scores.values()), "Scores out of range"
