# logger/logger.py
import logging
import threading
import tomllib
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "config.toml"
DEFAULT_LOG_FILE = Path("logs/app.log")

# Cached config and locks
_config_lock = threading.Lock()
_cached_config = None

_logger_lock = threading.Lock()


def load_logging_config():
    global _cached_config

    if _cached_config is None:
        with _config_lock:
            if _cached_config is None:
                try:
                    with open(CONFIG_PATH, "rb") as f:
                        config = tomllib.load(f)
                    log_cfg = config.get("logging", {})
                    _cached_config = {
                        "level": log_cfg.get("level", "INFO").upper(),
                        "file": Path(log_cfg.get("file", DEFAULT_LOG_FILE)),
                        "format": log_cfg.get("format", "%(asctime)s — %(name)s — %(levelname)s — %(message)s"),
                    }
                except Exception:
                    # Fall back to defaults if config missing/broken
                    _cached_config = {
                        "level": "INFO",
                        "file": DEFAULT_LOG_FILE,
                        "format": "%(asctime)s — %(name)s — %(levelname)s — %(message)s",
                    }

    return _cached_config


def get_logger(name: str) -> logging.Logger:
    cfg = load_logging_config()
    logger = logging.getLogger(name)

    with _logger_lock:
        if not logger.hasHandlers():
            logger.setLevel(getattr(logging, cfg["level"], logging.INFO))

            formatter = logging.Formatter(cfg["format"])

            # Console output
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)

            # File output
            cfg["file"].parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.FileHandler(cfg["file"])
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

    return logger
