# logger/logger.py
import logging
import logging.handlers
import sys
import threading
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "config.toml"
DEFAULT_LOG_FILE = Path("logs/app.log")
DEFAULT_LOG_FORMAT = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"

# Rotation settings
MAX_LOG_BYTES = 5 * 1024 * 1024  # 5 MB per file
BACKUP_COUNT = 3                  # Keep 3 rotated backups

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
                        "format": log_cfg.get("format", DEFAULT_LOG_FORMAT),
                        "console_export": log_cfg.get("console_export", True),
                    }
                except Exception as e:
                    # Fall back to defaults but make the failure visible
                    print(
                        f"WARNING: Failed to load logging config from {CONFIG_PATH}: {e} "
                        f"— using defaults",
                        file=sys.stderr,
                    )
                    _cached_config = {
                        "level": "INFO",
                        "file": DEFAULT_LOG_FILE,
                        "format": DEFAULT_LOG_FORMAT,
                        "console_export": True,
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
            if cfg["console_export"]:
                console_handler = logging.StreamHandler()
                console_handler.setFormatter(formatter)
                logger.addHandler(console_handler)

            # File output with rotation
            log_path = cfg["file"]
            if not log_path.is_absolute():
                log_path = PROJECT_ROOT / log_path
            log_path.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_path,
                maxBytes=MAX_LOG_BYTES,
                backupCount=BACKUP_COUNT,
            )
            file_handler.setFormatter(formatter)
            logger.addHandler(file_handler)

    return logger
