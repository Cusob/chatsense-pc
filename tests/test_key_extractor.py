"""Tests for KeyExtractor dual-path key extraction (PyWxDump -> pymem).

Uses unittest.mock.patch to control the internal _try_pywxdump and _try_pymem
methods without requiring the real packages to be installed.
"""

from unittest.mock import patch

from engine.key_extractor import KeyExtractor, KeyExtractionError

FAKE_KEY = "a" * 64  # 32-byte hex string (64 hex chars)

# Common patches to disable cached key and shard verification
_CACHE_PATCH = patch("config.settings.load_config", return_value={"cached_wx_key": ""})
_SHARD_PATCH = patch.object(KeyExtractor, "_find_test_shard", return_value=None)


class TestExtractKeyPywxdumpSuccess:
    """Primary path succeeds -> pymem must NOT be called."""

    def test_extract_key_pywxdump_success(self):
        extractor = KeyExtractor()

        with (
            _CACHE_PATCH,
            _SHARD_PATCH,
            patch.object(extractor, "_try_pywxdump", return_value=FAKE_KEY) as mock_py,
            patch.object(extractor, "_try_pymem") as mock_pm,
        ):
            result = extractor.extract_key()

        assert result == FAKE_KEY
        mock_py.assert_called_once()
        mock_pm.assert_not_called()


class TestExtractKeyPywxdumpFailFallback:
    """Primary fails -> fallback to pymem."""

    def test_extract_key_pywxdump_fail_then_pymem_succeed(self):
        extractor = KeyExtractor()

        with (
            _CACHE_PATCH,
            _SHARD_PATCH,
            patch.object(
                extractor, "_try_pywxdump", side_effect=KeyExtractionError("fail")
            ) as mock_py,
            patch.object(extractor, "_try_pymem", return_value=FAKE_KEY) as mock_pm,
        ):
            result = extractor.extract_key()

        assert result == FAKE_KEY
        mock_py.assert_called_once()
        mock_pm.assert_called_once()


class TestExtractKeyBothFail:
    """Both paths fail -> returns None."""

    def test_extract_key_both_fail(self):
        extractor = KeyExtractor()

        with (
            _CACHE_PATCH,
            _SHARD_PATCH,
            patch.object(
                extractor, "_try_pywxdump", side_effect=KeyExtractionError("fail")
            ) as mock_py,
            patch.object(
                extractor, "_try_pymem", side_effect=KeyExtractionError("fail")
            ) as mock_pm,
        ):
            result = extractor.extract_key()

        assert result is None
        mock_py.assert_called_once()
        mock_pm.assert_called_once()


class TestExtractKeyImportErrorFallback:
    """ImportError (pywxdump not installed) -> falls back to pymem."""

    def test_extract_key_import_error_falls_back_to_pymem(self):
        extractor = KeyExtractor()

        with (
            _CACHE_PATCH,
            _SHARD_PATCH,
            patch.object(
                extractor, "_try_pywxdump", side_effect=ImportError("not installed")
            ) as mock_py,
            patch.object(extractor, "_try_pymem", return_value=FAKE_KEY) as mock_pm,
        ):
            result = extractor.extract_key()

        assert result == FAKE_KEY
        mock_py.assert_called_once()
        mock_pm.assert_called_once()
