import base64
import hashlib
import hmac
import json
import os
import sqlite3
import time
from datetime import datetime, timezone

import requests

from config.settings import load_config, ensure_config_dir


class TencentSTT:
    """Tencent Cloud SentenceRecognition API + SQLite transcription cache.

    Free tier: 5,000 calls/month (postpaid disabled by default).
    """

    CACHE_DB = os.path.join(os.path.expanduser("~"), ".chatsense", "stt_cache.db")

    def __init__(self, secret_id: str = "", secret_key: str = ""):
        config = load_config()
        self._secret_id = secret_id or config.get("tencent_secret_id", "")
        self._secret_key = secret_key or config.get("tencent_secret_key", "")
        self._quota_warned = False
        self._auth_warned = False
        self._ensure_cache_table()

    def _ensure_cache_table(self):
        try:
            ensure_config_dir()
            conn = sqlite3.connect(self.CACHE_DB)
            conn.execute(
                "CREATE TABLE IF NOT EXISTS stt_cache "
                "(msg_svr_id INTEGER PRIMARY KEY, transcript TEXT NOT NULL, "
                "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
            )
            conn.commit()
        except sqlite3.Error:
            pass
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def transcribe(self, audio_path: str, msg_svr_id: int) -> str | None:
        """Transcribe a voice message. Returns text on success, None on failure.

        1. Check cache 2. Cache hit -> return 3. Miss -> read file -> call API -> write cache -> return
        """
        if not self._secret_id or not self._secret_key:
            return None

        # 1. Check cache
        try:
            conn = sqlite3.connect(self.CACHE_DB)
            row = conn.execute(
                "SELECT transcript FROM stt_cache WHERE msg_svr_id = ?",
                (msg_svr_id,),
            ).fetchone()
            conn.close()
            if row:
                return row[0]
        except sqlite3.Error:
            try:
                conn.close()
            except Exception:
                pass
            try:
                os.unlink(self.CACHE_DB)
            except OSError:
                pass
            self._ensure_cache_table()

        # 2. Read audio file
        if not os.path.isfile(audio_path):
            return None
        try:
            with open(audio_path, "rb") as f:
                audio_data = f.read()
        except OSError:
            return None

        if not audio_data:
            return None

        # 3. Call API
        try:
            result_text = self._call_asr_api(audio_data, os.path.basename(audio_path))
        except Exception as e:
            error_str = str(e)
            if "AuthFailure" in error_str or "Unauthorized" in error_str:
                if not self._auth_warned:
                    self._auth_warned = True
                    self._emit_warning("ASR Key Error", "Tencent Cloud SecretId/SecretKey is invalid. Please update in Settings.")
            elif "LimitExceeded" in error_str or "quota" in error_str.lower():
                if not self._quota_warned:
                    self._quota_warned = True
                    self._emit_warning("ASR Quota Exhausted", "Monthly 5,000 free calls used up.")
            return None

        if not result_text:
            return None

        # 4. Write cache
        conn = None
        try:
            conn = sqlite3.connect(self.CACHE_DB)
            conn.execute(
                "INSERT OR REPLACE INTO stt_cache (msg_svr_id, transcript) VALUES (?, ?)",
                (msg_svr_id, result_text),
            )
            conn.commit()
        except sqlite3.Error:
            pass
        finally:
            if conn:
                conn.close()

        return result_text

    def _call_asr_api(self, audio_data: bytes, filename: str) -> str:
        """Call Tencent Cloud SentenceRecognition API, return transcribed text."""
        ext = os.path.splitext(filename)[1].lower().lstrip(".")
        voice_format_map = {"amr": "amr", "silk": "silk", "wav": "wav", "mp3": "mp3", "m4a": "m4a", "aac": "aac"}
        voice_format = voice_format_map.get(ext, "amr")

        audio_b64 = base64.b64encode(audio_data).decode("ascii")

        payload = json.dumps({
            "EngSerViceType": "16k_zh",
            "SourceType": 1,
            "VoiceFormat": voice_format,
            "Data": audio_b64,
            "DataLen": len(audio_data),
        })

        headers = self._sign_request(payload)
        resp = requests.post(
            "https://asr.tencentcloudapi.com",
            headers=headers,
            data=payload,
            timeout=30,
        )
        data = resp.json()
        if "Response" not in data:
            error = data.get("Error", {})
            raise Exception(error.get("Code", "Unknown"))
        resp_data = data["Response"]
        if "Error" in resp_data:
            raise Exception(resp_data["Error"].get("Code", "API Error"))
        return resp_data.get("Result", "").strip()

    def _sign_request(self, payload: str) -> dict[str, str]:
        """TC3-HMAC-SHA256 Signature v3."""
        service = "asr"
        host = "asr.tencentcloudapi.com"
        action = "SentenceRecognition"
        version = "2019-06-14"
        algorithm = "TC3-HMAC-SHA256"
        timestamp = int(time.time())
        date = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")

        # Step 1: CanonicalRequest
        http_method = "POST"
        canonical_uri = "/"
        canonical_querystring = ""
        ct = "application/json; charset=utf-8"
        canonical_headers = (
            f"content-type:{ct}\nhost:{host}\nx-tc-action:{action.lower()}\n"
        )
        signed_headers = "content-type;host;x-tc-action"
        hashed_payload = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        canonical_request = (
            f"{http_method}\n{canonical_uri}\n{canonical_querystring}\n"
            f"{canonical_headers}\n{signed_headers}\n{hashed_payload}"
        )

        # Step 2: StringToSign
        credential_scope = f"{date}/{service}/tc3_request"
        hashed_request = hashlib.sha256(
            canonical_request.encode("utf-8")
        ).hexdigest()
        string_to_sign = (
            f"{algorithm}\n{timestamp}\n{credential_scope}\n{hashed_request}"
        )

        # Step 3: Signature
        def _hmac(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        secret_date = _hmac(("TC3" + self._secret_key).encode("utf-8"), date)
        secret_service = _hmac(secret_date, service)
        secret_signing = _hmac(secret_service, "tc3_request")
        signature = hmac.new(
            secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        # Step 4: Authorization header
        authorization = (
            f"{algorithm} Credential={self._secret_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        return {
            "Authorization": authorization,
            "Content-Type": ct,
            "Host": host,
            "X-TC-Action": action,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": version,
        }

    def _emit_warning(self, title: str, message: str):
        """Emit warning dialog from worker thread."""
        try:
            from PyQt6.QtCore import QMetaObject, Qt as QtCore, Q_ARG
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                ok = QMetaObject.invokeMethod(
                    app,
                    "_show_warning",
                    QtCore.ConnectionType.QueuedConnection,
                    Q_ARG(str, title),
                    Q_ARG(str, message),
                )
                if not ok:
                    _show_warning_sync(title, message)
            else:
                _show_warning_sync(title, message)
        except (ImportError, AttributeError):
            _show_warning_sync(title, message)

    @staticmethod
    def test_connection(secret_id: str, secret_key: str) -> tuple[bool, str]:
        """Test connection by sending a zero-byte payload — auth-only check.

        Uses SourceType=0 (URL mode) with no URL to avoid audio data
        validation. Only verifies that the signature and credentials are valid.
        """
        payload = json.dumps({
            "EngSerViceType": "16k_zh",
            "SourceType": 0,
            "VoiceFormat": "wav",
            "Url": "",
        })

        stt = TencentSTT(secret_id=secret_id, secret_key=secret_key)
        try:
            headers = stt._sign_request(payload)
        except Exception as e:
            return False, f"签名失败: {e}"

        try:
            resp = requests.post(
                "https://asr.tencentcloudapi.com",
                headers=headers,
                data=payload,
                timeout=15,
            )
            data = resp.json()
            if "Error" in data.get("Response", {}):
                err = data["Response"]["Error"]
                code = err.get("Code", "Unknown")
                msg = err.get("Message", "")
                # Auth-related errors
                if "Auth" in code or "auth" in code.lower() or "SecretId" in code:
                    return False, f"认证失败: {code} — {msg}"
                # All other errors = auth passed, just test data issue
                return True, "连接成功 (API 响应: {})".format(code)
            return True, "连接成功"
        except requests.Timeout:
            return False, "连接超时, 请检查网络"
        except requests.ConnectionError:
            return False, "无法连接服务器, 请检查网络"
        except Exception as e:
            return False, str(e)[:200]


def _show_warning_sync(title: str, message: str):
    """Fallback synchronous warning display."""
    try:
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.warning(None, title, message)
    except Exception:
        print(f"[ASR WARNING] {title}: {message}")
