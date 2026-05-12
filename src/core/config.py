"""
配置管理模块：保存和加载用户配置（BDUSS、下载目录等）
"""
import json
import os

APP_DIR = os.path.join(os.path.expanduser("~"), ".pdm")
LEGACY_APP_DIR = os.path.join(os.path.expanduser("~"), ".bduss_downloader")
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
LEGACY_CONFIG_PATH = os.path.join(LEGACY_APP_DIR, "config.json")

DEFAULT_CONFIG = {
    "bduss": "",
    "bduss_bfess": "",
    "full_cookie": "",
    "download_dir": os.path.join(os.path.expanduser("~"), "Downloads"),
    "max_concurrent_tasks": 2,
    "task_connections": 16,
    "speed_limit": 0,          # 0 = 不限速，单位 KB/s
}


def _clamp_int(value, minimum: int, maximum: int, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, number))


def load_config() -> dict:
    """加载配置"""
    config_path = CONFIG_PATH
    if not os.path.exists(config_path) and os.path.exists(LEGACY_CONFIG_PATH):
        config_path = LEGACY_CONFIG_PATH
    if not os.path.exists(config_path):
        return DEFAULT_CONFIG.copy()
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 合并默认值（新增字段向后兼容）
        cfg = DEFAULT_CONFIG.copy()
        cfg.update(data)
        if "max_concurrent_tasks" not in data:
            legacy_concurrent = data.get("max_concurrent")
            if isinstance(legacy_concurrent, int) and legacy_concurrent > 0:
                cfg["max_concurrent_tasks"] = legacy_concurrent
        if "task_connections" not in data:
            legacy_connections = data.get("connections_per_file")
            legacy_concurrent = data.get("max_concurrent")
            if isinstance(legacy_connections, int) and legacy_connections > 0:
                cfg["task_connections"] = legacy_connections
            elif isinstance(legacy_concurrent, int) and legacy_concurrent > 0:
                cfg["task_connections"] = legacy_concurrent
        cfg.pop("connections_per_file", None)
        cfg.pop("max_concurrent", None)
        for key in (
            "chunk_size",
            "auto_start",
            "open_api_app_key",
            "open_api_secret_key",
            "open_api_access_token",
            "open_api_refresh_token",
        ):
            cfg.pop(key, None)
        cfg["max_concurrent_tasks"] = _clamp_int(
            cfg.get("max_concurrent_tasks"), 1, 8, DEFAULT_CONFIG["max_concurrent_tasks"]
        )
        cfg["task_connections"] = _clamp_int(
            cfg.get("task_connections"), 1, 16, DEFAULT_CONFIG["task_connections"]
        )
        return cfg
    except Exception:
        return DEFAULT_CONFIG.copy()


def save_config(config: dict) -> None:
    """保存配置"""
    config["max_concurrent_tasks"] = _clamp_int(
        config.get("max_concurrent_tasks"), 1, 8, DEFAULT_CONFIG["max_concurrent_tasks"]
    )
    config["task_connections"] = _clamp_int(
        config.get("task_connections"), 1, 16, DEFAULT_CONFIG["task_connections"]
    )
    for key in (
        "chunk_size",
        "auto_start",
        "open_api_app_key",
        "open_api_secret_key",
        "open_api_access_token",
        "open_api_refresh_token",
    ):
        config.pop(key, None)
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
