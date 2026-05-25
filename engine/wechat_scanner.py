import os
import re

from models.wechat_account import WeChatAccount


def _candidate_paths() -> list[str]:
    """Return all possible WeChat data directory paths to probe, ordered by
    likelihood on Windows."""
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA", os.path.join(home, "AppData", "Roaming"))
    candidates = []
    # Primary: English Documents (physical folder name on disk)
    candidates.append(os.path.join(home, "Documents", "WeChat Files"))
    # Chinese-localized Documents folder (some installations)
    candidates.append(os.path.join(home, "文档", "WeChat Files"))
    # Alternate: Tencent naming
    candidates.append(os.path.join(home, "Documents", "Tencent Files"))
    # WeChatStore (Microsoft Store version) uses AppData
    candidates.append(os.path.join(appdata, "Tencent", "WeChatAppStore",
                                   "WeChatAppStore Files"))
    return candidates


class WeChatScanner:
    """Auto-detect WeChat data directories and version.

    Probes multiple candidate paths.  Keeps a record of every path checked
    so callers can show the user exactly where the scanner looked.
    """

    def __init__(self, base_path: str | None = None):
        self._explicit_path = base_path
        self._checked_paths: list[str] = []

    @property
    def checked_paths(self) -> list[str]:
        """Return a copy of the paths checked during the last scan.

        Note: reset on every find_data_dirs() call.  Reflects only the most
        recent scan.
        """
        return list(self._checked_paths)

    def _scan_candidate(self, base: str) -> list[str]:
        """Return data-dir paths found inside a single candidate directory."""
        result = []
        if not os.path.isdir(base):
            return result
        for entry in os.listdir(base):
            entry_path = os.path.join(base, entry)
            if not os.path.isdir(entry_path):
                continue
            if entry in ("All Users", "config", "Applet", "WMPF"):
                continue
            msg_db = os.path.join(entry_path, "Msg", "MSG.db")
            chat_db = os.path.join(entry_path, "Msg", "ChatMsg.db")
            multi_db = os.path.join(entry_path, "Msg", "Multi", "MSG0.db")
            if os.path.isfile(msg_db) or os.path.isfile(chat_db) or os.path.isfile(multi_db):
                result.append(entry_path)
        return result

    def find_data_dirs(self) -> list[str]:
        """Return list of wxid directories containing Msg/MSG.db."""
        self._checked_paths = []

        paths = ([self._explicit_path] if self._explicit_path
                 else _candidate_paths())

        result = []
        for base in paths:
            self._checked_paths.append(base)
            result.extend(self._scan_candidate(base))
        return result

    # ------------------------------------------------------------------
    # Helper methods for per-account version detection
    # ------------------------------------------------------------------

    _SQLITE_HEADER = b"SQLite format 3\x00"

    @staticmethod
    def _is_sqlite_file(filepath: str) -> bool:
        """Return True if *filepath* starts with the SQLite 3 magic header."""
        try:
            with open(filepath, "rb") as fh:
                return fh.read(16) == WeChatScanner._SQLITE_HEADER
        except (IOError, OSError):
            return False

    def _detect_version_and_shards(self, data_dir: str) -> tuple[int, list[str]]:
        """Detect version and shard paths for a single account directory.

        Returns (version, shard_paths):
            * 2 — plaintext v2 (Msg/MSG.db)
            * 3 — encrypted v3 (Msg/Multi/MSG0.db … or Msg/ChatMsg.db)
            * 0 — undetectable / no valid DB files
        """
        msg_dir = os.path.join(data_dir, "Msg")
        multi_dir = os.path.join(msg_dir, "Multi")

        if os.path.isdir(multi_dir):
            shard_paths: list[str] = []
            for i in range(10):
                shard = os.path.join(multi_dir, f"MSG{i}.db")
                if os.path.isfile(shard):
                    shard_paths.append(shard)

            if shard_paths:
                if self._is_sqlite_file(shard_paths[0]):
                    return (2, shard_paths)
                return (3, shard_paths)

        # V2 structure: Msg/MSG.db
        msg_db = os.path.join(msg_dir, "MSG.db")
        if os.path.isfile(msg_db) and self._is_sqlite_file(msg_db):
            return (2, [msg_db])
        if os.path.isfile(msg_db):
            return (3, [msg_db])

        # WeChatStore format: Msg/ChatMsg.db (single encrypted file)
        chat_db = os.path.join(msg_dir, "ChatMsg.db")
        if os.path.isfile(chat_db):
            return (3, [chat_db])

        return (0, [])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_accounts(self) -> list[WeChatAccount]:
        """Return WeChatAccount objects for every detected account."""
        accounts: list[WeChatAccount] = []
        for data_dir in self.find_data_dirs():
            wxid = os.path.basename(data_dir)
            version, shard_paths = self._detect_version_and_shards(data_dir)
            msg_dir = os.path.join(data_dir, "Msg")
            micro_msg_db = os.path.join(msg_dir, "MicroMsg.db")
            if not os.path.isfile(micro_msg_db):
                micro_msg_db = ""

            accounts.append(
                WeChatAccount(
                    wxid=wxid,
                    data_dir=data_dir,
                    msg_dir=msg_dir,
                    version=version,
                    shard_paths=shard_paths,
                    micro_msg_db=micro_msg_db,
                )
            )
        return accounts

    def detect_version(self) -> tuple[int, int] | None:
        """Return (major, minor) or None if undetectable."""
        for data_dir in self.find_data_dirs():
            config_data = os.path.join(
                data_dir, "..", "All Users", "config", "config.data"
            )
            config_data = os.path.normpath(config_data)
            if not os.path.isfile(config_data):
                continue
            try:
                with open(config_data, "rb") as f:
                    data = f.read()
                version_str = self._extract_version(data)
                if version_str:
                    parts = version_str.split(".")
                    major = int(parts[0])
                    minor = int(parts[1]) if len(parts) > 1 else 0
                    return (major, minor)
            except (IOError, ValueError, IndexError):
                pass
        return None

    def _extract_version(self, data: bytes) -> str | None:
        decoded = data.decode("utf-8", errors="replace")
        match = re.search(r"(\d+\.\d+\.\d+\.\d+)", decoded)
        if match:
            return match.group(1)
        return None

    def get_wxid_to_path(self) -> dict[str, str]:
        """Return {wxid: data_dir_path} for all wxid directories."""
        mapping = {}
        for data_dir in self.find_data_dirs():
            wxid = os.path.basename(data_dir)
            mapping[wxid] = data_dir
        return mapping
