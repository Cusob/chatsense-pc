import os
import tempfile

import pytest

from engine.wechat_scanner import WeChatScanner

SQLITE_HEADER = b"SQLite format 3\x00"


def _make_v2_structure(base: str, wxid: str) -> str:
    """Create a fake v2 plaintext WeChat account directory."""
    wxid_dir = os.path.join(base, wxid)
    msg_dir = os.path.join(wxid_dir, "Msg")
    os.makedirs(msg_dir)
    with open(os.path.join(msg_dir, "MSG.db"), "wb") as f:
        f.write(SQLITE_HEADER + b"\x00" * 84)
    return wxid_dir


def _make_v3_structure(base: str, wxid: str, sqlite_header: bool = False) -> str:
    """Create a fake v3 encrypted WeChat account directory.

    Args:
        base: Parent directory (e.g. WeChat Files).
        wxid: wxid directory name.
        sqlite_header: If True, MSG0.db starts with SQLite header
            (edge case: v2 plaintext masquerading in Multi/).
    """
    wxid_dir = os.path.join(base, wxid)
    multi_dir = os.path.join(wxid_dir, "Msg", "Multi")
    os.makedirs(multi_dir)
    header = SQLITE_HEADER + b"\x00" * 84 if sqlite_header else b"ENCRYPTED_DATA"
    for i in range(5):
        with open(os.path.join(multi_dir, f"MSG{i}.db"), "wb") as f:
            f.write(header)
    return wxid_dir


class TestFindAccountsV2Plaintext:
    """Tests for v2 (plaintext) account detection."""

    def test_find_accounts_v2_plaintext(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = os.path.join(tmpdir, "WeChat Files")
            _make_v2_structure(base, "wxid_old")

            scanner = WeChatScanner(base_path=base)
            accounts = scanner.find_accounts()

            assert len(accounts) == 1
            acc = accounts[0]
            assert acc.wxid == "wxid_old"
            assert acc.version == 2
            assert acc.is_encrypted is False
            assert len(acc.shard_paths) == 1
            assert os.path.basename(acc.shard_paths[0]) == "MSG.db"


class TestFindAccountsV3Encrypted:
    """Tests for v3 (encrypted) account detection."""

    def test_find_accounts_v3_encrypted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = os.path.join(tmpdir, "WeChat Files")
            _make_v3_structure(base, "wxid_v3")

            scanner = WeChatScanner(base_path=base)
            accounts = scanner.find_accounts()

            assert len(accounts) == 1
            acc = accounts[0]
            assert acc.wxid == "wxid_v3"
            assert acc.version == 3
            assert acc.is_encrypted is True
            assert len(acc.shard_paths) == 5
            for i, shard in enumerate(acc.shard_paths):
                assert os.path.basename(shard) == f"MSG{i}.db"


class TestFindAccountsMixed:
    """Tests for mixed v2 and v3 accounts."""

    def test_find_accounts_mixed_v2_and_v3(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = os.path.join(tmpdir, "WeChat Files")
            _make_v2_structure(base, "wxid_old")
            _make_v3_structure(base, "wxid_new")

            scanner = WeChatScanner(base_path=base)
            accounts = scanner.find_accounts()

            assert len(accounts) == 2
            version_map = {acc.wxid: acc.version for acc in accounts}
            assert version_map == {"wxid_old": 2, "wxid_new": 3}


class TestFindAccountsEdgeCases:
    """Tests for edge cases."""

    def test_find_accounts_empty_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = os.path.join(tmpdir, "WeChat Files")
            # Only "All Users/config" — no wxid directories
            config_dir = os.path.join(base, "All Users", "config")
            os.makedirs(config_dir)

            scanner = WeChatScanner(base_path=base)
            accounts = scanner.find_accounts()

            assert accounts == []

    def test_find_accounts_skips_invalid_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            base = os.path.join(tmpdir, "WeChat Files")
            # Directory with Msg/ but no actual DB files
            wxid_dir = os.path.join(base, "wxid_broken")
            msg_dir = os.path.join(wxid_dir, "Msg")
            os.makedirs(msg_dir)
            # No MSG.db or Multi/MSG*.db files

            scanner = WeChatScanner(base_path=base)
            accounts = scanner.find_accounts()

            assert accounts == []

    def test_find_accounts_v3_with_sqlite_header_treated_as_v2(self):
        """Edge case: v3 directory structure but MSG0.db has SQLite header."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = os.path.join(tmpdir, "WeChat Files")
            _make_v3_structure(base, "wxid_edge", sqlite_header=True)

            scanner = WeChatScanner(base_path=base)
            accounts = scanner.find_accounts()

            assert len(accounts) == 1
            acc = accounts[0]
            assert acc.wxid == "wxid_edge"
            assert acc.version == 2, (
                "Multi/ MSG0.db with SQLite header should be treated as v2 "
                "plaintext"
            )
            assert acc.is_encrypted is False
            assert len(acc.shard_paths) == 5
