import os
import sqlite3

from models.wechat_account import WeChatAccount
from engine.db_crypto import decrypt_db


class ContactParser:
    """Parse contact info from MicroMsg.db.

    For encrypted accounts a decryption key may be supplied; MicroMsg.db
    is then decrypted to a temporary file, read, and the temp file is
    cleaned up automatically.
    """

    def __init__(self, account: WeChatAccount, key: str | None = None):
        self._account = account
        self._key = key

    def load_contacts(self) -> dict[str, str]:
        """Return {wxid: display_name} mapping.

        Remark takes priority over NickName, which takes priority over wxid.
        """
        micro = self._account.micro_msg_db
        if not os.path.isfile(micro):
            return {}

        # Decrypt if needed
        db_path = micro
        cleanup_path: str | None = None
        if self._account.is_encrypted and self._key:
            db_path = decrypt_db(micro, self._key)
            if not db_path:
                return {}
            cleanup_path = db_path

        try:
            return self._read_contacts(db_path)
        finally:
            if cleanup_path and os.path.isfile(cleanup_path):
                try:
                    os.unlink(cleanup_path)
                except OSError:
                    pass

    def _read_contacts(self, db_path: str) -> dict[str, str]:
        """Read contacts from a single SQLite database file.

        Returns ALL contacts. Filtering (public accounts, chatrooms, system)
        is handled by the caller based on context.
        """
        mapping: dict[str, str] = {}
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            cur = conn.execute(
                "SELECT UserName, NickName, Remark FROM Contact"
            )
            for row in cur:
                wxid = row["UserName"]
                remark = row["Remark"]
                nick = row["NickName"]
                display = remark or nick or wxid
                mapping[wxid] = display
            conn.close()
        except sqlite3.Error:
            return {}
        return mapping
