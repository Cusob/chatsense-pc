import pytest
import sqlite3
import os
from unittest.mock import patch, MagicMock
from engine.tencent_stt import TencentSTT


class TestTranscribeCache:
    def test_cache_hit_returns_saved_transcript(self, tmp_path):
        """When msg_svr_id is in cache, return cached text without API call."""
        cache_db = str(tmp_path / "stt_cache.db")
        conn = sqlite3.connect(cache_db)
        conn.execute("CREATE TABLE IF NOT EXISTS stt_cache (msg_svr_id INTEGER PRIMARY KEY, transcript TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("INSERT INTO stt_cache (msg_svr_id, transcript) VALUES (12345, 'ni zai gan ma ne')")
        conn.commit()
        conn.close()

        stt = TencentSTT(secret_id="test", secret_key="test")
        stt.CACHE_DB = cache_db
        result = stt.transcribe("/nonexistent/file.amr", 12345)
        assert result == "ni zai gan ma ne"

    def test_cache_miss_calls_api(self, tmp_path):
        """Cache miss triggers API call, result written to cache."""
        audio_file = tmp_path / "test.amr"
        audio_file.write_bytes(b"\x23\x21\x41\x4d\x52\x0a")

        cache_db = str(tmp_path / "stt_cache.db")

        stt = TencentSTT(secret_id="test", secret_key="test")
        stt.CACHE_DB = cache_db

        with patch.object(stt, '_call_asr_api', return_value="test text"):
            result = stt.transcribe(str(audio_file), 99999)

        assert result == "test text"
        conn = sqlite3.connect(cache_db)
        row = conn.execute("SELECT transcript FROM stt_cache WHERE msg_svr_id = 99999").fetchone()
        assert row[0] == "test text"
        conn.close()

    def test_no_secret_keys_returns_none(self, tmp_path):
        """Returns None when no secret keys configured."""
        audio_file = tmp_path / "test.amr"
        audio_file.write_bytes(b"\x23\x21\x41\x4d\x52\x0a")

        stt = TencentSTT(secret_id="", secret_key="")
        result = stt.transcribe(str(audio_file), 1)
        assert result is None

    def test_file_not_found_returns_none(self, tmp_path):
        stt = TencentSTT(secret_id="test", secret_key="test")
        stt.CACHE_DB = str(tmp_path / "cache.db")
        result = stt.transcribe("/nonexistent/file.amr", 1)
        assert result is None


class TestConnection:
    def test_test_connection_success(self):
        """Mock requests.post to return success (no Error in Response)."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"Response": {"Result": "ok"}}
        with patch('requests.post', return_value=mock_resp):
            ok, msg = TencentSTT.test_connection("id", "key")
        assert ok is True

    def test_test_connection_auth_failure(self):
        """Mock requests.post to return auth error → ok=False."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"Response": {"Error": {"Code": "AuthFailure.SecretIdNotFound", "Message": "SecretId not exist"}}}
        with patch('requests.post', return_value=mock_resp):
            ok, msg = TencentSTT.test_connection("id", "bad_key")
        assert ok is False
        assert "AuthFailure" in msg
        assert "SecretId" in msg

    def test_test_connection_non_auth_error_passes(self):
        """Non-auth API errors → ok=True (auth is valid, just bad test data)."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"Response": {"Error": {"Code": "InvalidParameterValue.ErrorVoicedataTooShort", "Message": "audio data too short"}}}
        with patch('requests.post', return_value=mock_resp):
            ok, msg = TencentSTT.test_connection("id", "key")
        assert ok is True
        assert "InvalidParameterValue" in msg
