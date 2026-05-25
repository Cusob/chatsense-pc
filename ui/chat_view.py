from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QLabel, QPushButton, QHBoxLayout,
    QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from models.chat_message import ChatMessage


class ChatView(QWidget):
    """Center panel: conversation display with color-coded message bubbles."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._messages: list[ChatMessage] = []
        self._user_scrolled_up = False
        self._contact_name = ""
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Header with contact name
        self.header_label = QLabel("选择一个联系人")
        self.header_label.setStyleSheet(
            "font-size: 14px; font-weight: bold; padding: 8px; background: #f5f5f5; border-bottom: 1px solid #ddd;"
        )
        layout.addWidget(self.header_label)

        # Scrollable message area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("QScrollArea { border: none; }")

        self.messages_container = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.messages_layout.addStretch()
        self.scroll_area.setWidget(self.messages_container)
        layout.addWidget(self.scroll_area)

        # "New messages" button (appears when user scrolls up)
        self.new_msg_btn = QPushButton("↓ 新消息")
        self.new_msg_btn.setStyleSheet(
            "QPushButton { background: #2196F3; color: white; border-radius: 4px; padding: 4px 12px; }"
        )
        self.new_msg_btn.clicked.connect(self._scroll_to_bottom)
        self.new_msg_btn.hide()
        layout.addWidget(self.new_msg_btn)

        # Connect scrollbar change detection
        v_scrollbar = self.scroll_area.verticalScrollBar()
        v_scrollbar.valueChanged.connect(self._on_scroll_changed)

    @property
    def message_count(self) -> int:
        return len(self._messages)

    def set_contact(self, display_name: str):
        self._contact_name = display_name
        self.header_label.setText(display_name)

    def load_messages(self, messages: list[ChatMessage]):
        self._messages = messages
        self._clear_bubbles()
        for msg in messages:
            self._add_bubble(msg)
        self._scroll_to_bottom()
        self._user_scrolled_up = False

    def append_messages(self, messages: list[ChatMessage]):
        self._messages.extend(messages)
        for msg in messages:
            self._add_bubble(msg)
        if not self._user_scrolled_up:
            self._scroll_to_bottom()
        else:
            self.new_msg_btn.show()

    def _clear_bubbles(self):
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            widget = item.widget()
            if widget:
                self.messages_layout.removeWidget(widget)
                widget.setParent(None)
                widget.deleteLater()

    def _add_bubble(self, msg: ChatMessage):
        bubble = self._create_bubble(msg)
        self.messages_layout.insertWidget(
            self.messages_layout.count() - 1, bubble
        )

    def _create_bubble(self, msg: ChatMessage) -> QWidget:
        is_me = msg.is_from_me
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 2, 4, 2)

        # Sender label (outside bubble in ChatSense style)
        sender_color = "#2196F3" if is_me else "#666"
        sender_label = QLabel(msg.sender_label)
        sender_label.setStyleSheet(f"color: {sender_color}; font-size: 10px; font-weight: bold;")
        if is_me:
            sender_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(sender_label)

        display_text = msg.display_text

        bubble_label = QLabel(display_text)
        bubble_label.setWordWrap(True)
        bubble_label.setMaximumWidth(400)
        bubble_label.setStyleSheet(
            f"""
            QLabel {{
                padding: 6px 10px;
                border-radius: 8px;
                background: {'#2196F3' if is_me else '#E0E0E0'};
                color: {'white' if is_me else '#333'};
                font-size: 12px;
            }}
            """
        )
        if is_me:
            bubble_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(bubble_label)

        return container

    def show_placeholder(self, text: str):
        self._clear_bubbles()
        self.header_label.setText(self._contact_name or "ChatSense")
        label = QLabel(text)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color: #999; font-size: 14px; padding: 30px;")
        self.messages_layout.insertWidget(
            self.messages_layout.count() - 1, label
        )

    def _scroll_to_bottom(self):
        v_scrollbar = self.scroll_area.verticalScrollBar()
        v_scrollbar.setValue(v_scrollbar.maximum())
        self.new_msg_btn.hide()
        self._user_scrolled_up = False

    def _on_scroll_changed(self, value: int):
        v_scrollbar = self.scroll_area.verticalScrollBar()
        at_bottom = value >= v_scrollbar.maximum() - 10
        if not at_bottom:
            self._user_scrolled_up = True
