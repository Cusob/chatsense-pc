from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QDoubleSpinBox,
    QPushButton, QHBoxLayout, QLabel, QMessageBox, QComboBox, QTabWidget,
    QWidget,
)
from PyQt6.QtCore import Qt
import json
import requests
import webbrowser

from config.settings import load_config, save_config


class SettingsDialog(QDialog):
    """API and ASR configuration dialog."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.setMinimumWidth(500)
        self._build_ui()
        self._load_config()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        tabs = QTabWidget()

        # ── Tab 1: API 设置 ──
        api_tab = QWidget()
        api_layout = QVBoxLayout(api_tab)
        form = QFormLayout()
        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("sk-...")
        form.addRow("API Key:", self.api_key_edit)

        self.api_url_edit = QLineEdit()
        self.api_url_edit.setPlaceholderText("https://api.deepseek.com/v1")
        self.api_url_edit.textChanged.connect(lambda: self._fetch_models_btn.setEnabled(True))
        form.addRow("API URL:", self.api_url_edit)

        self.api_format_combo = QComboBox()
        self.api_format_combo.addItems(["OpenAI", "Anthropic"])
        self.api_format_combo.currentTextChanged.connect(self._on_format_changed)
        form.addRow("格式:", self.api_format_combo)

        model_layout = QHBoxLayout()
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setMinimumWidth(200)
        self.model_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        model_layout.addWidget(self.model_combo)

        self._fetch_models_btn = QPushButton("获取模型")
        self._fetch_models_btn.setFixedWidth(80)
        self._fetch_models_btn.clicked.connect(self._fetch_models)
        model_layout.addWidget(self._fetch_models_btn)
        form.addRow("Model:", model_layout)

        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 2.0)
        self.temp_spin.setSingleStep(0.1)
        self.temp_spin.setDecimals(2)
        self.temp_spin.setValue(0.3)
        form.addRow("Temperature:", self.temp_spin)

        api_layout.addLayout(form)

        test_layout = QHBoxLayout()
        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self._test_connection)
        self.test_label = QLabel("")
        test_layout.addWidget(self.test_btn)
        test_layout.addWidget(self.test_label)
        test_layout.addStretch()
        api_layout.addLayout(test_layout)

        tabs.addTab(api_tab, "API 设置")

        # ── Tab 2: 语音识别 ──
        asr_tab = QWidget()
        asr_layout = QVBoxLayout(asr_tab)
        asr_form = QFormLayout()

        self.asr_secret_id_edit = QLineEdit()
        self.asr_secret_id_edit.setPlaceholderText("AKIDxxxxxxxx")
        asr_form.addRow("SecretId:", self.asr_secret_id_edit)

        self.asr_secret_key_edit = QLineEdit()
        self.asr_secret_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.asr_secret_key_edit.setPlaceholderText("xxxxxxxx")
        asr_form.addRow("SecretKey:", self.asr_secret_key_edit)

        asr_layout.addLayout(asr_form)

        get_key_btn = QPushButton("获取密钥")
        get_key_btn.setToolTip("打开浏览器到腾讯云 API 密钥管理页面")
        get_key_btn.clicked.connect(
            lambda: webbrowser.open("https://console.cloud.tencent.com/cam/capi")
        )
        get_key_layout = QHBoxLayout()
        get_key_layout.addWidget(get_key_btn)
        get_key_layout.addWidget(QLabel("登录后点击'新建密钥'，粘贴到上方"))
        get_key_layout.addStretch()
        asr_layout.addLayout(get_key_layout)

        asr_test_layout = QHBoxLayout()
        self.asr_test_btn = QPushButton("测试连接")
        self.asr_test_btn.clicked.connect(self._test_asr_connection)
        self.asr_test_label = QLabel("")
        asr_test_layout.addWidget(self.asr_test_btn)
        asr_test_layout.addWidget(self.asr_test_label)
        asr_test_layout.addStretch()
        asr_layout.addLayout(asr_test_layout)

        asr_layout.addStretch()
        tabs.addTab(asr_tab, "语音识别")

        layout.addWidget(tabs)

        # OK / Cancel
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        save_btn = QPushButton("保存")
        save_btn.clicked.connect(self._save)
        save_btn.setDefault(True)
        btn_layout.addWidget(save_btn)
        layout.addLayout(btn_layout)

    def _load_config(self):
        cfg = load_config()
        self.api_key_edit.setText(cfg.get("api_key", ""))
        self.api_url_edit.setText(cfg.get("api_url", ""))
        fmt = cfg.get("api_format", "openai")
        self.api_format_combo.setCurrentText("Anthropic" if fmt == "anthropic" else "OpenAI")
        model = cfg.get("model", "")
        if model:
            self.model_combo.setCurrentText(model)
        self.temp_spin.setValue(cfg.get("temperature", 0.3))
        self.asr_secret_id_edit.setText(cfg.get("tencent_secret_id", ""))
        self.asr_secret_key_edit.setText(cfg.get("tencent_secret_key", ""))
        self._on_format_changed()

    def _on_format_changed(self):
        fmt = "anthropic" if self.api_format_combo.currentText() == "Anthropic" else "openai"
        self._fetch_models_btn.setVisible(fmt == "openai")
        if fmt == "openai":
            self.api_url_edit.setPlaceholderText("https://api.deepseek.com/v1")
        else:
            self.api_url_edit.setPlaceholderText("https://api.anthropic.com/v1")

    def _fetch_models(self):
        url = self.api_url_edit.text().strip()
        key = self.api_key_edit.text().strip()
        if not url or not key:
            return

        models_url = url.rstrip("/") + "/models"

        self._fetch_models_btn.setEnabled(False)
        self._fetch_models_btn.setText("获取中...")
        current_text = self.model_combo.currentText()

        try:
            resp = requests.get(
                models_url,
                headers={"Authorization": f"Bearer {key}"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                model_ids = sorted(
                    m["id"] for m in data.get("data", [])
                    if not m.get("id", "").startswith(("ft:", "text-"))
                )
                if model_ids:
                    self.model_combo.clear()
                    self.model_combo.addItems(model_ids)
                    if current_text in model_ids:
                        self.model_combo.setCurrentText(current_text)
                    self.test_label.setText(f"获取到 {len(model_ids)} 个模型")
                    self.test_label.setStyleSheet("color: #43A047")
                else:
                    self.test_label.setText("未找到可用模型")
                    self.test_label.setStyleSheet("color: #FFA726")
            else:
                self.test_label.setText(f"获取模型失败 ({resp.status_code})")
                self.test_label.setStyleSheet("color: #E53935")
        except Exception as e:
            self.test_label.setText(f"获取失败: {e}")
            self.test_label.setStyleSheet("color: #E53935")
        finally:
            self._fetch_models_btn.setEnabled(True)
            self._fetch_models_btn.setText("获取模型")

    def _test_connection(self):
        url = self.api_url_edit.text().strip()
        key = self.api_key_edit.text().strip()
        model = self.model_combo.currentText().strip() or "deepseek-chat"
        fmt = "anthropic" if self.api_format_combo.currentText() == "Anthropic" else "openai"

        if not url or not key:
            self.test_label.setText("请填写 API URL 和 Key")
            self.test_label.setStyleSheet("color: #E53935")
            return

        self.test_label.setText("测试中...")
        self.test_label.setStyleSheet("color: #FFA726")
        self.test_btn.setEnabled(False)

        try:
            if fmt == "anthropic":
                headers = {
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                }
                chat_url = url.rstrip("/") + "/messages"
                payload = {
                    "model": model,
                    "max_tokens": 5,
                    "messages": [{"role": "user", "content": "Hi"}],
                }
            else:
                headers = {
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                }
                chat_url = url.rstrip("/") + "/chat/completions"
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": "Hi"}],
                    "max_tokens": 5,
                }

            resp = requests.post(
                chat_url, headers=headers, json=payload, timeout=15,
            )
            if resp.status_code == 200:
                self.test_label.setText("连接成功")
                self.test_label.setStyleSheet("color: #43A047")
            else:
                self.test_label.setText(f"错误: {resp.status_code}")
                self.test_label.setStyleSheet("color: #E53935")
        except requests.Timeout:
            self.test_label.setText("连接超时")
            self.test_label.setStyleSheet("color: #E53935")
        except requests.ConnectionError:
            self.test_label.setText("无法连接")
            self.test_label.setStyleSheet("color: #E53935")
        except Exception as e:
            self.test_label.setText(f"错误: {e}")
            self.test_label.setStyleSheet("color: #E53935")
        finally:
            self.test_btn.setEnabled(True)

    def _test_asr_connection(self):
        secret_id = self.asr_secret_id_edit.text().strip()
        secret_key = self.asr_secret_key_edit.text().strip()
        if not secret_id or not secret_key:
            self.asr_test_label.setText("请填写 SecretId 和 SecretKey")
            self.asr_test_label.setStyleSheet("color: #E53935")
            return

        self.asr_test_label.setText("测试中...")
        self.asr_test_label.setStyleSheet("color: #FFA726")
        self.asr_test_btn.setEnabled(False)

        from engine.tencent_stt import TencentSTT
        ok, msg = TencentSTT.test_connection(secret_id, secret_key)

        if ok:
            self.asr_test_label.setText("连接成功")
            self.asr_test_label.setStyleSheet("color: #43A047")
        else:
            self.asr_test_label.setText(msg)
            self.asr_test_label.setStyleSheet("color: #E53935")
        self.asr_test_btn.setEnabled(True)

    def _save(self):
        cfg = load_config()
        cfg["api_key"] = self.api_key_edit.text().strip()
        cfg["api_url"] = self.api_url_edit.text().strip()
        cfg["api_format"] = "anthropic" if self.api_format_combo.currentText() == "Anthropic" else "openai"
        cfg["model"] = self.model_combo.currentText().strip()
        cfg["temperature"] = self.temp_spin.value()
        cfg["tencent_secret_id"] = self.asr_secret_id_edit.text().strip()
        cfg["tencent_secret_key"] = self.asr_secret_key_edit.text().strip()
        save_config(cfg)
        self.accept()
