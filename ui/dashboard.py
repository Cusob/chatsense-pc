import json
import sqlite3
import os
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QMessageBox, QFileDialog, QDialog,
    QTextEdit, QTabWidget, QSpinBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread
from PyQt6.QtGui import QFont, QColor

from models.analysis_result import AnalysisResult, DimensionScores
from ui.widgets.bar_gauge import BarGauge
from ui.widgets.trend_chart import TrendChart
from ui.widgets.colors import score_color
from ui.chat_tab import ChatTab
from config.settings import CACHE_DB_PATH
from engine.analysis_engine import ANNOTATION_PROMPT, FEEDBACK_PROMPT, FALLBACK_PROMPT


class ChatWorker(QThread):
    """Background thread for LLM chat, no UI blocking."""
    finished = pyqtSignal(dict, str)   # (reply_dict, wxid)
    error = pyqtSignal(str)

    def __init__(self, engine, user_input, chat_wxid, contact_name,
                 messages, analysis_result, history, config):
        super().__init__()
        self._engine = engine
        self._user_input = user_input
        self._chat_wxid = chat_wxid
        self._contact_name = contact_name
        self._messages = messages
        self._analysis_result = analysis_result
        self._history = history
        self._config = config

    def run(self):
        try:
            reply_dict = self._engine.chat(
                self._user_input, self._contact_name,
                self._messages, self._analysis_result,
                self._history, self._config,
            )
            self.finished.emit(reply_dict, self._chat_wxid)
        except Exception as e:
            from engine.api_client import ApiError
            if isinstance(e, ApiError):
                msg = self._format_error(e)
            else:
                msg = str(e)[:200]
            self.error.emit(msg)

    def _format_error(self, e) -> str:
        if e.code == 0 and e.body == "timeout":
            return "请求超时，请重试"
        if e.code == 0 and e.body == "connection_error":
            return "无法连接 API 服务器"
        if e.code == 0 and e.body == "empty_choices":
            return "API 返回数据为空"
        if e.code == 401 or e.code == 403:
            return "API 密钥无效，请检查配置"
        if e.code == 429:
            return "请求过于频繁，请稍后重试"
        return f"API 错误 ({e.code}): {e.body[:200]}"


class Dashboard(QWidget):
    """Right panel: bar gauge, trend graph, advice, analyze/export buttons."""

    analyze_requested = pyqtSignal()      # User pressed Analyze
    export_requested = pyqtSignal(str)    # Export path
    load_count_changed = pyqtSignal(int)   # User changed load message count

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_result: AnalysisResult | None = None
        self._contact_wxid: str = ""
        self._data_range: str = ""
        self._chat_worker: ChatWorker | None = None
        self._total_msg_count: int = 0       # total messages for this contact
        self._loaded_msg_count: int = 0      # actually loaded (text + non-text)
        self._loaded_text_count: int = 0     # loaded text messages
        self._build_ui()
        self.show_placeholder()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; }")

        self.content_widget = QWidget()
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.content_widget)
        # ── QTabWidget: Tab1 分析 + Tab2 对话 ──
        self.tabs = QTabWidget()

        # Tab 1: 分析结果（现有的 scroll）
        self.tabs.addTab(scroll, "分析结果")

        # Tab 2: AI 对话
        self.chat_tab = ChatTab()
        self.chat_tab.chat_requested.connect(self._on_chat_requested)
        self.tabs.addTab(self.chat_tab, "AI 对话")

        layout.addWidget(self.tabs)

        # ── Message count controls ──
        count_section = QFrame()
        count_section.setStyleSheet(
            "QFrame { background: #F5F5F5; border-radius: 6px; padding: 6px; }"
        )
        count_layout = QVBoxLayout(count_section)
        count_layout.setSpacing(4)

        # Total count
        self.total_label = QLabel("")
        self.total_label.setStyleSheet("font-size: 11px; color: #666; font-weight: bold;")
        self.total_label.setWordWrap(True)
        count_layout.addWidget(self.total_label)

        # Load count row
        load_row = QHBoxLayout()
        load_row.addWidget(QLabel("加载消息数:"))
        self.load_spin = QSpinBox()
        self.load_spin.setRange(1, 999999)
        self.load_spin.setValue(200)
        self.load_spin.setSingleStep(50)
        self.load_spin.setSuffix(" 条")
        self.load_spin.setStyleSheet("QSpinBox { min-width: 100px; }")
        # We connect valueChanged after spin range is finalized
        load_row.addWidget(self.load_spin)
        load_row.addStretch()
        count_layout.addLayout(load_row)

        # Analysis count row
        analysis_row = QHBoxLayout()
        analysis_row.addWidget(QLabel("分析消息数:"))
        self.analysis_spin = QSpinBox()
        self.analysis_spin.setRange(5, 999999)
        self.analysis_spin.setValue(30)
        self.analysis_spin.setSingleStep(10)
        self.analysis_spin.setSuffix(" 条")
        self.analysis_spin.setStyleSheet("QSpinBox { min-width: 100px; }")
        self.analysis_spin.setToolTip("选择用于LLM分析的文本消息数量（最少5条）")
        analysis_row.addWidget(self.analysis_spin)
        analysis_row.addStretch()
        count_layout.addLayout(analysis_row)

        # Loaded status
        self.loaded_info_label = QLabel("")
        self.loaded_info_label.setStyleSheet("font-size: 10px; color: #999;")
        count_layout.addWidget(self.loaded_info_label)

        self.content_layout.addWidget(count_section)

        # Bar gauge chart (6 dimensions)
        self.bar_gauge = BarGauge(self)
        self.bar_gauge.setMinimumHeight(260)
        self.content_layout.addWidget(self.bar_gauge)

        # Data range label
        self.data_range_label = QLabel("")
        self.data_range_label.setStyleSheet(
            "font-size: 10px; color: #999; padding: 2px 4px;"
        )
        self.data_range_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content_layout.addWidget(self.data_range_label)


        # Trend chart
        self.trend = TrendChart(self, width=3.5, height=2, dpi=90)
        self.trend.setMinimumHeight(160)
        self.content_layout.addWidget(self.trend)

        # Warnings
        self.warnings_label = QLabel("")
        self.warnings_label.setWordWrap(True)
        self.warnings_label.setStyleSheet(
            "color: #E53935; font-size: 11px; padding: 4px;"
        )
        self.content_layout.addWidget(self.warnings_label)

        # Advice
        self.advice_label = QLabel("")
        self.advice_label.setWordWrap(True)
        self.advice_label.setStyleSheet(
            "font-size: 12px; padding: 8px; background: #E3F2FD; border-radius: 6px;"
        )
        self.content_layout.addWidget(self.advice_label)

        # Sample reply
        self.reply_label = QLabel("")
        self.reply_label.setWordWrap(True)
        self.reply_label.setStyleSheet(
            "font-size: 11px; padding: 6px; background: #F3E5F5; border-radius: 6px; margin-top: 4px;"
        )
        self.content_layout.addWidget(self.reply_label)

        # ── Debug info (collapsible) ──
        self.debug_label = QLabel("调试信息")
        self.debug_label.setStyleSheet(
            "font-size: 10px; color: #999; margin-top: 8px;"
        )
        self.debug_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.debug_label.mousePressEvent = lambda e: self._toggle_debug()
        self.content_layout.addWidget(self.debug_label)

        self.debug_text = QTextEdit()
        self.debug_text.setReadOnly(True)
        self.debug_text.setMaximumHeight(180)
        self.debug_text.setStyleSheet(
            "font-family: 'Consolas', 'Microsoft YaHei'; font-size: 10px; "
            "background: #FAFAFA; border: 1px solid #E0E0E0; border-radius: 4px;"
        )
        self.debug_text.hide()
        self.content_layout.addWidget(self.debug_text)

        self.content_layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        self.reload_btn = QPushButton("重新加载")
        self.reload_btn.setVisible(False)
        self.reload_btn.setStyleSheet(
            "QPushButton { background: #FF9800; color: white; padding: 6px 12px; border-radius: 4px; }"
        )
        self.reload_btn.clicked.connect(self._on_reload_clicked)
        btn_layout.addWidget(self.reload_btn)

        self.analyze_btn = QPushButton("开始分析")
        self.analyze_btn.setStyleSheet(
            "QPushButton { background: #2196F3; color: white; padding: 6px 16px; border-radius: 4px; }"
            "QPushButton:disabled { background: #BBDEFB; }"
        )
        self.analyze_btn.clicked.connect(self.analyze_requested.emit)
        btn_layout.addWidget(self.analyze_btn)

        self.export_btn = QPushButton("导出")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self._on_export)
        btn_layout.addWidget(self.export_btn)

        self.clear_cache_btn = QPushButton("清空缓存")
        self.clear_cache_btn.setStyleSheet(
            "QPushButton { background: #E53935; color: white; padding: 6px 12px; border-radius: 4px; }"
        )
        self.clear_cache_btn.clicked.connect(self._on_clear_cache)
        btn_layout.addWidget(self.clear_cache_btn)

        self.skill_btn = QPushButton("Skill")
        self.skill_btn.setStyleSheet(
            "QPushButton { padding: 6px 12px; border-radius: 4px; }"
        )
        self.skill_btn.clicked.connect(self._show_skill)
        btn_layout.addWidget(self.skill_btn)
        layout.addLayout(btn_layout)

        # Placeholder
        self.placeholder_label = QLabel("选择一个联系人，点击 [开始分析]")
        self.placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder_label.setStyleSheet("color: #999; font-size: 13px; padding: 30px;")
        self.placeholder_label.setWordWrap(True)

        # Connect spinner change → show reload button
        self.load_spin.valueChanged.connect(self._on_load_spin_changed)

    # ── Public API ──────────────────────────────────────────────────────

    def set_total_count(self, total: int):
        """Called when we know total message count for the active contact."""
        self._total_msg_count = total
        self.total_label.setText(f"共 {total:,} 条消息")
        # Cap load spinner to total
        self.load_spin.setMaximum(max(total, 1))
        if self.load_spin.value() > total:
            self.load_spin.setValue(total)
        # Record current load value to detect future changes
        self._last_load_value = self.load_spin.value()

    def set_loaded_info(self, total_loaded: int, text_count: int):
        """Called after messages are loaded — show loaded counts."""
        self._loaded_msg_count = total_loaded
        self._loaded_text_count = text_count
        self.loaded_info_label.setText(
            f"已加载: {total_loaded} 条 (文本 {text_count} 条)"
        )
        # Cap analysis spinner to loaded text count
        self.analysis_spin.setMaximum(max(text_count, 5))
        if self.analysis_spin.value() > text_count:
            self.analysis_spin.setValue(min(text_count, max(5, text_count)))

    def get_load_count(self) -> int:
        return self.load_spin.value()

    def get_analysis_count(self) -> int:
        return self.analysis_spin.value()

    def append_debug(self, line: str):
        """Append a timestamped line to the debug panel."""
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.debug_text.append(f"[{ts}] {line}")

    def _toggle_debug(self):
        if self.debug_text.isVisible():
            self.debug_text.hide()
            self.debug_label.setText("调试信息 ▶")
        else:
            self.debug_text.show()
            self.debug_label.setText("调试信息 ▼")

    def _on_reload_clicked(self):
        self.load_count_changed.emit(self.load_spin.value())
        self.reload_btn.setVisible(False)

    def _on_load_spin_changed(self, value: int):
        """Show reload button when user changes load count from last-loaded."""
        if hasattr(self, '_last_load_value') and value != self._last_load_value:
            self.reload_btn.setVisible(True)
            self.reload_btn.setText(f"重新加载 ({value} 条)")

    def show_placeholder(self):
        self.content_layout.insertWidget(0, self.placeholder_label)
        self.bar_gauge.hide()
        self.data_range_label.hide()
        self.trend.hide()
        self.warnings_label.hide()
        self.advice_label.hide()
        self.reply_label.hide()
        self.export_btn.setEnabled(False)

    def _hide_placeholder(self):
        self.placeholder_label.hide()
        self.bar_gauge.show()
        self.data_range_label.show()
        self.trend.show()
        self.warnings_label.show()
        self.advice_label.show()
        self.reply_label.show()
        self.export_btn.setEnabled(True)

    def render(self, result: AnalysisResult, contact_wxid: str = "",
               data_range: str = ""):
        self._current_result = result
        self._contact_wxid = contact_wxid
        self._data_range = data_range
        self._hide_placeholder()

        # Bar gauge
        self.bar_gauge.render(result.scores)

        # Data range
        if data_range:
            self.data_range_label.setText(data_range)
            self.data_range_label.show()
        else:
            self.data_range_label.hide()

        # Trend
        history = self._load_trend_history(contact_wxid)
        self.trend.render(history)

        # Strengths -> reply_label (green bg)
        if result.strengths:
            text = "\n".join(f"✅ {s}" for s in result.strengths)
            self.reply_label.setText(text)
            self.reply_label.setStyleSheet(
                "font-size: 11px; padding: 6px; background: #E8F5E9; border-radius: 6px; margin-top: 4px;"
            )
            self.reply_label.show()
        else:
            self.reply_label.hide()

        # ── Per-dimension analysis ──
        if result.improvements:
            lines = []
            dim_names = {k: v for k, v in DimensionScores().dimension_names()}
            for imp in result.improvements:
                if isinstance(imp, str):
                    lines.append(f"📌 {imp}")
                    continue
                dim_key = imp.get("dimension", "")
                dim_name = dim_names.get(dim_key, dim_key)
                score = imp.get("score", "?")
                # New format: {dimension, score, analysis}
                analysis = imp.get("analysis", "")
                if analysis:
                    lines.append(
                        f'<b>{dim_name}({score})</b>'
                        f'<br><span style="color:#555;font-size:10px">'
                        f'{analysis}</span>'
                    )
                # Old format: {dimension, score, issue, evidence, suggestion}
                else:
                    issue = imp.get("issue", imp.get("suggestion", ""))
                    lines.append(f"📌 {dim_name} ({score}): {issue}")
            self.advice_label.setTextFormat(Qt.TextFormat.RichText)
            self.advice_label.setText("<br><br>".join(lines))
            self.advice_label.setStyleSheet(
                "font-size: 11px; padding: 6px; line-height: 1.6;"
            )
            self.advice_label.show()
        else:
            self.advice_label.hide()

        # Warnings -> warnings_label (red)
        if result.warnings:
            self.warnings_label.setText("\n".join(f"⚠ {w}" for w in result.warnings))
            self.warnings_label.setStyleSheet("color: #E53935; font-size: 11px; padding: 4px;")
            self.warnings_label.show()
        else:
            self.warnings_label.hide()

        # Sample reply
        if result.sample_reply:
            self.reply_label.setText(f"💬 参考回复: {result.sample_reply}")
            self.reply_label.show()
        else:
            self.reply_label.hide()

    def clear_chart(self):
        self.bar_gauge.clear()
        self.trend.clear_chart()

    def _load_trend_history(self, contact_wxid: str) -> list[dict]:
        if not contact_wxid:
            return []
        try:
            conn = sqlite3.connect(CACHE_DB_PATH)
            cur = conn.execute(
                "SELECT timestamp, json_result FROM analyses WHERE contact_wxid = ? ORDER BY timestamp ASC LIMIT 20",
                (contact_wxid,),
            )
            history = []
            for row in cur:
                data = json.loads(row[1])
                scores = data.get("scores", {})
                if scores:
                    avg = sum(scores.values()) // len(scores)
                else:
                    avg = 50
                history.append({"timestamp": row[0], "overall": avg})
            conn.close()
            return history
        except (sqlite3.Error, json.JSONDecodeError):
            return []

    def set_analyzing(self, is_analyzing: bool):
        self.analyze_btn.setEnabled(not is_analyzing)
        self.reload_btn.setEnabled(not is_analyzing)
        self.load_spin.setEnabled(not is_analyzing)
        self.analysis_spin.setEnabled(not is_analyzing)
        self.export_btn.setEnabled(False)
        if is_analyzing:
            self.analyze_btn.setText("分析中...")
            self.analyze_btn.setStyleSheet(
                "QPushButton { background: #BBDEFB; color: #666; padding: 6px 16px; border-radius: 4px; }"
            )
        else:
            self.analyze_btn.setText("开始分析")
            self.analyze_btn.setStyleSheet(
                "QPushButton { background: #2196F3; color: white; padding: 6px 16px; border-radius: 4px; }"
                "QPushButton:disabled { background: #BBDEFB; }"
            )
        if hasattr(self, 'chat_tab') and self.chat_tab:
            self.chat_tab.set_responding(is_analyzing)

    def show_error(self, message: str):
        self._hide_placeholder()
        self.bar_gauge.clear()
        self.warnings_label.setText(message)
        self.warnings_label.show()
        self.advice_label.hide()
        self.reply_label.hide()
        self.analyze_btn.setEnabled(True)

    def show_one_way_warning(self):
        if self._current_result:
            existing = self._current_result.warnings
            if "仅检测到单向消息" not in existing:
                existing = ["仅检测到单向消息"] + existing
            self._current_result.warnings = existing
            self.warnings_label.setText(
                "\n".join(f"⚠ {w}" for w in existing)
            )
            self.warnings_label.show()

    def _show_skill(self):
        """Show the full analysis skill content + pipeline debug log."""
        dialog = QDialog(self)
        dialog.setWindowTitle("分析 Skill 内容")
        dialog.setMinimumSize(700, 550)
        layout = QVBoxLayout(dialog)

        tabs = QTabWidget()

        prompt_tab = QTextEdit()
        prompt_tab.setReadOnly(True)
        prompt_tab.setPlainText(
            "=== 标注阶段 ===\n" + ANNOTATION_PROMPT + "\n\n"
            + "=== 反馈阶段 ===\n" + FEEDBACK_PROMPT + "\n\n"
            + "=== 兜底阶段 ===\n" + FALLBACK_PROMPT
        )
        prompt_tab.setStyleSheet("font-family: 'Consolas', 'Microsoft YaHei'; font-size: 12px;")
        tabs.addTab(prompt_tab, "Prompt")

        # Pipeline Log (from AnalysisEngine internal debug)
        pipeline_tab = QTextEdit()
        pipeline_tab.setReadOnly(True)
        pipeline_debug = getattr(self._current_result, 'debug_log', '') or "（暂无调试信息，请执行一次分析后查看）"
        pipeline_tab.setPlainText(pipeline_debug)
        pipeline_tab.setStyleSheet("font-family: 'Consolas', 'Microsoft YaHei'; font-size: 11px;")
        tabs.addTab(pipeline_tab, "Pipeline Log")

        # Global debug tab (from MainWindow orchestration)
        global_tab = QTextEdit()
        global_tab.setReadOnly(True)
        global_tab.setPlainText(
            self.debug_text.toPlainText() or "（暂无全局调试信息）"
        )
        global_tab.setStyleSheet("font-family: 'Consolas', 'Microsoft YaHei'; font-size: 11px;")
        tabs.addTab(global_tab, "全局日志")

        layout.addWidget(tabs)
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(dialog.accept)
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)
        dialog.exec()

    def set_active_context(self, wxid: str, messages: list):
        """Called by MainWindow when a contact is selected."""
        if hasattr(self, 'chat_tab') and self.chat_tab:
            self.chat_tab.set_context(wxid, messages)

    def set_active_analysis(self, result):
        """Called by MainWindow when analysis completes."""
        if hasattr(self, 'chat_tab') and self.chat_tab:
            self.chat_tab.set_analysis(result)

    def _on_chat_requested(self, user_input: str, config: dict):
        wxid = self.chat_tab._wxid
        main_win = self.window()
        display_name = (main_win._wxid_to_name.get(wxid, wxid)
                       if hasattr(main_win, '_wxid_to_name') else wxid)

        self._persist_message(wxid, "user", user_input, len(self.chat_tab._messages))

        from config.settings import load_config
        from engine.api_client import ApiClient
        from engine.chat_engine import ChatEngine

        cfg = load_config()
        if not cfg.get("api_key") or not cfg.get("api_url"):
            self.chat_tab.add_message("assistant", "\u8bf7\u5148\u5728\u8bbe\u7f6e\u4e2d\u914d\u7f6e API Key")
            return

        api_client = ApiClient(
            api_url=cfg["api_url"], api_key=cfg["api_key"],
            model=cfg.get("model", "deepseek-chat"),
            temperature=cfg.get("temperature", 0.3),
            api_format=cfg.get("api_format", "openai"),
        )
        engine = ChatEngine(api_client)

        msgs = self.chat_tab._messages[-config["msg_count"]:] \
            if config.get("include_messages") and self.chat_tab._messages else []
        hist = self.chat_tab._history[-config["history_rounds"]*2:] \
            if self.chat_tab._history else []
        analysis = self.chat_tab._analysis_result \
            if config.get("include_analysis") else None

        self._chat_worker = ChatWorker(
            engine, user_input, wxid, display_name,
            msgs, analysis, hist, config,
        )
        self._chat_worker.finished.connect(self._on_chat_finished)
        self._chat_worker.error.connect(self._on_chat_error)
        self.chat_tab.set_responding(True)
        self.analyze_btn.setEnabled(False)
        self._chat_worker.start()

    def _on_chat_finished(self, reply_dict: dict, wxid: str):
        if self.chat_tab._wxid == wxid:
            self.chat_tab.add_response("assistant", reply_dict)
            self._persist_message(wxid, "assistant", reply_dict.get("answer", ""))
        self.chat_tab.set_responding(False)
        self.analyze_btn.setEnabled(True)
        if self._chat_worker:
            self._chat_worker.deleteLater()
            self._chat_worker = None

    def _on_chat_error(self, error_msg: str):
        self.chat_tab.add_message("assistant", f"\u274c {error_msg}")
        self.chat_tab.set_responding(False)
        self.analyze_btn.setEnabled(True)
        if self._chat_worker:
            self._chat_worker.deleteLater()
            self._chat_worker = None

    def _persist_message(self, wxid: str, role: str, content: str,
                        msg_count: int = 0):
        """Write a single chat message to chat_history.db."""
        import sqlite3
        from config.settings import ensure_config_dir
        CHAT_DB = os.path.join(os.path.expanduser("~"), ".chatsense", "chat_history.db")
        try:
            ensure_config_dir()
            conn = sqlite3.connect(CHAT_DB)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS chat_history ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                "contact_wxid TEXT NOT NULL,"
                "role TEXT NOT NULL,"
                "content TEXT NOT NULL,"
                "has_analysis INTEGER DEFAULT 0,"
                "message_count INTEGER,"
                "created_at TEXT DEFAULT CURRENT_TIMESTAMP"
                ")"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_wxid "
                "ON chat_history(contact_wxid)"
            )
            conn.execute(
                "INSERT INTO chat_history (contact_wxid, role, content, message_count) "
                "VALUES (?, ?, ?, ?)",
                (wxid, role, content, msg_count if role == "user" else 0),
            )
            conn.commit()
            conn.close()
        except sqlite3.Error:
            pass

    def _on_clear_cache(self):
        """Clear both analysis cache and STT cache."""
        from PyQt6.QtWidgets import QMessageBox
        cleared = []
        for db_path in [CACHE_DB_PATH, os.path.join(os.path.dirname(CACHE_DB_PATH), "stt_cache.db")]:
            if os.path.isfile(db_path):
                try:
                    os.unlink(db_path)
                    cleared.append(os.path.basename(db_path))
                except OSError:
                    pass
        if cleared:
            QMessageBox.information(self, "缓存已清空", f"已删除: {', '.join(cleared)}")
            self.show_placeholder()
        else:
            QMessageBox.information(self, "缓存已清空", "没有需要清空的缓存文件")

    def _on_export(self):
        if self._current_result is None:
            return
        default_dir = ""
        try:
            from PyQt6.QtCore import QStandardPaths
            docs = QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.DocumentsLocation
            )
            if docs:
                default_dir = docs
        except Exception:
            pass

        path, _ = QFileDialog.getSaveFileName(
            self, "导出分析报告", default_dir, "PNG (*.png);;文本文件 (*.txt)"
        )
        if not path:
            return
        self.export_requested.emit(path)
