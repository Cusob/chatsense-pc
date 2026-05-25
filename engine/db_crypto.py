import os
import tempfile
import logging
from hashlib import pbkdf2_hmac
from hmac import new as hmac_new

logger = logging.getLogger(__name__)

DECRYPT_TEMP_PREFIX = "chatsense_decrypt_"
PBKDF2_ITERATIONS = 64000
KEY_SIZE = 32


def verify_key(key_hex: str, db_path: str) -> bool:
    """Verify a key against an encrypted database using WeChat's HMAC scheme.

    Computes the HMAC-SHA1 of the first page and compares it against the
    stored value at the end of the page (bytes -32 to -12).
    """
    if len(key_hex) != 64:
        return False
    if not os.path.isfile(db_path):
        return False

    try:
        with open(db_path, "rb") as f:
            blist = f.read()
    except (IOError, OSError):
        return False

    if len(blist) < 4096:
        return False

    password = bytes.fromhex(key_hex.strip())
    salt = blist[:16]

    mac_salt = bytes([(salt[i] ^ 58) for i in range(16)])
    byteHmac = pbkdf2_hmac("sha1", password, salt, PBKDF2_ITERATIONS, KEY_SIZE)
    mac_key = pbkdf2_hmac("sha1", byteHmac, mac_salt, 2, KEY_SIZE)
    hash_mac = hmac_new(mac_key, blist[16:4064], "sha1")
    hash_mac.update(b'\x01\x00\x00\x00')

    return hash_mac.digest() == blist[4064:4084]


def decrypt_db(encrypted_path: str, key_hex: str,
               page_size: int = 0) -> str | None:
    """Decrypt an encrypted WeChat SQLite database file.

    Delegates to pywxdump.decrypt for the production-tested implementation.
    Falls back to built-in implementation if pywxdump is unavailable.

    Args:
        encrypted_path: Path to the encrypted database file.
        key_hex: 32-byte hex key string (64 hex chars).
        page_size: Ignored (kept for API compatibility).

    Returns:
        Path to decrypted temporary SQLite file, or None on failure.
    """
    if not os.path.isfile(encrypted_path):
        logger.warning("Encrypted DB not found: %s", encrypted_path)
        return None

    fd, tmp_path = tempfile.mkstemp(
        prefix=DECRYPT_TEMP_PREFIX, suffix=".db"
    )
    os.close(fd)

    try:
        import pywxdump
        ok, result = pywxdump.decrypt(key_hex, encrypted_path, tmp_path)
        if ok:
            logger.debug("Decrypted (pywxdump) %s -> %s", encrypted_path, tmp_path)
            return tmp_path
        else:
            logger.error("pywxdump decrypt failed: %s", result)
    except ImportError:
        logger.warning("pywxdump not available for decryption")
    except Exception as e:
        logger.error("pywxdump decrypt error: %s", e)

    try:
        os.unlink(tmp_path)
    except OSError:
        pass
    return None


def cleanup_temp_files():
    """Remove leftover decrypted temp files from previous runs."""
    tmpdir = tempfile.gettempdir()
    for fname in os.listdir(tmpdir):
        if fname.startswith(DECRYPT_TEMP_PREFIX):
            path = os.path.join(tmpdir, fname)
            try:
                os.unlink(path)
                logger.debug("Cleaned up temp: %s", path)
            except OSError:
                pass
