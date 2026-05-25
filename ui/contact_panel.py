from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
    QLabel,
)
from PyQt6.QtCore import pyqtSignal, Qt
from PyQt6.QtGui import QColor


class ContactPanel(QWidget):
    """Left panel: contact list with search, red dot indicators."""

    contact_selected = pyqtSignal(str, str)  # wxid, display_name

    def __init__(self, parent=None):
        super().__init__(parent)
        self._contacts: dict[str, str] = {}  # wxid -> display_name
        self._unread: set[str] = set()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Search box
        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("搜索联系人...")
        self.search_box.textChanged.connect(self._on_search)
        layout.addWidget(self.search_box)

        # Contact list
        self.list_widget = QListWidget()
        self.list_widget.setVerticalScrollMode(
            self.list_widget.ScrollMode.ScrollPerPixel
        )
        self.list_widget.currentRowChanged.connect(self._on_contact_clicked)
        layout.addWidget(self.list_widget)

        # Empty state label
        self.empty_label = QLabel("未找到联系人")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet("color: #999; padding: 20px;")
        layout.addWidget(self.empty_label)
        self.empty_label.hide()

    def load_contacts(self, contacts: dict[str, str]):
        """Load contact list with {wxid: display_name} mapping."""
        self._contacts = contacts
        self._refresh_list()

    def _refresh_list(self, filter_text: str = ""):
        self.list_widget.clear()
        for wxid, display_name in self._contacts.items():
            if filter_text and filter_text.lower() not in display_name.lower() and filter_text.lower() not in wxid.lower():
                continue
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, wxid)
            if wxid in self._unread:
                text = f"● {display_name}"
                item.setForeground(QColor("#2196F3"))
            else:
                text = display_name
            item.setText(text)
            self.list_widget.addItem(item)

        has_items = self.list_widget.count() > 0
        self.list_widget.setVisible(has_items)
        self.empty_label.setVisible(not has_items)

    def _on_search(self, text: str):
        self._refresh_list(text)

    def _on_contact_clicked(self, row: int):
        if row < 0:
            return
        item = self.list_widget.item(row)
        if item is None:
            return
        wxid = item.data(Qt.ItemDataRole.UserRole)
        display_name = self._contacts.get(wxid, wxid)
        self.contact_selected.emit(wxid, display_name)

    def set_unread_dot(self, wxid: str, has_unread: bool):
        if has_unread:
            self._unread.add(wxid)
        else:
            self._unread.discard(wxid)
        # Refresh the current visible list
        self._refresh_list(self.search_box.text())

    def clear_unread(self, wxid: str):
        self.set_unread_dot(wxid, False)
