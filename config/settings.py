import json
import os


DEFAULT_CONFIG = {
    "api_key": "",
    "api_url": "https://api.deepseek.com/v1",  # base URL; /chat/completions and /models appended at call time
    "api_format": "openai",  # "openai" or "anthropic"
    "model": "deepseek-chat",
    "temperature": 0.3,
    "tencent_secret_id": "",
    "tencent_secret_key": "",
    "cached_wx_key": "",
}

CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".chatsense")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
CACHE_DB_PATH = os.path.join(CONFIG_DIR, "analysis_cache.db")


class ConfigCorruptError(Exception):
    """Raised when config.json is corrupted and cannot be loaded."""
    pass


def ensure_config_dir():
    os.makedirs(CONFIG_DIR, exist_ok=True)


def load_config() -> dict:
    ensure_config_dir()
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return dict(DEFAULT_CONFIG)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            raw = f.read()
        if not raw.strip():
            save_config(DEFAULT_CONFIG)
            return dict(DEFAULT_CONFIG)
        cfg = json.loads(raw)
        for key, val in DEFAULT_CONFIG.items():
            if key not in cfg:
                cfg[key] = val
        return cfg
    except json.JSONDecodeError:
        raise ConfigCorruptError("配置文件损坏，请重新配置")
    except IOError:
        return dict(DEFAULT_CONFIG)


def save_config(cfg: dict):
    ensure_config_dir()
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
