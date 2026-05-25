"""Tests for VoiceDecoder module."""

import os

import pytest
from unittest.mock import patch, MagicMock

from engine.voice_decoder import VoiceDecoder
from models.wechat_account import WeChatAccount


def _make_account(wxid="wx_test", msg_dir="/tmp/a"):
    """Create a minimal WeChatAccount for testing."""
    return WeChatAccount(wxid, "/tmp/base", msg_dir, 3, [], "")


class TestDecode:
    """Tests for VoiceDecoder.decode()."""

    def test_no_key_returns_none(self):
        result = VoiceDecoder.decode(12345, [_make_account()], key=None)
        assert result is None

    def test_empty_key_returns_none(self):
        result = VoiceDecoder.decode(12345, [_make_account()], key="")
        assert result is None

    def test_no_accounts_returns_none(self):
        result = VoiceDecoder.decode(12345, [], key="abc")
        assert result is None

    def test_pysilk_not_installed_returns_none(self):
        acc = _make_account()
        result = VoiceDecoder.decode(12345, [acc], key="abc")
        # pysilk is not installed in the test environment, so decode
        # returns None after catching ImportError.
        assert result is None

    def test_media_dir_missing_returns_none(self):
        acc = _make_account(msg_dir="/nonexistent/path")
        result = VoiceDecoder.decode(12345, [acc], key="abc")
        assert result is None


class TestDecodeFromShard:
    """Tests for VoiceDecoder._decode_from_shard()."""

    def test_decode_from_shard_success(self, tmp_path):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (
            b"\x02#!SILK_V3\x00\x00test",
        )

        wav_path = str(tmp_path / "test.wav")

        with patch('engine.voice_decoder.decrypt_db',
                   return_value=str(tmp_path / "dec.db")), \
             patch('engine.voice_decoder.sqlite3.connect',
                   return_value=mock_conn), \
             patch('engine.voice_decoder.wave') as mock_wave, \
             patch('engine.voice_decoder.tempfile.NamedTemporaryFile') as mock_tmp:

            mock_tmp.return_value.__enter__.return_value.name = wav_path
            mock_tmp.return_value.name = wav_path

            # mock pysilk
            def fake_silk(silk_io, pcm_io, rate):
                pcm_io.write(b"\x00" * 500)
            mock_silk = MagicMock()
            mock_silk.side_effect = fake_silk

            result = VoiceDecoder._decode_from_shard(
                "/fake/shard.db", 12345, "abc", mock_silk
            )

        assert result == wav_path

    def test_decrypt_failure_returns_none(self):
        with patch('engine.voice_decoder.decrypt_db',
                   return_value=None):
            result = VoiceDecoder._decode_from_shard(
                "/fake/shard.db", 12345, "abc", MagicMock()
            )
        assert result is None

    def test_decrypt_raises_returns_none(self):
        with patch('engine.voice_decoder.decrypt_db',
                   side_effect=OSError("fail")):
            result = VoiceDecoder._decode_from_shard(
                "/fake/shard.db", 12345, "abc", MagicMock()
            )
        assert result is None

    def test_query_returns_none_row(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = None

        with patch('engine.voice_decoder.decrypt_db',
                   return_value="/tmp/decrypted.db"), \
             patch('engine.voice_decoder.sqlite3.connect',
                   return_value=mock_conn), \
             patch('engine.voice_decoder.os.unlink'):
            result = VoiceDecoder._decode_from_shard(
                "/fake/shard.db", 12345, "abc", MagicMock()
            )
        assert result is None

    def test_query_empty_buf_returns_none(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (b"",)

        with patch('engine.voice_decoder.decrypt_db',
                   return_value="/tmp/decrypted.db"), \
             patch('engine.voice_decoder.sqlite3.connect',
                   return_value=mock_conn), \
             patch('engine.voice_decoder.os.unlink'):
            result = VoiceDecoder._decode_from_shard(
                "/fake/shard.db", 12345, "abc", MagicMock()
            )
        assert result is None

    def test_query_buf_too_short_returns_none(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (b"\x01\x02\x03",)

        with patch('engine.voice_decoder.decrypt_db',
                   return_value="/tmp/decrypted.db"), \
             patch('engine.voice_decoder.sqlite3.connect',
                   return_value=mock_conn), \
             patch('engine.voice_decoder.os.unlink'):
            result = VoiceDecoder._decode_from_shard(
                "/fake/shard.db", 12345, "abc", MagicMock()
            )
        assert result is None

    def test_sqlite_error_returns_none(self):
        with patch('engine.voice_decoder.decrypt_db',
                   return_value="/tmp/decrypted.db"), \
             patch('engine.voice_decoder.sqlite3.connect',
                   side_effect=__import__('sqlite3').Error("bad")), \
             patch('engine.voice_decoder.os.unlink'):
            result = VoiceDecoder._decode_from_shard(
                "/fake/shard.db", 12345, "abc", MagicMock()
            )
        assert result is None

    def test_silk_decode_failure_returns_none(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (
            b"\x02#!SILK_V3\x00\x00test",
        )
        # silk_decode that raises
        def bad_silk(silk_io, pcm_io, rate):
            raise RuntimeError("decode failed")
        mock_silk = MagicMock()
        mock_silk.side_effect = bad_silk

        with patch('engine.voice_decoder.decrypt_db',
                   return_value="/tmp/decrypted.db"), \
             patch('engine.voice_decoder.sqlite3.connect',
                   return_value=mock_conn), \
             patch('engine.voice_decoder.os.unlink'):
            result = VoiceDecoder._decode_from_shard(
                "/fake/shard.db", 12345, "abc", mock_silk
            )
        assert result is None

    def test_pcm_too_short_returns_none(self):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (
            b"\x02#!SILK_V3\x00\x00test",
        )
        # silk_decode that produces too little PCM data
        def short_silk(silk_io, pcm_io, rate):
            pcm_io.write(b"\x00" * 10)
        mock_silk = MagicMock()
        mock_silk.side_effect = short_silk

        with patch('engine.voice_decoder.decrypt_db',
                   return_value="/tmp/decrypted.db"), \
             patch('engine.voice_decoder.sqlite3.connect',
                   return_value=mock_conn), \
             patch('engine.voice_decoder.os.unlink'):
            result = VoiceDecoder._decode_from_shard(
                "/fake/shard.db", 12345, "abc", mock_silk
            )
        assert result is None

    def test_wave_write_failure_cleans_up(self, tmp_path):
        mock_conn = MagicMock()
        mock_conn.execute.return_value.fetchone.return_value = (
            b"\x02#!SILK_V3\x00\x00test",
        )

        wav_path = str(tmp_path / "test.wav")

        # silk_decode produces valid PCM
        def fake_silk(silk_io, pcm_io, rate):
            pcm_io.write(b"\x00" * 500)
        mock_silk = MagicMock()
        mock_silk.side_effect = fake_silk

        with patch('engine.voice_decoder.decrypt_db',
                   return_value=str(tmp_path / "dec.db")), \
             patch('engine.voice_decoder.sqlite3.connect',
                   return_value=mock_conn), \
             patch('engine.voice_decoder.tempfile.NamedTemporaryFile') as mock_tmp, \
             patch('engine.voice_decoder.wave.open',
                   side_effect=IOError("write fail")), \
             patch('engine.voice_decoder.os.unlink') as mock_unlink:

            mock_tmp.return_value.__enter__.return_value.name = wav_path
            mock_tmp.return_value.name = wav_path

            result = VoiceDecoder._decode_from_shard(
                "/fake/shard.db", 12345, "abc", mock_silk
            )

        assert result is None
        # os.unlink is called twice: once for the decrypted DB, once for
        # the failed WAV file. Verify the WAV cleanup happened.
        mock_unlink.assert_any_call(wav_path)
