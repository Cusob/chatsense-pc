"""Tests for db_crypto module.

decrypt_db() delegates to pywxdump.decrypt which requires real
WeChat-encrypted databases.  The production path is validated via
manual integration test on the developer machine.
"""
import os
from engine.db_crypto import decrypt_db, verify_key, cleanup_temp_files


def test_decrypt_db_nonexistent_file():
    assert decrypt_db("/nonexistent/path.db", "a" * 64) is None


def test_verify_key_nonexistent_file():
    assert verify_key("a" * 64, "/nonexistent/path.db") is False


def test_verify_key_wrong_format():
    assert verify_key("short", "/dev/null") is False
