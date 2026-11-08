# -*- coding: utf-8 -*-
"""
Format Sonrası Kurulum Sihirbazı - Uygulama Veritabanı ve Katalog Yükleyici
Veriler data/catalog.json dosyasından dinamik olarak yüklenir.
"""

import json
import os
import sys
from typing import Any, Dict, List, Optional
from app_logger import get_logger

logger = get_logger("apps_data")


def _find_catalog_file() -> str:
    """Katalog JSON dosyasının yolunu arar (PyInstaller paket desteği ile)."""
    candidates = []
    # 1. PyInstaller _MEIPASS dizini
    if hasattr(sys, "_MEIPASS"):
        candidates.append(os.path.join(sys._MEIPASS, "data", "catalog.json"))
        candidates.append(os.path.join(sys._MEIPASS, "catalog.json"))

    # 2. Betik klasörüne göre
    base_dir = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(base_dir, "data", "catalog.json"))
    candidates.append(os.path.join(base_dir, "catalog.json"))

    # 3. Çalışma dizini
    candidates.append(os.path.abspath(os.path.join("data", "catalog.json")))

    for path in candidates:
        if os.path.isfile(path):
            return path

    return os.path.join(base_dir, "data", "catalog.json")


def load_catalog_data() -> Dict[str, Any]:
    """Katalog JSON dosyasını okur ve doğrular."""
    cat_path = _find_catalog_file()
    if not os.path.isfile(cat_path):
        logger.error(f"Katalog dosyası bulunamadı: {cat_path}")
        return {
            "categories": [],
            "applications": [],
            "conflict_groups": {},
            "profiles": [],
        }

    try:
        with open(cat_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return {
                "categories": data.get("categories", []),
                "applications": data.get("applications", []),
                "conflict_groups": data.get("conflict_groups", {}),
                "profiles": data.get("profiles", []),
            }
    except Exception as e:
        logger.error(f"Katalog dosyası okunamadı ({cat_path}): {e}")
        return {
            "categories": [],
            "applications": [],
            "conflict_groups": {},
            "profiles": [],
        }


_CATALOG_DATA = load_catalog_data()

CATEGORIES: List[Dict[str, Any]] = _CATALOG_DATA["categories"]
APPLICATIONS: List[Dict[str, Any]] = _CATALOG_DATA["applications"]
CONFLICT_GROUPS: Dict[str, str] = _CATALOG_DATA["conflict_groups"]
PROFILES: List[Dict[str, Any]] = _CATALOG_DATA["profiles"]


def get_application(app_id: str) -> Optional[Dict[str, Any]]:
    """Belirtilen ID'ye sahip uygulama tanımını döner."""
    for app in APPLICATIONS:
        if app.get("id") == app_id:
            return app
    return None


def get_applications_by_category(category_id: str) -> List[Dict[str, Any]]:
    """Belirli bir kategoriye ait uygulamaları listeler."""
    return [app for app in APPLICATIONS if app.get("category") == category_id]
