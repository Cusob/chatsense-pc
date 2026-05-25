import sys

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from ui.main_window import MainWindow
from engine.db_crypto import cleanup_temp_files


def main():
    cleanup_temp_files()  # Remove leftover decrypted temp files from previous runs
    app = QApplication(sys.argv)
    app.setApplicationName("ChatSense")
    app.setOrganizationName("ChatSense")

    # Global stylesheet
    app.setStyleSheet("""
        QMainWindow {
            background: #ffffff;
        }
        QMenuBar {
            background: #f5f5f5;
            border-bottom: 1px solid #e0e0e0;
        }
        QMenuBar::item:selected {
            background: #e0e0e0;
        }
        QStatusBar {
            background: #f5f5f5;
            border-top: 1px solid #e0e0e0;
            font-size: 11px;
        }
        QSplitter::handle {
            background: #e0e0e0;
        }
        QSplitter::handle:horizontal {
            width: 2px;
        }
        QListWidget {
            border: none;
            outline: none;
            font-size: 13px;
        }
        QListWidget::item {
            padding: 8px 12px;
            border-bottom: 1px solid #f0f0f0;
        }
        QListWidget::item:selected {
            background: #E3F2FD;
            color: #333;
        }
        QListWidget::item:hover {
            background: #F5F5F5;
        }
        QLineEdit {
            padding: 6px 10px;
            border: 1px solid #e0e0e0;
            border-radius: 4px;
            font-size: 12px;
        }
        QLineEdit:focus {
            border-color: #2196F3;
        }
        QScrollArea {
            border: none;
        }
    """)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
