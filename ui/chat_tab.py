import sqlite3
import os
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton,
    QScrollArea, QLabel, QCheckBox, QSpinBox, QFrame, QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal
from config.settings import ensure_config_dir


CHAT_HISTORY_DB = os.path.join(os.path.expanduser("~"), ".chatsense", "chat_history.db")


class ChatBubble(QFrame):
    """Single chat bubble: blue (user, right) or gray (assistant, left)."""

    def __init__(self, text: str, is_user: bool, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        bg = "#2196F3" if is_user else "#E8E8E8"
        fg = "white" if is_user else "#222"
        align = Qt.AlignmentFlag.AlignLeft  # always left-align text inside
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setStyleSheet(
            f"QFrame {{ background: {bg}; border-radius: 10px; margin: 3px 4px; }}"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(2)

        label = QLabel(text)
        label.setWordWrap(True)
        label.setTextFormat(Qt.TextFormat.PlainText)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        label.setOpenExternalLinks(False)
        label.setStyleSheet(
            f"color: {fg}; font-size: 12px; background: transparent; "
            f"padding: 0px; border: none;"
        )

        # Use a container to control max width relative to parent
        if is_user:
            layout.setAlignment(Qt.AlignmentFlag.AlignRight)
            label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        else:
            layout.setAlignment(Qt.AlignmentFlag.AlignLeft)

        layout.addWidget(label)
        label.setMaximumWidth(400)  # upper bound; will shrink if needed


class DeepThinkBubble(QFrame):
    """Collapsible bubble for deep-think responses with reasoning, answer, and sources."""

    def __init__(self, reasoning: str, answer: str, sources: list = None, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(
            "QFrame { background: #E8E8E8; border-radius: 10px; margin: 3px 4px; }"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(4)

        # Toggle button for reasoning
        self.toggle_btn = QPushButton("展开思考过程 ▼")
        self.toggle_btn.setStyleSheet(
            "QPushButton { background: transparent; border: 1px solid #AAA; "
            "border-radius: 4px; padding: 2px 8px; font-size: 11px; color: #555; "
            "text-align: left; }"
        )
        self.toggle_btn.setCheckable(True)
        self.toggle_btn.clicked.connect(self._toggle_reasoning)
        layout.addWidget(self.toggle_btn)

        # Hidden reasoning label
        self.reason_label = QLabel(reasoning)
        self.reason_label.setWordWrap(True)
        self.reason_label.setTextFormat(Qt.TextFormat.PlainText)
        self.reason_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.reason_label.setStyleSheet(
            "color: #777; background: #F0F0F0; border-radius: 4px; "
            "padding: 6px; font-size: 10px; border: none;"
        )
        self.reason_label.setVisible(False)
        self.reason_label.setMaximumWidth(400)
        layout.addWidget(self.reason_label)

        # Answer label
        answer_label = QLabel(answer)
        answer_label.setWordWrap(True)
        answer_label.setTextFormat(Qt.TextFormat.PlainText)
        answer_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        answer_label.setStyleSheet(
            "color: #222; font-size: 12px; background: transparent; "
            "padding: 0px; border: none;"
        )
        answer_label.setMaximumWidth(400)
        layout.addWidget(answer_label)

        # Sources links
        if sources:
            links_html = "<br>".join(
                f'<a href="{s}">{s}</a>' for s in sources if s
            )
            if links_html:
                sources_label = QLabel(links_html)
                sources_label.setWordWrap(True)
                sources_label.setOpenExternalLinks(True)
                sources_label.setTextInteractionFlags(
                    Qt.TextInteractionFlag.TextBrowserInteraction
                )
                sources_label.setStyleSheet(
                    "color: #1976D2; font-size: 10px; background: transparent; "
                    "padding: 2px 0px; border: none;"
                )
                sources_label.setMaximumWidth(400)
                layout.addWidget(sources_label)

    def _toggle_reasoning(self):
        show = self.toggle_btn.isChecked()
        self.reason_label.setVisible(show)
        self.toggle_btn.setText(
            "收起思考过程 ▲" if show else "展开思考过程 ▼"
        )


class ChatTab(QWidget):
    """Dashboard tab for LLM conversation with context-aware AI chat."""

    chat_requested = pyqtSignal(str, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._wxid = ""
        self._messages = []
        self._history: list[dict] = []
        self._analysis_result = None
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # -- Context controls --
        ctrl_frame = QFrame()
        ctrl_frame.setStyleSheet(
            "QFrame { background: #F5F5F5; border-radius: 6px; padding: 4px; }"
        )
        ctrl_layout = QVBoxLayout(ctrl_frame)

        # Row 1: existing controls
        row1 = QHBoxLayout()
        self.include_msgs_cb = QCheckBox("附带聊天")
        self.include_msgs_cb.setChecked(True)
        row1.addWidget(self.include_msgs_cb)

        self.msg_count_spin = QSpinBox()
        self.msg_count_spin.setRange(1, 999)
        self.msg_count_spin.setValue(50)
        self.msg_count_spin.setSuffix("条")
        self.msg_count_spin.setStyleSheet("QSpinBox { min-width: 70px; }")
        row1.addWidget(self.msg_count_spin)

        self.include_analysis_cb = QCheckBox("附带分析")
        row1.addWidget(self.include_analysis_cb)

        row1.addWidget(QLabel("历史:"))
        self.history_spin = QSpinBox()
        self.history_spin.setRange(1, 50)
        self.history_spin.setValue(10)
        self.history_spin.setSuffix("轮")
        self.history_spin.setStyleSheet("QSpinBox { min-width: 60px; }")
        row1.addWidget(self.history_spin)

        row1.addStretch()
        ctrl_layout.addLayout(row1)

        # Row 2: thinking + search
        row2 = QHBoxLayout()
        self.deep_think_cb = QCheckBox("深度思考")
        row2.addWidget(self.deep_think_cb)
        self.web_search_cb = QCheckBox("联网搜索")
        row2.addWidget(self.web_search_cb)
        row2.addStretch()
        ctrl_layout.addLayout(row2)

        layout.addWidget(ctrl_frame)

        # -- Chat display --
        self.chat_scroll = QScrollArea()
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setStyleSheet("QScrollArea { border: none; }")

        self.chat_widget = QWidget()
        self.chat_layout = QVBoxLayout(self.chat_widget)
        self.chat_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.chat_layout.addStretch()
        self.chat_scroll.setWidget(self.chat_widget)
        layout.addWidget(self.chat_scroll)

        # -- Input area --
        self.input_text = QTextEdit()
        self.input_text.setMaximumHeight(80)
        self.input_text.setPlaceholderText("输入问题，Enter 发送...")
        self.input_text.textChanged.connect(self._on_input_changed)
        self.input_text.installEventFilter(self)
        layout.addWidget(self.input_text)

        # -- Buttons --
        btn_layout = QHBoxLayout()
        self.send_btn = QPushButton("发送")
        self.send_btn.setStyleSheet(
            "QPushButton { background: #2196F3; color: white; padding: 6px 16px; border-radius: 4px; }"
            "QPushButton:disabled { background: #BBDEFB; }"
        )
        self.send_btn.clicked.connect(self._on_send)
        self.send_btn.setEnabled(False)
        btn_layout.addWidget(self.send_btn)

        self.clear_btn = QPushButton("清空对话")
        self.clear_btn.setStyleSheet(
            "QPushButton { padding: 6px 12px; border-radius: 4px; }"
        )
        self.clear_btn.clicked.connect(self.clear_chat)
        btn_layout.addWidget(self.clear_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def eventFilter(self, obj, event):
        if obj == self.input_text and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key.Key_Return and not (
                event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            ):
                self._on_send()
                return True
        return super().eventFilter(obj, event)

    def _on_input_changed(self):
        self.send_btn.setEnabled(bool(self.input_text.toPlainText().strip()))

    def _on_send(self):
        text = self.input_text.toPlainText().strip()
        if not text:
            return
        self.input_text.clear()

        config = {
            "include_messages": self.include_msgs_cb.isChecked(),
            "msg_count": self.msg_count_spin.value(),
            "include_analysis": self.include_analysis_cb.isChecked(),
            "history_rounds": self.history_spin.value(),
            "deep_think": self.deep_think_cb.isChecked(),
            "web_search": self.web_search_cb.isChecked(),
        }

        self.add_message("user", text)
        self.chat_requested.emit(text, config)

    def set_context(self, wxid: str, messages: list, analysis_result=None):
        self._wxid = wxid
        self._messages = messages
        self._analysis_result = analysis_result
        self._history = []
        self._load_history()
        self._clear_display()
        for h in self._history:
            self._add_bubble(h["role"], h["content"])

        if not messages:
            self.include_msgs_cb.setChecked(False)
        if analysis_result is None:
            self.include_analysis_cb.setChecked(False)

    def set_analysis(self, result):
        self._analysis_result = result
        if result is None:
            self.include_analysis_cb.setChecked(False)

    def set_responding(self, is_responding: bool):
        self.send_btn.setEnabled(not is_responding)

    def add_response(self, role: str, reply: dict):
        """Route reply to correct bubble type based on content."""
        answer = reply.get("answer", "")
        reasoning = reply.get("reasoning")
        sources = reply.get("sources")
        if reasoning:
            bubble = DeepThinkBubble(reasoning, answer, sources)
        else:
            bubble = ChatBubble(answer, is_user=(role == "user"))
            if sources:
                links_html = "<br>".join(
                    f'<a href="{s}">{s}</a>' for s in sources if s
                )
                if links_html:
                    src_label = QLabel(links_html)
                    src_label.setWordWrap(True)
                    src_label.setOpenExternalLinks(True)
                    src_label.setTextInteractionFlags(
                        Qt.TextInteractionFlag.TextBrowserInteraction
                    )
                    src_label.setStyleSheet(
                        "color: #1976D2; font-size: 10px; background: transparent; "
                        "padding: 2px 10px; border: none;"
                    )
                    src_label.setMaximumWidth(400)
                    self.chat_layout.insertWidget(
                        self.chat_layout.count() - 1, bubble
                    )
                    self.chat_layout.insertWidget(
                        self.chat_layout.count() - 1, src_label
                    )
                    self._history.append({"role": role, "content": answer})
                    return
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)
        self._history.append({"role": role, "content": answer})

    def add_message(self, role: str, content: str):
        self.add_response(role, {"answer": content, "reasoning": None, "sources": None})

    def clear_chat(self):
        self._clear_display()
        self._history = []
        if self._wxid:
            try:
                ensure_config_dir()
                conn = sqlite3.connect(CHAT_HISTORY_DB)
                conn.execute(
                    "DELETE FROM chat_history WHERE contact_wxid = ?",
                    (self._wxid,),
                )
                conn.commit()
                conn.close()
            except sqlite3.Error:
                pass

    def _load_history(self):
        if not self._wxid:
            return
        try:
            ensure_config_dir()
            conn = sqlite3.connect(CHAT_HISTORY_DB)
            cur = conn.execute(
                "SELECT role, content FROM chat_history WHERE contact_wxid = ? ORDER BY id ASC",
                (self._wxid,),
            )
            self._history = [{"role": r[0], "content": r[1]} for r in cur]
            conn.close()
        except sqlite3.Error:
            self._history = []

    def _add_bubble(self, role: str, content: str):
        bubble = ChatBubble(content, is_user=(role == "user"))
        self.chat_layout.insertWidget(self.chat_layout.count() - 1, bubble)

    def _clear_display(self):
        while self.chat_layout.count() > 1:
            item = self.chat_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
