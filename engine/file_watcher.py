import os
import time

from PyQt6.QtCore import QObject, pyqtSignal

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

from models.chat_message import ChatMessage
from models.wechat_account import WeChatAccount
from engine.db_reader import DBReader


class MSGDbHandler(FileSystemEventHandler):
    """Watchdog handler for MSG.db modifications.

    Emits a simple 'db changed' notification via on_new_callback(wxid, None)
    when a DB file is modified.  The caller (MainWindow) is responsible for
    reloading the active contact's messages.
    """

    def __init__(self, account: WeChatAccount,
                 key: str | None,
                 on_new_callback):
        super().__init__()
        self._account = account
        self._key = key
        self._on_new = on_new_callback
        self._last_event_time = 0
        self._debounce_seconds = 0.5

    def on_modified(self, event):
        if event.is_directory:
            return
        src = event.src_path.replace("/", os.sep)
        if not src.endswith(".db"):
            return

        now = time.time()
        if now - self._last_event_time < self._debounce_seconds:
            return
        self._last_event_time = now

        self._on_new(self._account.wxid, None)


class FileWatcher(QObject):
    """Monitors MSG.db files for changes using watchdog.

    Supports both v2 (single MSG.db) and v3 (Multi/MSG*.db shards) via
    recursive directory watching.  Emits the account wxid when any DB
    file changes; the caller reloads the active contact.
    """

    new_messages = pyqtSignal(str, object)  # wxid, list[Message] or None

    def __init__(self):
        super().__init__()
        self._observer: Observer | None = None
        self._handlers: dict[str, MSGDbHandler] = {}

    def start_watching(self, wxid_to_path: dict[str, str],
                       key: str | None = None):
        """Start monitoring MSG.db for each wxid."""
        self._observer = Observer()
        for wxid, data_dir in wxid_to_path.items():
            msg_dir = os.path.join(data_dir, "Msg")
            if not os.path.isdir(msg_dir):
                continue

            multi_dir = os.path.join(msg_dir, "Multi")
            if os.path.isdir(multi_dir):
                shard_paths = [
                    os.path.join(multi_dir, f"MSG{i}.db")
                    for i in range(10)
                    if os.path.isfile(os.path.join(multi_dir, f"MSG{i}.db"))
                ]
                account = WeChatAccount(
                    wxid=wxid, data_dir=data_dir, msg_dir=msg_dir,
                    version=3, shard_paths=shard_paths,
                    micro_msg_db=os.path.join(msg_dir, "MicroMsg.db"),
                )
            else:
                msg_db = os.path.join(msg_dir, "MSG.db")
                account = WeChatAccount(
                    wxid=wxid, data_dir=data_dir, msg_dir=msg_dir,
                    version=2,
                    shard_paths=[msg_db] if os.path.isfile(msg_db) else [],
                    micro_msg_db=os.path.join(msg_dir, "MicroMsg.db"),
                )

            handler = MSGDbHandler(
                account, key=key,
                on_new_callback=self._on_file_changed,
            )
            self._observer.schedule(handler, msg_dir, recursive=True)
            self._handlers[wxid] = handler
        try:
            self._observer.start()
            return True
        except Exception:
            return False

    def _on_file_changed(self, wxid: str, _messages):
        self.new_messages.emit(wxid, None)  # None = db changed, caller reloads

    def stop(self):
        if self._observer and self._observer.is_alive():
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None
        self._handlers.clear()
