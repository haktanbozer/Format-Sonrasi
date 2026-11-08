# -*- coding: utf-8 -*-
"""
Format Sonrası Kurulum Sihirbazı - Merkezi Günlükleme (Logging) Modülü
Konsol ve yerel AppData altındaki log dosyasına standart formatta çıktı üretir.
"""

import logging
import os
import sys
from typing import Optional

_LOG_FILE: Optional[str] = None
_ROOT_CONFIGURED = False


def _get_log_path() -> str:
    global _LOG_FILE
    if _LOG_FILE is not None:
        return _LOG_FILE
    try:
        base_dir = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.dirname(os.path.abspath(__file__))
        log_dir = os.path.join(base_dir, "FormatSonrasi", "logs")
        os.makedirs(log_dir, exist_ok=True)
        _LOG_FILE = os.path.join(log_dir, "format_sonrasi.log")
    except Exception:
        _LOG_FILE = "format_sonrasi.log"
    return _LOG_FILE


def configure_logging(level: int = logging.INFO):
    global _ROOT_CONFIGURED
    if _ROOT_CONFIGURED:
        return

    logger = logging.getLogger("FormatSonrasi")
    logger.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Konsol / stderr işleyicisi (sys.stderr None değilse)
    if sys.stderr is not None:
        try:
            sh = logging.StreamHandler(sys.stderr)
            sh.setFormatter(formatter)
            logger.addHandler(sh)
        except Exception:
            pass

    # Dosya işleyicisi
    try:
        log_path = _get_log_path()
        fh = logging.FileHandler(log_path, encoding="utf-8", delay=True)
        fh.setFormatter(formatter)
        logger.addHandler(fh)
    except Exception:
        pass

    _ROOT_CONFIGURED = True


def get_logger(name: str = "") -> logging.Logger:
    if not _ROOT_CONFIGURED:
        configure_logging()
    if name:
        return logging.getLogger(f"FormatSonrasi.{name}")
    return logging.getLogger("FormatSonrasi")
