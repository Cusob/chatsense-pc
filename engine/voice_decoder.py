"""VoiceDecoder: Decode WeChat 3.x voice messages from MediaMSG*.db BLOBs."""

import io
import os
import sqlite3
import tempfile
import wave
import logging

from engine.db_crypto import decrypt_db
from models.wechat_account import WeChatAccount

logger = logging.getLogger(__name__)


class VoiceDecoder:
    """Decode WeChat 3.x voice messages from MediaMSG*.db BLOBs."""

    @staticmethod
    def decode(msg_svr_id: int, accounts: list[WeChatAccount],
               key: str | None) -> str | None:
        """Return path to temp WAV file, or None on failure.

        Searches MediaMSG*.db shards under each account's Msg/Multi/
        directory for the BLOB matching *msg_svr_id* and decodes it
        from SILK to 24 kHz mono PCM WAV.

        Args:
            msg_svr_id: The WeChat msg_svr_id identifying the voice message.
            accounts: List of WeChatAccount objects to search.
            key: Hex-encoded AES-256 key for decrypting MediaMSG shards.

        Returns:
            Absolute path to a temporary WAV file, or None.
        """
        try:
            from pysilk import decode as silk_decode
        except ImportError:
            logger.debug("pysilk not installed; cannot decode voice")
            return None

        if not key or not accounts:
            return None

        for acc in accounts:
            media_dir = os.path.join(acc.msg_dir, "Multi")
            if not os.path.isdir(media_dir):
                continue
            for fname in sorted(os.listdir(media_dir)):
                if not fname.startswith("MediaMSG") or not fname.endswith(".db"):
                    continue
                shard_path = os.path.join(media_dir, fname)
                if not os.path.isfile(shard_path):
                    continue
                wav = VoiceDecoder._decode_from_shard(
                    shard_path, msg_svr_id, key, silk_decode
                )
                if wav:
                    return wav
        return None

    @staticmethod
    def _decode_from_shard(shard_path: str, msg_svr_id: int,
                          key: str, silk_decode) -> str | None:
        """Attempt to decode a voice BLOB from a single MediaMSG shard.

        Returns path to temp WAV file on success, None on failure.
        """
        try:
            decrypted = decrypt_db(shard_path, key)
        except Exception:
            return None
        if not decrypted:
            return None

        conn = None
        try:
            conn = sqlite3.connect(f"file:{decrypted}?mode=ro", uri=True)
            row = conn.execute(
                "SELECT Buf FROM Media WHERE Reserved0 = ?",
                (msg_svr_id,),
            ).fetchone()
        except sqlite3.Error:
            return None
        finally:
            if conn:
                conn.close()
            try:
                os.unlink(decrypted)
            except OSError:
                pass

        if not row or not row[0] or len(row[0]) < 10:
            return None

        buf = row[0]
        try:
            silk_io = io.BytesIO(buf)
            pcm_io = io.BytesIO()
            silk_decode(silk_io, pcm_io, 24000)
            pcm_data = pcm_io.getvalue()
        except Exception:
            return None

        if not pcm_data or len(pcm_data) < 100:
            return None

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        try:
            with wave.open(tmp, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(24000)
                wf.writeframes(pcm_data)
            return tmp.name
        except Exception:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
            return None
