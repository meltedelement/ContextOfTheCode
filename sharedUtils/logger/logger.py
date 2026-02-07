# logger/logger.py
import logging
import logging.config
import os
from pathlib import Path
import toml

# Load config from config.toml
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.toml"
DEFAULT_LOG_FILE = Path("logs/app.log")

def load_logging_config():
    try:
        config = toml.load(CONFIG_PATH)
        log_cfg = config.get("logging", {})
        return {
            "level": log_cfg.get("level", "INFO").upper(),
            "file": Path(log_cfg.get("file", DEFAULT_LOG_FILE)),
            "format": log_cfg.get("format", "%(asctime)s — %(name)s — %(levelname)s — %(message)s"),
        }
    except Exception:
        # Fall back to default if config missing/broken
        return {
            "level": "INFO",
            "file": DEFAULT_LOG_FILE,
            "format": "%(asctime)s — %(name)s — %(levelname)s — %(message)s",
        }

def get_logger(name: str) -> logging.Logger:
    cfg = load_logging_config()
    logger = logging.getLogger(name)

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