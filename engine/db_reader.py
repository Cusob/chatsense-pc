import os
import sqlite3
import time

from models.chat_message import ChatMessage
from models.wechat_account import WeChatAccount
from engine.db_crypto import decrypt_db


class DBEncryptedError(Exception):
    """Raised when DBReader is constructed for an encrypted account without a key."""
    pass


class DBReader:
    """Read and parse WeChat MSG.db (v2 single-shard or v3 multi-shard) in
    read-only mode.  Transparently decrypts encrypted shards when a key is
    supplied."""

    def __init__(self, account: WeChatAccount, key: str | None = None):
        self._account = account
        self._key = key
        self._last_max_ts: int | None = None
        self._temp_paths: list[str] = []

        if account.is_encrypted and key is None:
            raise DBEncryptedError(
                f"Account {account.wxid} is encrypted but no key provided"
            )

    # ------------------------------------------------------------------
    # Path resolution
    # ------------------------------------------------------------------

    def _resolve_paths(self) -> list[str]:
        """Return list of readable SQLite file paths for all shards.

        For v2 (plaintext) accounts the original shard paths are returned
        as-is.  For v3 (encrypted) accounts each shard is decrypted to a
        temporary file.  Callers must invoke _cleanup_temp_paths() when done.
        """
        if not self._account.is_encrypted:
            return [p for p in self._account.shard_paths
                    if os.path.isfile(p)]

        self._temp_paths = []
        for shard in self._account.shard_paths:
            if not os.path.isfile(shard):
                continue
            tmp_path = decrypt_db(shard, self._key)
            if tmp_path:
                self._temp_paths.append(tmp_path)
        return self._temp_paths

    def _cleanup_temp_paths(self):
        """Delete decrypted temp files created by _resolve_paths."""
        for p in self._temp_paths:
            try:
                os.unlink(p)
            except OSError:
                pass
        self._temp_paths = []

    # ------------------------------------------------------------------
    # Message loading
    # ------------------------------------------------------------------

    def load_messages(
        self,
        talker_wxid: str,
        limit: int = 200,
        since_ts: int | None = None,
    ) -> list[ChatMessage]:
        """Load messages for a specific talker across all shards.

        Messages from each shard are merged, deduplicated by msgSvrId, and
        sorted by createTime.  *limit* is applied to the final result.
        """
        if not self._account.shard_paths:
            return []

        messages: list[ChatMessage] = []
        seen_ids: set[int] = set()

        try:
            for attempt in range(3):
                paths = self._resolve_paths()
                if not paths:
                    return []

                try:
                    for path in paths:
                        shard_msgs = self._read_single_shard(
                            path, talker_wxid, limit, since_ts
                        )
                        for m in shard_msgs:
                            if m.msg_svr_id not in seen_ids:
                                seen_ids.add(m.msg_svr_id)
                                messages.append(m)

                    # Sort by createTime and apply limit
                    messages.sort(key=lambda m: m.create_time)
                    if len(messages) > limit:
                        messages = messages[-limit:]

                    if messages:
                        self._last_max_ts = messages[-1].create_time
                    break
                except sqlite3.OperationalError:
                    time.sleep(0.2)
        finally:
            self._cleanup_temp_paths()

        return messages

    def _read_single_shard(
        self, path: str, talker_wxid: str,
        limit: int, since_ts: int | None,
    ) -> list[ChatMessage]:
        """Read messages from a single SQLite shard file.

        Returns messages most-recent-first (as produced by the SQL ORDER BY
        DESC query).  The caller is responsible for merging and sorting across
        shards.
        """
        if not os.path.isfile(path):
            return []

        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row

        # Auto-detect table: try MSG first, then ChatCRMsg, then ChatMsg
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('MSG', 'ChatCRMsg', 'ChatMsg')"
        )
        tables = [row[0] for row in cursor]
        if not tables:
            conn.close()
            return []

        # Priority: ChatCRMsg > ChatMsg (AppStore ChatMsg is often empty) > MSG
        table = "ChatCRMsg" if "ChatCRMsg" in tables else tables[0]
        if table in ("ChatCRMsg", "ChatMsg"):
            sql = ("SELECT MsgSvrID as msgSvrId, type, IsSender as isSend, "
                   "CreateTime as createTime, strTalker as talker, "
                   "strContent as content "
                   f"FROM {table} WHERE strTalker = ?")
        else:
            # WeChat 3.9.x MSG table uses PascalCase column names
            sql = ("SELECT MsgSvrID as msgSvrId, Type as type, "
                   "IsSender as isSend, CreateTime as createTime, "
                   "StrTalker as talker, StrContent as content "
                   "FROM MSG WHERE StrTalker = ?")
        params: list = [talker_wxid]
        if since_ts is not None:
            sql += " AND CreateTime > ?"
            params.append(since_ts)
        sql += " ORDER BY CreateTime DESC LIMIT ?"
        params.append(limit)

        cur = conn.execute(sql, params)
        messages: list[ChatMessage] = []
        for row in reversed(list(cur)):
            content = row["content"] or ""
            try:
                content_bytes = content.encode("latin1")
                content = content_bytes.decode("utf-8")
            except (UnicodeDecodeError, UnicodeEncodeError):
                try:
                    content = content.encode("latin1").decode(
                        "utf-8", errors="replace"
                    )
                except Exception:
                    content = str(content)

            messages.append(
                ChatMessage(
                    msg_svr_id=row["msgSvrId"] or 0,
                    msg_type=row["type"] or 0,
                    is_send=row["isSend"] or 0,
                    create_time=row["createTime"] or 0,
                    talker=row["talker"] or talker_wxid,
                    content=content,
                )
            )
        conn.close()
        return messages

    # ------------------------------------------------------------------
    # Fast count
    # ------------------------------------------------------------------

    def count_messages(self, talker_wxid: str) -> int:
        """Fast COUNT query across all shards — returns total messages for a talker."""
        if not self._account.shard_paths:
            return 0
        total = 0
        try:
            paths = self._resolve_paths()
            for path in paths:
                if not os.path.isfile(path):
                    continue
                conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' "
                    "AND name IN ('MSG', 'ChatCRMsg', 'ChatMsg')"
                )
                tables = [row[0] for row in cursor]
                if not tables:
                    conn.close()
                    continue
                # Priority: ChatCRMsg > ChatMsg > MSG
                table = "ChatCRMsg" if "ChatCRMsg" in tables else tables[0]
                if table in ("ChatCRMsg", "ChatMsg"):
                    cur = conn.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE strTalker = ?",
                        (talker_wxid,),
                    )
                else:
                    cur = conn.execute(
                        "SELECT COUNT(*) FROM MSG WHERE StrTalker = ?",
                        (talker_wxid,),
                    )
                total += cur.fetchone()[0]
                conn.close()
        finally:
            self._cleanup_temp_paths()
        return total

    # ------------------------------------------------------------------
    # Incremental & talker discovery
    # ------------------------------------------------------------------

    def load_incremental(
        self, talker_wxid: str
    ) -> list[ChatMessage]:
        """Load new messages since last read for real-time monitoring."""
        since = self._last_max_ts
        if since is None:
            return self.load_messages(talker_wxid)
        return self.load_messages(talker_wxid, since_ts=since)

    def load_all_contacts_with_messages(self) -> set[str]:
        """Return all distinct non-chatroom talker wxids across all shards."""
        if not self._account.shard_paths:
            return set()

        paths = self._resolve_paths()
        if not paths:
            return set()

        try:
            result: set[str] = set()
            for path in paths:
                if not os.path.isfile(path):
                    continue
                try:
                    conn = sqlite3.connect(
                        f"file:{path}?mode=ro", uri=True
                    )
                    # Try MSG first, then ChatMsg
                    tables_cur = conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' "
                        "AND name IN ('MSG', 'ChatCRMsg', 'ChatMsg')"
                    )
                    db_tables = [r[0] for r in tables_cur]
                    table = "ChatCRMsg" if "ChatCRMsg" in db_tables else (db_tables[0] if db_tables else None)
                    if table in ("ChatCRMsg", "ChatMsg"):
                        cur = conn.execute(f"SELECT DISTINCT strTalker FROM {table}")
                    elif table == "MSG":
                        cur = conn.execute("SELECT DISTINCT StrTalker FROM MSG")
                    else:
                        conn.close()
                        continue
                    for row in cur:
                        if row[0] and "@chatroom" not in str(row[0]):
                            result.add(row[0])
                    conn.close()
                except sqlite3.Error:
                    pass
            return result
        finally:
            self._cleanup_temp_paths()
