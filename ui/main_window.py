from PyQt6.QtWidgets import (
    QMainWindow, QSplitter, QMenuBar, QMenu, QStatusBar, QLabel,
    QWidget, QVBoxLayout, QMessageBox, QApplication, QFileDialog,
)
import os

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QAction, QPixmap

from config.settings import load_config, save_config, DEFAULT_CONFIG, ConfigCorruptError
from engine.wechat_scanner import WeChatScanner
from engine.contact_parser import ContactParser
from engine.db_reader import DBReader, DBEncryptedError
from engine.file_watcher import FileWatcher
from engine.key_extractor import KeyExtractor
from models.wechat_account import WeChatAccount
from engine.api_client import ApiClient, ApiError
from engine.analysis_engine import AnalysisEngine
from models.analysis_result import AnalysisResult
from ui.contact_panel import ContactPanel
from ui.chat_view import ChatView
from ui.dashboard import Dashboard
from ui.settings_dialog import SettingsDialog


class KeyExtractionWorker(QThread):
    """Background thread for WeChat database key extraction."""

    key_ready = pyqtSignal(str, str)     # (key hex, wxid)
    key_failed = pyqtSignal(str, object)  # (message, extractor with missing_deps)

    def __init__(self, extractor: KeyExtractor):
        super().__init__()
        self._extractor = extractor

    def run(self):
        key = self._extractor.extract_key()
        if key:
            self.key_ready.emit(key, self._extractor.key_wxid or "")
        else:
            debug = self._extractor.debug_log
            missing = self._extractor.missing_deps
            if missing:
                deps_text = "、".join(missing)
                msg = (
                    f"无法解密微信数据库\n\n"
                    f"缺失依赖: {deps_text}\n\n"
                    f"是否自动安装缺失的依赖？\n\n"
                    f"--- 调试信息 ---\n{debug}"
                )
            else:
                msg = (
                    "无法解密微信数据库\n\n"
                    "请确认微信已启动（pymem 需要读取进程内存）\n\n"
                    f"--- 调试信息 ---\n{debug}"
                )
            self.key_failed.emit(msg, self._extractor)


class InstallWorker(QThread):
    """Background thread for pip install without blocking UI."""

    pip_installed = pyqtSignal(bool, str)

    def __init__(self, extractor: KeyExtractor):
        super().__init__()
        self._extractor = extractor

    def run(self):
        ok, msg = self._extractor.install_missing()
        self.pip_installed.emit(ok, msg)


class CountWorker(QThread):
    """Background thread: fast COUNT query across all shards for a contact."""

    count_ready = pyqtSignal(int)          # total message count
    error_occurred = pyqtSignal(str)

    def __init__(self, wxid: str, accounts: list,
                 key: str | None, key_wxid: str | None):
        super().__init__()
        self._wxid = wxid
        self._accounts = accounts
        self._key = key
        self._key_wxid = key_wxid

    def run(self):
        total = 0
        for acc in self._accounts:
            acc_key = self._key if (
                not self._key_wxid or acc.wxid == self._key_wxid
            ) else None
            try:
                reader = DBReader(acc, key=acc_key)
            except DBEncryptedError:
                if acc_key is None and acc.is_encrypted:
                    continue
                continue
            try:
                total += reader.count_messages(self._wxid)
            except Exception:
                continue
        self.count_ready.emit(total)


class MessageLoadWorker(QThread):
    """Background thread: decrypt DBs and load messages without UI freeze."""

    messages_ready = pyqtSignal(list)   # list[ChatMessage]
    error_occurred = pyqtSignal(str)
    debug_line = pyqtSignal(str)         # per-message transcription debug

    def __init__(self, wxid: str, accounts: list,
                 key: str | None, key_wxid: str | None,
                 limit: int = 200):
        super().__init__()
        self._wxid = wxid
        self._accounts = accounts
        self._key = key
        self._key_wxid = key_wxid
        self._limit = limit

    def run(self):
        all_messages = []
        shard_count = 0
        for acc in self._accounts:
            acc_key = self._key if (
                not self._key_wxid or acc.wxid == self._key_wxid
            ) else None
            try:
                reader = DBReader(acc, key=acc_key)
            except DBEncryptedError:
                if acc_key is None and acc.is_encrypted:
                    continue  # Skip encrypted accounts when no key
                else:
                    self.error_occurred.emit(
                        "此联系人的消息已加密，请先解密数据库"
                    )
                    return
            try:
                shard_msgs = reader.load_messages(
                    self._wxid, limit=self._limit
                )
                shard_count += 1
                for msg in shard_msgs:
                    msg._msg_dir = acc.msg_dir
                all_messages.extend(shard_msgs)
            except Exception as e:
                # Silently skip accounts with wrong keys
                continue

        seen_ids = set()
        deduped = []
        for m in sorted(all_messages, key=lambda x: x.create_time):
            if m.msg_svr_id not in seen_ids:
                seen_ids.add(m.msg_svr_id)
                deduped.append(m)

        # ── Transcribe voice and emoji messages ──
        from engine.content_parser import ContentParser
        from engine.tencent_stt import TencentSTT
        from config.settings import load_config

        config = load_config()
        parser = ContentParser()
        stt = TencentSTT(
            secret_id=config.get("tencent_secret_id", ""),
            secret_key=config.get("tencent_secret_key", ""),
        )

        voice_total = voice_file_ok = voice_stt_ok = voice_fallback = 0
        emoji_total = emoji_parsed = 0
        asr_configured = bool(config.get("tencent_secret_id"))

        for msg in deduped:
            if msg.msg_type == 34 and msg.transcript is None:
                voice_total += 1
                msg_dir = getattr(msg, '_msg_dir', '')
                # Diagnostic: dump raw XML content and msg_dir
                raw_preview = (msg.content[:200] + "...") if len(msg.content) > 200 else msg.content
                self.debug_line.emit(
                    f"  [语音诊断] msg_svr_id={msg.msg_svr_id} "
                    f"msg_dir={msg_dir}"
                )
                self.debug_line.emit(
                    f"    raw_content={repr(raw_preview)}"
                )
                file_path, duration = parser.parse_voice(msg.content, msg_dir)
                dur_s = duration // 1000
                # --- WeChat 3.x: audio from MediaMSG*.db ---
                if file_path == "media_msg":
                    from engine.voice_decoder import VoiceDecoder
                    try:
                        from pysilk import decode
                        _has_pysilk = True
                    except ImportError:
                        _has_pysilk = False

                    wav_path = VoiceDecoder.decode(
                        msg.msg_svr_id, self._accounts,
                        key=self._key or getattr(self, '_decrypt_key_wxid', ''),
                    )
                    if wav_path and os.path.isfile(wav_path):
                        wav_size = os.path.getsize(wav_path)
                        if wav_size > 3 * 1024 * 1024:
                            os.unlink(wav_path)
                            msg.transcript = "[语音: 过长]"
                            self.debug_line.emit(
                                f"  [语音] msg_svr_id={msg.msg_svr_id} v3 WAV过大({wav_size//1024}KB) → 跳过"
                            )
                        else:
                            voice_file_ok += 1
                            self.debug_line.emit(
                                f"  [语音] msg_svr_id={msg.msg_svr_id} v3 MediaMSG解码成功 "
                                f"({wav_size//1024}KB WAV, {dur_s}s) → 转录中..."
                            )
                            result = stt.transcribe(wav_path, msg.msg_svr_id)
                            if result is not None:
                                voice_stt_ok += 1
                                msg.transcript = result
                                preview = (result[:30] + "...") if len(result) > 30 else result
                                self.debug_line.emit(
                                    f"  [语音] msg_svr_id={msg.msg_svr_id} 转录成功 → \"{preview}\""
                                )
                            else:
                                voice_fallback += 1
                                msg.transcript = f"[语音: {dur_s}s]"
                                self.debug_line.emit(
                                    f"  [语音] msg_svr_id={msg.msg_svr_id} 转录失败 → 降级标签"
                                )
                            try:
                                os.unlink(wav_path)
                            except OSError:
                                pass
                    else:
                        voice_fallback += 1
                        msg.transcript = f"[语音: {dur_s}s]"
                        reason = "缺少 pysilk" if not _has_pysilk else "解码失败或文件缺失"
                        self.debug_line.emit(
                            f"  [语音] msg_svr_id={msg.msg_svr_id} v3 {reason} → 降级标签"
                        )
                elif not file_path or not os.path.isfile(file_path):
                    voice_fallback += 1
                    msg.transcript = f"[语音: {dur_s}s]"
                    self.debug_line.emit(
                        f"  [语音] msg_svr_id={msg.msg_svr_id} 文件未找到 → 降级标签"
                    )
                    continue
                elif duration > 60000:
                    msg.transcript = "[语音: 过长]"
                    self.debug_line.emit(
                        f"  [语音] msg_svr_id={msg.msg_svr_id} 过长({dur_s}s) → 跳过"
                    )
                elif os.path.getsize(file_path) > 3 * 1024 * 1024:
                    msg.transcript = "[语音: 过长]"
                    self.debug_line.emit(
                        f"  [语音] msg_svr_id={msg.msg_svr_id} 文件过大({os.path.getsize(file_path)//1024}KB) → 跳过"
                    )
                else:
                    voice_file_ok += 1
                    self.debug_line.emit(
                        f"  [语音] msg_svr_id={msg.msg_svr_id} "
                        f"文件={os.path.basename(file_path)} 时长={dur_s}s → 转录中..."
                    )
                    result = stt.transcribe(file_path, msg.msg_svr_id)
                    if result is not None:
                        voice_stt_ok += 1
                        preview = (result[:30] + "...") if len(result) > 30 else result
                        self.debug_line.emit(
                            f"  [语音] msg_svr_id={msg.msg_svr_id} 转录成功"
                        )
                        self.debug_line.emit(
                            f"         → \"{preview}\""
                        )
                        msg.transcript = result
                    else:
                        voice_fallback += 1
                        self.debug_line.emit(
                            f"  [语音] msg_svr_id={msg.msg_svr_id} 转录失败 → 降级标签"
                        )
                        msg.transcript = f"[语音: {dur_s}s]"
            elif msg.msg_type == 47 and msg.transcript is None:
                emoji_total += 1
                # Diagnostic: dump raw XML content
                raw_preview = (msg.content[:200] + "...") if len(msg.content) > 200 else msg.content
                self.debug_line.emit(
                    f"  [表情诊断] msg_svr_id={msg.msg_svr_id} "
                    f"raw_content={repr(raw_preview)}"
                )
                emoji_text = parser.parse_emoji(msg.content)
                if emoji_text:
                    emoji_parsed += 1
                    msg.transcript = emoji_text
                    self.debug_line.emit(
                        f"  [表情] msg_svr_id={msg.msg_svr_id} → \"{emoji_text}\""
                    )
                else:
                    msg.transcript = "[自定义表情]"
                    self.debug_line.emit(
                        f"  [表情] msg_svr_id={msg.msg_svr_id} 自定义表情 → \"[自定义表情]\""
                    )

        # Summary
        if voice_total > 0 or emoji_total > 0:
            parts = []
            if voice_total > 0:
                parts.append(
                    f"语音: {voice_total}条 "
                    f"(文件OK={voice_file_ok} STT成功={voice_stt_ok} 降级={voice_fallback})"
                )
                if not asr_configured:
                    parts.append("[ASR密钥未配置,全部降级]")
            if emoji_total > 0:
                parts.append(
                    f"表情: {emoji_total}条 (已解析={emoji_parsed})"
                )
            self.debug_line.emit("  转录汇总: " + ", ".join(parts))

        self.messages_ready.emit(deduped)


class AnalysisWorker(QThread):
    """Worker thread for running LLM analysis without blocking UI."""

    result_ready = pyqtSignal(object)  # AnalysisResult
    error_occurred = pyqtSignal(str)  # Error message
    one_way_detected = pyqtSignal()  # One-way communication

    def __init__(self, engine: AnalysisEngine, messages, contact_wxid: str):
        super().__init__()
        self.engine = engine
        self.messages = messages
        self.contact_wxid = contact_wxid

    def run(self):
        try:
            result = self.engine.analyze(self.messages, self.contact_wxid)
            if self.engine.check_one_way(self.messages):
                self.one_way_detected.emit()
            self.result_ready.emit(result)
        except ApiError as e:
            msg = self._format_error(e)
            self.error_occurred.emit(msg)

    def _format_error(self, e: ApiError) -> str:
        if e.code == 0 and e.body == "timeout":
            return "API 请求超时，请检查网络"
        if e.code == 0 and e.body == "connection_error":
            return "无法连接 API 服务器，请检查网络和配置"
        if e.code == 0 and e.body == "empty_choices":
            return "API 返回数据为空"
        if e.code == 0 and e.body == "empty_content":
            return "API 返回内容为空"
        if e.code == 401 or e.code == 403:
            return "API 密钥无效，请检查配置"
        if e.code == 429:
            if e.retry_after:
                return f"请求过于频繁，请稍后重试 (等待 {e.retry_after}s)"
            return "请求过于频繁，请稍后重试"
        if e.code == 0:
            return f"API 返回格式异常: {e.body[:200]}"
        return f"API 错误 ({e.code}): {e.body[:200]}"


class MainWindow(QMainWindow):
    """Main window with 3-pane layout: contacts | chat | dashboard."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("ChatSense")
        self.setMinimumSize(900, 600)
        self.resize(1200, 750)

        # Engine state
        self.scanner = WeChatScanner()
        self._wxid_to_path: dict[str, str] = {}
        self._wxid_to_name: dict[str, str] = {}
        self._active_wxid: str | None = None
        self._active_messages: list = []
        self._analysis_worker: AnalysisWorker | None = None
        self._decrypt_key: str | None = None
        self._accounts: list[WeChatAccount] = []

        # File watcher
        self.watcher = FileWatcher()

        # Debug log accumulator
        self._debug_lines: list[str] = []

        # Config — handle corruption gracefully
        try:
            self._config = load_config()
        except ConfigCorruptError:
            self._config = dict(DEFAULT_CONFIG)
            self._config_corrupt = True
        else:
            self._config_corrupt = False

        self._build_ui()
        self._init_app()

    def _log_debug(self, msg: str):
        """Append debug line with timestamp, push to dashboard panel."""
        from datetime import datetime
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        line = f"[{ts}] {msg}"
        self._debug_lines.append(line)
        self.dashboard.append_debug(line)

    def _build_ui(self):
        # Central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)

        # Menu bar
        menubar = self.menuBar()

        file_menu = menubar.addMenu("File")
        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)
        refresh_action = QAction("Refresh", self)
        refresh_action.triggered.connect(self._reload)
        file_menu.addAction(refresh_action)
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        help_menu = menubar.addMenu("Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

        # 3-pane splitter
        self.splitter = QSplitter(Qt.Orientation.Horizontal)

        self.contact_panel = ContactPanel()
        self.contact_panel.contact_selected.connect(self._on_contact_selected)
        self.splitter.addWidget(self.contact_panel)

        self.chat_view = ChatView()
        self.splitter.addWidget(self.chat_view)

        self.dashboard = Dashboard()
        self.dashboard.analyze_requested.connect(self._on_analyze)
        self.dashboard.export_requested.connect(self._on_export)
        self.dashboard.load_count_changed.connect(self._on_reload_messages)
        self.splitter.addWidget(self.dashboard)

        # Set proportions (contacts 200px : chat flex : dashboard flex)
        self.splitter.setSizes([220, 480, 500])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 1)

        layout.addWidget(self.splitter)

        # Status bar
        self.statusbar = QStatusBar()
        self.setStatusBar(self.statusbar)
        self.status_label = QLabel("就绪")
        self.statusbar.addWidget(self.status_label)

        self.ws_status = QLabel("")
        self.statusbar.addPermanentWidget(self.ws_status)
        self.msg_count_label = QLabel("")
        self.statusbar.addPermanentWidget(self.msg_count_label)
        self.api_status = QLabel("")
        self.statusbar.addPermanentWidget(self.api_status)

    def _init_app(self):
        """Startup: scan WeChat, load contacts, populate UI."""
        # Show config corruption warning if needed
        if self._config_corrupt:
            QMessageBox.warning(
                self,
                "配置文件损坏",
                "配置文件损坏，请重新配置 API Key 和 API URL",
            )

        accounts = self.scanner.find_accounts()
        if not accounts:
            self._enter_no_wechat_state()
            self._log_debug("启动: 未找到微信数据目录")
            return

        self._accounts = accounts
        plain = [a for a in accounts if not a.is_encrypted]
        enc = [a for a in accounts if a.is_encrypted]
        self._log_debug(
            f"启动: 找到 {len(accounts)} 个账户 "
            f"(明文={len(plain)}, 加密={len(enc)})"
        )
        for a in accounts:
            self._log_debug(
                f"  账户 wxid={a.wxid} v{a.version} "
                f"分片={len(a.shard_paths)} 加密={a.is_encrypted}"
            )

        # Build wxid -> path mapping for file watcher
        self._wxid_to_path = {a.wxid: a.data_dir for a in accounts}

        # Separate encrypted and plaintext accounts
        encrypted_accounts = [a for a in accounts if a.is_encrypted]
        plaintext_accounts = [a for a in accounts if not a.is_encrypted]

        # If there are encrypted accounts, extract key
        if encrypted_accounts:
            self._init_key_extraction(
                accounts, encrypted_accounts, plaintext_accounts
            )
        else:
            self._load_contacts_and_continue(accounts, key=None)

        # Version check
        version = self.scanner.detect_version()
        if version:
            major, minor = version
            if major >= 3:
                self.ws_status.setText(f"微信 {major}.x | 已解密")
                self.ws_status.setStyleSheet("color: #43A047")

        # API status check
        if not self._config.get("api_key"):
            self.api_status.setText("API 未配置")
            self.api_status.setStyleSheet("color: #FFA726")
        else:
            self.api_status.setText("API 就绪")
            self.api_status.setStyleSheet("color: #43A047")

    def _init_key_extraction(self, all_accounts: list[WeChatAccount],
                             encrypted_accounts: list[WeChatAccount],
                             plaintext_accounts: list[WeChatAccount]):
        """Start background key extraction for encrypted WeChat databases."""
        self.status_label.setText("正在提取密钥...")

        self._key_worker = KeyExtractionWorker(KeyExtractor())
        self._key_worker.key_ready.connect(
            lambda key, wxid: self._load_contacts_and_continue(
                all_accounts, key=key, key_wxid=wxid)
        )
        self._key_worker.key_failed.connect(
            lambda msg, extractor: self._on_key_extraction_failed(
                all_accounts, encrypted_accounts, plaintext_accounts, msg, extractor
            )
        )
        self._key_worker.start()

    def _load_contacts_and_continue(self, accounts: list[WeChatAccount],
                                   key: str | None, key_wxid: str = ""):
        """Load contacts from all accounts and finish initialization."""
        # Only keep accounts matching the key's wxid (skip accounts with different keys)
        if key and key_wxid:
            accounts = [a for a in accounts if a.wxid == key_wxid]
            self._accounts = accounts  # update the stored list

        if key:
            self._decrypt_key = key
            self._decrypt_key_wxid = key_wxid
            self.status_label.setText("密钥提取成功")
            self.status_label.setStyleSheet("color: #43A047")
            # Cache the working key for future use
            config = load_config()
            if config.get("cached_wx_key") != key:
                config["cached_wx_key"] = key
                save_config(config)

        # Build talker set from chat messages (real contacts — people you chatted with)
        all_contacts: dict[str, str] = {}
        key_wxid = getattr(self, '_decrypt_key_wxid', None)
        talker_set: set[str] = set()
        for acc in accounts:
            acc_key = key if (not key_wxid or acc.wxid == key_wxid) else None
            try:
                reader = DBReader(acc, key=acc_key)
            except DBEncryptedError:
                self._log_debug(f"  跳过加密账户 {acc.wxid} (无密钥)")
                continue
            talkers = reader.load_all_contacts_with_messages()
            self._log_debug(f"  账户 {acc.wxid}: {len(talkers)} 个联系人")
            talker_set.update(talkers)
        self._log_debug(f"联系人发现: 共 {len(talker_set)} 个唯一 wxid")

        # Load display names from MicroMsg.db for these talkers
        for acc in accounts:
            acc_key = key if (not key_wxid or acc.wxid == key_wxid) else None
            try:
                parser = ContactParser(acc, key=acc_key)
            except Exception:
                parser = ContactParser(acc, key=None)
            contacts = parser.load_contacts()
            for c_wxid, name in contacts.items():
                if c_wxid in talker_set and c_wxid not in all_contacts:
                    all_contacts[c_wxid] = name

        # Fill in any talkers without a name from MicroMsg.db
        for talker in talker_set:
            if talker not in all_contacts:
                all_contacts[talker] = talker

        self._wxid_to_name = all_contacts

        # Filter: exclude public accounts, system accounts, group chats
        _sys_prefixes = ("gh_", "newsapp_", "weixin_", "ibroadcast_",
                         "filehelper", "medianote", "notifymessage",
                         "qmessage", "qqmail", "tmessage")
        personal_contacts = {
            wxid: name for wxid, name in all_contacts.items()
            if not wxid.startswith(_sys_prefixes) and "@chatroom" not in wxid
        }
        self._personal_contacts = personal_contacts

        self._log_debug(
            f"联系人解析完成: {len(all_contacts)} wxid, "
            f"{len(personal_contacts)} 个人联系人"
        )

        if not personal_contacts:
            self._enter_empty_db_state()
            self._log_debug("无个人联系人，进入空状态")
            return

        self.contact_panel.load_contacts(personal_contacts)

        # Start file watcher
        started = self.watcher.start_watching(
            self._wxid_to_path, key=key
        )
        self.watcher.new_messages.connect(self._on_new_messages)

        # Polling fallback: periodically check newest shard mtime
        self._last_shard_mtime = 0
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_shard_changes)
        self._poll_timer.start(3000)  # every 3 seconds

        self.status_label.setText("监控中")
        self.status_label.setStyleSheet("color: #43A047")

        if started:
            self.ws_status.setText("监控中 ●")
            self.ws_status.setStyleSheet("color: #43A047")
        else:
            self.ws_status.setText("文件监控启动失败")
            self.ws_status.setStyleSheet("color: #FFA726")

        # Decryption status
        encrypted_count = sum(1 for a in self._accounts if a.is_encrypted)
        if encrypted_count > 0 and key:
            self.api_status.setText(f"解密: {encrypted_count}/{encrypted_count} 就绪")
            self.api_status.setStyleSheet("color: #43A047")
        elif encrypted_count > 0 and not key:
            self.api_status.setText(f"解密: 0/{encrypted_count}")
            self.api_status.setStyleSheet("color: #E53935")

    def _poll_shard_changes(self):
        """Polling fallback: check newest shard mtime and reload if changed."""
        if not self._active_wxid:
            return
        if not self._accounts:
            return
        # Find the newest MSG shard across all accounts
        newest_mtime = 0
        for acc in self._accounts:
            for shard in acc.shard_paths:
                if os.path.isfile(shard):
                    mtime = os.path.getmtime(shard)
                    if mtime > newest_mtime:
                        newest_mtime = mtime
        if newest_mtime == 0:
            return
        if self._last_shard_mtime == 0:
            self._last_shard_mtime = newest_mtime
            return
        if newest_mtime > self._last_shard_mtime:
            self._last_shard_mtime = newest_mtime
            limit = self.dashboard.get_load_count()
            self._load_messages_with_limit(limit)

    def _on_key_extraction_failed(self, all_accounts: list[WeChatAccount],
                                  encrypted_accounts: list[WeChatAccount],
                                  plaintext_accounts: list[WeChatAccount],
                                  reason: str, extractor: "KeyExtractor"):
        """Handle key extraction failure: show dialog with Retry/Ignore/Install."""
        self.status_label.setText("密钥提取失败")
        self.status_label.setStyleSheet("color: #E53935")

        # Split debug info from main message
        parts = reason.split("--- 调试信息 ---\n", 1)
        main_text = parts[0].strip()
        debug_info = parts[1].strip() if len(parts) > 1 else ""

        detail = (
            f"检测到 {len(encrypted_accounts)} 个加密数据库（微信 3.x/4.x）\n\n"
            f"{main_text}"
        )

        missing = extractor.missing_deps
        # Buttons: Install(Yes) | Manual Key(No) | Retry | Ignore
        buttons = QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Ignore
        has_install = bool(missing)

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("微信数据解密")
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setText(detail)
        if debug_info:
            msg_box.setDetailedText(debug_info)

        if has_install:
            msg_box.addButton("安装依赖", QMessageBox.ButtonRole.YesRole)
        msg_box.addButton("手动输入密钥", QMessageBox.ButtonRole.NoRole)
        msg_box.addButton(QMessageBox.StandardButton.Retry)
        msg_box.addButton(QMessageBox.StandardButton.Ignore)

        reply = msg_box.exec()

        # Check which button was clicked by role
        clicked_button = msg_box.clickedButton()
        if clicked_button and clicked_button.text() == "安装依赖":
            self.status_label.setText("正在安装缺失依赖...")
            self._install_worker = InstallWorker(extractor)
            self._install_worker.pip_installed.connect(
                lambda ok, msg: self._on_install_finished(
                    ok, msg, all_accounts, encrypted_accounts,
                    plaintext_accounts
                )
            )
            self._install_worker.start()
            return

        if clicked_button and clicked_button.text() == "手动输入密钥":
            self._prompt_manual_key(all_accounts, encrypted_accounts,
                                    plaintext_accounts)
            return

        if reply == QMessageBox.StandardButton.Retry:
            self._init_key_extraction(
                all_accounts, encrypted_accounts, plaintext_accounts
            )
            return

        if reply == QMessageBox.StandardButton.Ignore:
            # Load all accounts. Encrypted accounts appear with wxid as
            # display name, clicking shows placeholder message.
            self._load_contacts_and_continue(all_accounts, key=None)
            self.ws_status.setText(
                f"解密: 0/{len(encrypted_accounts)} | 跳过"
            )
            self.ws_status.setStyleSheet("color: #FFA726")

    def _prompt_manual_key(self, all_accounts, encrypted_accounts,
                           plaintext_accounts):
        """Show dialog for manual key entry."""
        from PyQt6.QtWidgets import QInputDialog, QLineEdit
        text, ok = QInputDialog.getText(
            self, "手动输入密钥",
            "请输入微信数据库密钥（64位十六进制字符串）：\n\n"
            "可尝试以下方式获取密钥：\n"
            "  pip install pywxdump\n"
            "  python -c \"from pywxdump.wx_core.wx_info import get_info_details; "
            "import pymem; pm=pymem.Pymem('Weixin.exe'); "
            "print(get_info_details(pm.process_id, {}))\"",
            QLineEdit.EchoMode.Password,
        )
        if not ok or not text:
            return
        text = text.strip()
        if len(text) != 64 or not all(c in '0123456789abcdefABCDEF' for c in text):
            QMessageBox.warning(self, "密钥格式错误",
                                "密钥必须是64位十六进制字符串")
            return

        # Validate against first encrypted account's DB
        from engine.db_crypto import verify_key, decrypt_db
        valid = False
        for acc in encrypted_accounts:
            if acc.shard_paths and os.path.isfile(acc.shard_paths[0]):
                if verify_key(text, acc.shard_paths[0]):
                    valid = True
                    break
                # Also try decrypt_db
                result = decrypt_db(acc.shard_paths[0], text)
                if result:
                    import sqlite3
                    try:
                        conn = sqlite3.connect(f"file:{result}?mode=ro", uri=True)
                        conn.execute("SELECT 1")
                        conn.close()
                        valid = True
                        break
                    except sqlite3.Error:
                        pass

        if valid:
            self.status_label.setText("密钥验证成功")
            self.status_label.setStyleSheet("color: #43A047")
            self._load_contacts_and_continue(all_accounts, key=text)
        else:
            QMessageBox.warning(self, "密钥无效",
                                "该密钥无法解密数据库，请检查后重试")

    def _on_install_finished(self, ok: bool, msg: str,
                             all_accounts: list[WeChatAccount],
                             encrypted_accounts: list[WeChatAccount],
                             plaintext_accounts: list[WeChatAccount]):
        """Handle completion of background pip install."""
        if ok:
            self.status_label.setText("依赖安装成功，正在重试...")
            self._init_key_extraction(
                all_accounts, encrypted_accounts, plaintext_accounts
            )
        else:
            QMessageBox.critical(
                self, "安装失败",
                f"自动安装失败:\n{msg}"
            )

    def _enter_no_wechat_state(self):
        checked = self.scanner.checked_paths
        paths_text = "\n".join(f"  • {p}" for p in checked) if checked else ""
        detail = (
            f"未找到微信数据目录\n\n已搜索以下路径：\n{paths_text}\n\n"
            f"请确认微信已安装并至少登录过一次。"
        )
        self.status_label.setText("未找到微信数据目录")
        self.status_label.setStyleSheet("color: #E53935")
        self.contact_panel.load_contacts({})
        self.chat_view.show_placeholder(detail)

        reply = QMessageBox.question(
            self,
            "未找到微信数据",
            f"{detail}\n\n是否手动选择微信数据目录？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._browse_wechat_dir()

    def _browse_wechat_dir(self):
        path = QFileDialog.getExistingDirectory(
            self, "选择微信数据目录",
            os.path.join(os.path.expanduser("~"), "Documents"),
        )
        if not path:
            return
        self.scanner = WeChatScanner(base_path=path)
        self._init_app()

    def _enter_empty_db_state(self):
        self.status_label.setText("暂无消息记录")
        self.chat_view.show_placeholder("暂无消息记录")

    def _on_contact_selected(self, wxid: str, display_name: str):
        self._active_wxid = wxid
        self.contact_panel.clear_unread(wxid)

        if not self._accounts:
            self.chat_view.show_placeholder("无法读取消息")
            return

        self.chat_view.set_contact(display_name)
        self.chat_view.show_placeholder("统计中...")
        self.dashboard.show_placeholder()
        self.dashboard.total_label.setText(f"联系人: {display_name}")
        self._log_debug(f"选中联系人: {display_name} (wxid={wxid})")
        self._log_debug(f"账户数: {len(self._accounts)}, 密钥: {'已获取' if self._decrypt_key else '无'}")

        # Step 1: Fast COUNT query to know total messages
        self._count_worker = CountWorker(
            wxid, self._accounts,
            key=self._decrypt_key,
            key_wxid=getattr(self, '_decrypt_key_wxid', None),
        )
        self._count_worker.count_ready.connect(self._on_total_count_ready)
        self._count_worker.error_occurred.connect(self._on_count_error)
        self._count_worker.start()
        self._log_debug("COUNT 查询已启动...")

    def _on_total_count_ready(self, total: int):
        """COUNT query complete — update dashboard, then auto-load with spinner value."""
        display_name = self._wxid_to_name.get(self._active_wxid or "", self._active_wxid or "?")
        self._log_debug(
            f"COUNT 完成: {display_name} 共 {total:,} 条消息"
        )
        self.dashboard.set_total_count(total)

        if total == 0:
            self.chat_view.show_placeholder("暂无消息记录")
            self.dashboard.loaded_info_label.setText("")
            self._log_debug("消息数为 0，跳过加载")
            return

        limit = self.dashboard.get_load_count()
        self._log_debug(
            f"准备加载: limit={limit} (总共 {total:,})"
        )
        self._load_messages_with_limit(limit)

    def _on_count_error(self, error_msg: str):
        self._log_debug(f"COUNT 查询失败: {error_msg}")
        # Fall back to loading with default limit
        limit = self.dashboard.get_load_count()
        self._load_messages_with_limit(limit)

    def _on_reload_messages(self, limit: int):
        """User changed load count and clicked reload."""
        self._log_debug(
            f"重新加载消息: limit={limit} (总共 {self.dashboard._total_msg_count:,})"
        )
        self.chat_view.show_placeholder("加载中...")
        self._load_messages_with_limit(limit)

    def _load_messages_with_limit(self, limit: int):
        # Stop previous worker if still running
        if hasattr(self, '_msg_worker') and self._msg_worker and self._msg_worker.isRunning():
            self._msg_worker.quit()
            self._msg_worker.wait(3000)
        self._msg_worker = MessageLoadWorker(
            self._active_wxid, self._accounts,
            key=self._decrypt_key,
            key_wxid=getattr(self, '_decrypt_key_wxid', None),
            limit=limit,
        )
        self._msg_worker.messages_ready.connect(self._on_messages_loaded)
        self._msg_worker.error_occurred.connect(self._on_messages_error)
        self._msg_worker.debug_line.connect(self._log_debug)
        self._msg_worker.start()

    def _on_messages_loaded(self, messages: list):
        self._active_messages = messages
        text_count = sum(1 for m in messages if m.is_text)
        total_count = self.dashboard._total_msg_count  # may be 0 if COUNT didn't run
        wxid = self._active_wxid or "?"
        display_name = self._wxid_to_name.get(wxid, wxid)

        self._log_debug(
            f"消息加载完成: {display_name}"
        )
        self._log_debug(
            f"  已加载 {len(messages)} 条 (文本 {text_count} 条, 非文本 {len(messages) - text_count} 条)"
        )
        if total_count:
            pct = len(messages) / total_count * 100 if total_count > 0 else 0
            self._log_debug(
                f"  占比: {len(messages)}/{total_count} ({pct:.1f}%)"
            )
            # Message type breakdown
            type_counts: dict[int, int] = {}
            for m in messages:
                t = m.msg_type
                type_counts[t] = type_counts.get(t, 0) + 1
            type_parts = []
            for t, c in sorted(type_counts.items()):
                label = {1: "文本", 3: "图片", 34: "语音", 43: "视频", 47: "表情", 49: "链接/文件"}.get(t, f"类型{t}")
                type_parts.append(f"{label}:{c}")
            self._log_debug(f"  消息类型: {', '.join(type_parts)}")

        if messages:
            from datetime import datetime
            self._log_debug(
                f"  时间范围: {datetime.fromtimestamp(messages[0].create_time).strftime('%Y-%m-%d %H:%M')}"
                f" ~ {datetime.fromtimestamp(messages[-1].create_time).strftime('%Y-%m-%d %H:%M')}"
            )
            # Check send/receive ratio
            sent = sum(1 for m in messages if m.is_from_me)
            recv = len(messages) - sent
            self._log_debug(f"  发送/接收: {sent}/{recv} ({sent/len(messages)*100:.1f}% / {recv/len(messages)*100:.1f}%)")

        # Load cached analysis FIRST (may call show_placeholder, which clears labels)
        self._load_cached_analysis()

        if not messages:
            self.chat_view.show_placeholder("暂无消息记录")
        else:
            self.chat_view.load_messages(messages)
            self.msg_count_label.setText(f"消息: {len(messages)}")

        # Set loaded info AFTER _load_cached_analysis to not be cleared by show_placeholder
        self.dashboard.set_loaded_info(len(messages), text_count)
        self.dashboard.set_active_context(
            self._active_wxid or "", self._active_messages
        )
        # Show reload button if loaded count differs from current spinner value
        current_limit = self.dashboard.get_load_count()
        if current_limit != getattr(self, '_last_loaded_limit', 0):
            pass  # spinner already matches — was auto-load
        self._last_loaded_limit = current_limit

    def _on_messages_error(self, error_msg: str):
        self._log_debug(f"消息加载失败: {error_msg}")
        self.chat_view.show_placeholder(error_msg)

    def _load_cached_analysis(self):
        """Load cached analysis for active contact."""
        if not self._active_wxid:
            return
        config = load_config()
        api_client = ApiClient(
            api_url=config.get("api_url", ""),
            api_key=config.get("api_key", ""),
            model=config.get("model", "deepseek-chat"),
            temperature=config.get("temperature", 0.3),
            api_format=config.get("api_format", "openai"),
        )
        engine = AnalysisEngine(api_client)
        cached = engine.get_cached_result(self._active_wxid)
        if cached:
            self._log_debug("加载缓存分析结果")
            self.dashboard.render(cached, self._active_wxid)
        else:
            self.dashboard.show_placeholder()

    def _on_new_messages(self, wxid: str, messages: list):
        if messages is None:
            # DB file changed — reload active contact's messages
            self._log_debug(f"文件监控: 数据库变更 (wxid={wxid})，重新加载当前联系人...")
            if self._active_wxid:
                limit = self.dashboard.get_load_count()
                self._load_messages_with_limit(limit)
            return

        text_count = sum(1 for m in messages if m.is_text)
        self._log_debug(
            f"实时消息: wxid={wxid} +{len(messages)} 条 (文本 {text_count})"
        )
        if wxid == self._active_wxid:
            self.chat_view.append_messages(messages)
            self.msg_count_label.setText(
                f"消息: {self.chat_view.message_count}"
            )
        else:
            self.contact_panel.set_unread_dot(wxid, True)

    def _on_analyze(self):
        if self._active_wxid is None:
            return
        if not self._active_messages:
            text_count = 0
        else:
            text_count = sum(1 for m in self._active_messages if m.is_text)

        analysis_count = self.dashboard.get_analysis_count()

        if text_count < 5:
            QMessageBox.information(
                self, "消息不足", "消息不足(需至少5条可分析消息)"
            )
            return

        self._log_debug(
            f"开始分析: 联系人={self._wxid_to_name.get(self._active_wxid, self._active_wxid)}"
        )
        self._log_debug(
            f"  加载文本: {text_count} 条, 选取最近 {analysis_count} 条分析"
        )

        self.dashboard.set_analyzing(True)
        self.status_label.setText("分析中...")
        self.status_label.setStyleSheet("color: #FFA726")

        config = load_config()
        if not config.get("api_key") or not config.get("api_url"):
            reply = QMessageBox.question(
                self,
                "未配置 API",
                "请先配置 API Key 和 API URL",
                QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            )
            if reply == QMessageBox.StandardButton.Ok:
                self._open_settings()
            self.dashboard.set_analyzing(False)
            self.status_label.setText("就绪")
            self._log_debug("分析中止: API 未配置")
            return

        api_client = ApiClient(
            api_url=config["api_url"],
            api_key=config["api_key"],
            model=config.get("model", "deepseek-chat"),
            temperature=config.get("temperature", 0.3),
            api_format=config.get("api_format", "openai"),
        )
        engine = AnalysisEngine(api_client)

        self._log_debug(
            f"  API: {config['api_url'][:40]}..., model={config.get('model')}"
        )

        # Use dashboard spinner value for analysis count
        text_msgs = [m for m in self._active_messages if m.is_text]
        analysis_msgs = text_msgs[-analysis_count:] if analysis_count <= len(text_msgs) else text_msgs

        # Compute data range
        if analysis_msgs:
            from datetime import datetime
            dates = sorted(m.create_time for m in analysis_msgs)
            start = datetime.fromtimestamp(dates[0]).strftime("%Y-%m-%d")
            end = datetime.fromtimestamp(dates[-1]).strftime("%Y-%m-%d")
            self._analysis_data_range = (
                f"分析范围: 最近{len(analysis_msgs)}条消息 ({start} 至 {end})"
            )
            self._log_debug(
                f"  分析范围: {start} ~ {end} ({len(analysis_msgs)} 条)"
            )
        else:
            self._analysis_data_range = ""
            self._log_debug("  分析范围: 空")

        self._analysis_worker = AnalysisWorker(
            engine, analysis_msgs, self._active_wxid
        )
        self._analysis_worker.result_ready.connect(self._on_analysis_complete)
        self._analysis_worker.error_occurred.connect(self._on_analysis_error)
        self._analysis_worker.one_way_detected.connect(
            self.dashboard.show_one_way_warning
        )
        self._analysis_worker.start()
        self._log_debug("分析 worker 已启动...")

    def _on_analysis_complete(self, result: AnalysisResult):
        self._log_debug("分析完成!")
        if result.stage:
            self._log_debug(f"  对话阶段: {result.stage}")
        if result.strengths:
            self._log_debug(f"  优势 ({len(result.strengths)}): {result.strengths[:3]}...")
        if result.warnings:
            self._log_debug(f"  警告 ({len(result.warnings)}): {result.warnings}")
        if result.scores:
            parts = []
            for k, name in result.scores.dimension_names():
                parts.append(f"{name}={getattr(result.scores, k, '?')}")
            self._log_debug(f"  维度评分: {', '.join(parts)}")

        if self._active_wxid:
            self.dashboard.render(result, self._active_wxid,
                                  data_range=getattr(self, '_analysis_data_range', ""))
        self.dashboard.set_active_analysis(result)
        self.status_label.setText("分析完成")
        self.status_label.setStyleSheet("color: #43A047")
        self.dashboard.set_analyzing(False)

    def _on_analysis_error(self, error_msg: str):
        self._log_debug(f"分析失败: {error_msg}")
        self.dashboard.show_error(error_msg)
        self.status_label.setText("分析失败")
        self.status_label.setStyleSheet("color: #E53935")
        self.dashboard.set_analyzing(False)

    def _on_export(self, path: str):
        if self.dashboard._current_result is None:
            return
        if path.lower().endswith(".txt"):
            self._export_text(path)
        else:
            self._export_png(path)

    def _export_png(self, path: str):
        pixmap = self.dashboard.grab()
        pixmap.save(path)
        QMessageBox.information(self, "导出成功", f"报告已保存到: {path}")

    def _export_text(self, path: str):
        result = self.dashboard._current_result
        if result is None:
            return
        lines = ["=== ChatSense 分析报告 ===\n"]
        contact_name = self._wxid_to_name.get(
            self._active_wxid or "", self._active_wxid or "未知"
        )
        lines.append(f"联系人: {contact_name}")

        if result.stage:
            lines.append(f"对话阶段: {result.stage}")
        lines.append("")

        lines.append("--- 维度评分 ---")
        for key, name in result.scores.dimension_names():
            score = getattr(result.scores, key, 0)
            lines.append(f"  {name}: {score}")

        if result.strengths:
            lines.append("\n--- 做得好的地方 ✅ ---")
            for s in result.strengths:
                lines.append(f"  - {s}")

        if result.improvements:
            lines.append("\n--- 改进建议 ---")
            from models.analysis_result import DimensionScores
            dim_names = {k: v for k, v in DimensionScores().dimension_names()}
            for imp in result.improvements:
                dim = dim_names.get(imp.get("dimension", ""), imp.get("dimension", ""))
                detail = imp.get('analysis') or imp.get('suggestion', '')
                lines.append(f"  📌 {dim} ({imp.get('score', '?')}): {detail}")

        if result.warnings:
            lines.append("\n--- 警告 ---")
            for w in result.warnings:
                lines.append(f"  - {w}")

        if result.sample_reply:
            lines.append(f"\n--- 参考回复 ---\n{result.sample_reply}")

        with open(path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        QMessageBox.information(self, "导出成功", f"报告已保存到: {path}")

    def _open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec() == SettingsDialog.DialogCode.Accepted:
            self._config = load_config()
            if self._config.get("api_key"):
                self.api_status.setText("API 就绪")
                self.api_status.setStyleSheet("color: #43A047")
            else:
                self.api_status.setText("API 未配置")
                self.api_status.setStyleSheet("color: #FFA726")

    def _reload(self):
        self._wxid_to_path.clear()
        self._wxid_to_name.clear()
        self._active_wxid = None
        self._active_messages.clear()
        self._decrypt_key = None
        self._accounts.clear()
        self._debug_lines.clear()
        self.watcher.stop()
        self.contact_panel.load_contacts({})
        self.chat_view.show_placeholder("加载中...")
        self.dashboard.show_placeholder()
        self.dashboard.debug_text.clear()
        self._init_app()
        self._log_debug("重新加载完成")

    def _show_about(self):
        QMessageBox.about(
            self,
            "About ChatSense",
            "ChatSense v1.0\n\n微信聊天质量分析工具\n分析维度：姿态平等度、自我暴露度、需求感指数、话题健康度、互动平衡度、情感共鸣度",
        )

    def closeEvent(self, event):
        self.watcher.stop()
        if (hasattr(self.dashboard, '_chat_worker') and
            self.dashboard._chat_worker and
            self.dashboard._chat_worker.isRunning()):
            self.dashboard._chat_worker.quit()
            self.dashboard._chat_worker.wait(3000)
        super().closeEvent(event)
