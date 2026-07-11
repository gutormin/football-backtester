import logging.config
import os

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "level": os.environ.get("LOG_LEVEL", "INFO"),
            "formatter": "standard",
            "stream": "ext://sys.stdout",
        },
        "file": {
            "class": "logging.handlers.TimedRotatingFileHandler",
            "level": "ERROR",
            "formatter": "standard",
            "filename": os.path.join(LOG_DIR, "backend.log"),
            "when": "midnight",
            "interval": 1,
            "backupCount": 30,
            "encoding": "utf-8",
        },
    },
    "loggers": {
        "uvicorn": {"level": "WARNING"},
        "fastapi": {"level": "WARNING"},
    },
    "root": {
        "handlers": ["console", "file"],
        "level": os.environ.get("LOG_LEVEL", "INFO"),
    },
}


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.config.dictConfig(LOGGING_CONFIG)
