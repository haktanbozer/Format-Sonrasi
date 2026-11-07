# -*- coding: utf-8 -*-
"""
Format Sonrası Kurulum Sihirbazı - Üretici Destek Sayfası ve Sürücü Eşleme Tablosu
Doğrulanmış resmi destek portalları, Dell Service Tag denetimi ve güvenli URL doğrulayıcısı içerir.
"""

import re
import urllib.parse
from typing import Dict, Any, Optional, Tuple

PLACEHOLDER_MFGS = {
    "system manufacturer",
    "system product name",
    "to be filled by o.e.m.",
    "to be filled by oem",
    "default string",
    "unknown",
    "bilinmiyor",
    "none",
    "null",
    "0",
    "chassis manufacturer",
    "baseboard manufacturer",
}

PLACEHOLDER_MODELS = {
    "system product name",
    "system manufacturer",
    "to be filled by o.e.m.",
    "to be filled by oem",
    "default string",
    "unknown",
    "bilinmiyor",
    "none",
    "null",
    "0",
    "baseboard product",
    "type2 - board",
}

MANUFACTURER_ENTRIES = [
    {
        "id": "dell",
        "name": "Dell",
        "mfg_patterns": ["dell", "alienware"],
        "model_patterns": ["alienware", "latitude", "optiplex", "xps", "vostro", "inspiron", "precision"],
        "verified": True,
        "last_checked": "2026-11-01",
        "portal_url": "https://www.dell.com/support/home/tr-tr",
        "direct_template": "https://www.dell.com/support/home/tr-tr/product-support/servicetag/{tag}/overview",
        "tag_regex": r"^[A-Z0-9]{5,7}$",
        "note": "Dell Servis Etiketi (Service Tag) ile doğrudan ürün destek sayfasına yönlendirir.",
    },
    {
        "id": "lenovo",
        "name": "Lenovo",
        "mfg_patterns": ["lenovo"],
        "model_patterns": ["thinkpad", "ideapad", "legion", "thinkcentre", "thinkstation", "yoga", "loq"],
        "verified": True,
        "last_checked": "2026-11-01",
        "portal_url": "https://pcsupport.lenovo.com/tr/tr",
        "direct_template": None,
        "tag_regex": None,
        "note": "Lenovo Destek Portalı. Seri numarası panoya kopyalanır, sitedeki arama kutusuna yapıştırılabilir.",
    },
    {
        "id": "hp",
        "name": "HP",
        "mfg_patterns": ["hp", "hewlett-packard", "hewlett packard"],
        "model_patterns": ["omen", "victus", "elitebook", "probook", "pavilion", "spectre", "envy", "zbook"],
        "verified": True,
        "last_checked": "2026-11-01",
        "portal_url": "https://support.hp.com/tr-tr/drivers",
        "direct_template": None,
        "tag_regex": None,
        "note": "HP Resmi Sürücü Portalı. Ürün modeli veya seri numarası panoya kopyalanır.",
    },
    {
        "id": "asus",
        "name": "Asus",
        "mfg_patterns": ["asus", "asustek"],
        "model_patterns": ["rog", "tuf", "zenbook", "vivobook", "proart", "expertbook"],
        "verified": True,
        "last_checked": "2026-11-01",
        "portal_url": "https://www.asus.com/tr/support/download-center/",
        "direct_template": None,
        "tag_regex": None,
        "note": "Asus İndirme Merkezi. Model adı panoya kopyalanır.",
    },
    {
        "id": "msi",
        "name": "MSI",
        "mfg_patterns": ["msi", "micro-star"],
        "model_patterns": ["stealth", "raider", "katana", "cyborg", "bravo", "modern", "prestige"],
        "verified": True,
        "last_checked": "2026-11-01",
        "portal_url": "https://www.msi.com/support/download/",
        "direct_template": None,
        "tag_regex": None,
        "note": "MSI İndirme Merkezi. Model adı panoya kopyalanır.",
    },
    {
        "id": "acer",
        "name": "Acer",
        "mfg_patterns": ["acer"],
        "model_patterns": ["predator", "nitro", "aspire", "swift", "travelmate"],
        "verified": True,
        "last_checked": "2026-11-01",
        "portal_url": "https://www.acer.com/tr-tr/support",
        "direct_template": None,
        "tag_regex": None,
        "note": "Acer Resmi Destek Sayfası. Seri numarası veya SNID panoya kopyalanır.",
    },
    {
        "id": "monster",
        "name": "Monster Notebook",
        "mfg_patterns": ["monster", "monster notebook"],
        "model_patterns": ["abra", "tulpar", "huma", "semruk", "aryond"],
        "verified": False,
        "last_checked": "2026-11-01",
        "portal_url": "https://www.monsternotebook.com.tr/suruculer/",
        "direct_template": None,
        "tag_regex": None,
        "note": "Monster Notebook Resmi Sürücü Portalı. Cihaz modeli panoya kopyalanır.",
    },
    {
        "id": "casper",
        "name": "Casper / Excalibur",
        "mfg_patterns": ["casper", "casper bilgisayar"],
        "model_patterns": ["excalibur", "nirvana"],
        "verified": True,
        "last_checked": "2026-11-01",
        "portal_url": "https://www.casper.com.tr/destek-ve-suruculer",
        "direct_template": None,
        "tag_regex": None,
        "note": "Casper ve Excalibur Destek ve Sürücüler Portalı.",
    },
    {
        "id": "gigabyte",
        "name": "Gigabyte",
        "mfg_patterns": ["gigabyte"],
        "model_patterns": ["aorus", "aero"],
        "verified": True,
        "last_checked": "2026-11-01",
        "portal_url": "https://www.gigabyte.com/Support",
        "direct_template": None,
        "tag_regex": None,
        "note": "Gigabyte Destek Sayfası. Anakart veya dizüstü modeli panoya kopyalanır.",
    },
    {
        "id": "apple",
        "name": "Apple",
        "mfg_patterns": ["apple"],
        "model_patterns": ["macbook", "imac", "mac mini", "mac studio", "mac pro"],
        "verified": True,
        "last_checked": "2026-11-01",
        "portal_url": "https://support.apple.com/tr-tr",
        "direct_template": None,
        "tag_regex": None,
        "note": "Apple Destek Portalı (Windows BootCamp Sürücüleri).",
    },
    {
        "id": "surface",
        "name": "Microsoft Surface",
        "mfg_patterns": ["microsoft corporation", "microsoft"],
        "model_patterns": ["surface", "surface pro", "surface laptop", "surface book", "surface go", "surface studio"],
        "require_model_pattern": True,
        "verified": False,
        "last_checked": "2026-11-02",
        "portal_url": "https://support.microsoft.com/tr-tr/surface",
        "direct_template": None,
        "tag_regex": None,
        "note": "Microsoft Surface Resmi Destek ve Sürücü Sayfası.",
    },
    {
        "id": "samsung",
        "name": "Samsung",
        "mfg_patterns": ["samsung", "samsung electronics"],
        "model_patterns": ["galaxy book", "odyssey", "ativ"],
        "verified": False,
        "last_checked": "2026-11-02",
        "portal_url": "https://www.samsung.com/tr/support/",
        "direct_template": None,
        "tag_regex": None,
        "note": "Samsung Destek ve İndirme Portalı.",
    },
    {
        "id": "huawei",
        "name": "Huawei",
        "mfg_patterns": ["huawei"],
        "model_patterns": ["matebook"],
        "verified": False,
        "last_checked": "2026-11-02",
        "portal_url": "https://consumer.huawei.com/tr/support/",
        "direct_template": None,
        "tag_regex": None,
        "note": "Huawei Tüketici Destek Portalı (PC Manager / Sürücüler).",
    },
    {
        "id": "lg",
        "name": "LG Electronics",
        "mfg_patterns": ["lg electronics", "lg"],
        "model_patterns": ["gram", "ultrapc"],
        "verified": False,
        "last_checked": "2026-11-02",
        "portal_url": "https://www.lg.com/tr/destek",
        "direct_template": None,
        "tag_regex": None,
        "note": "LG Destek ve Yazılım/Sürücü İndirme Portalı.",
    },
]

# Geriye dönük uyumluluk: her girdiye birleşik patterns alanı ekle
for _e in MANUFACTURER_ENTRIES:
    _e["patterns"] = _e["mfg_patterns"] + _e["model_patterns"]


def _build_allowed_domains() -> set:
    """MANUFACTURER_ENTRIES tablosundaki tüm portal ve şablon URL'lerinden alan adlarını dinamik türetir."""
    domains = {"google.com", "www.google.com"}
    for entry in MANUFACTURER_ENTRIES:
        for key in ("portal_url", "direct_template"):
            url_str = entry.get(key)
            if url_str:
                p = urllib.parse.urlparse(url_str)
                if p.hostname:
                    domains.add(p.hostname.lower())
    return domains


ALLOWED_DOMAINS = _build_allowed_domains()


def _has_word(pattern: str, text: str) -> bool:
    """
    Belirli bir kalıbın (örneğin 'hp', 'msi', 'rog') metin içinde bağımsız bir kelime
    olarak geçip geçmediğini kelime sınırlarıyla denetler (örn. 'Insyde' içindeki 'hp' eşleşmez).
    """
    if not pattern or not text:
        return False
    pat = pattern.strip().lower()
    txt = text.strip().lower()
    # Kelime sınırı regex'i
    pattern_esc = re.escape(pat)
    return bool(re.search(r"(?:^|[\s\-_.,/\\()\[\]])" + pattern_esc + r"(?:$|[\s\-_.,/\\()\[\]])", txt))


def is_url_safe(url: str) -> bool:
    """
    Yalnızca izin verilen alan adlarındaki HTTPS URL'lerini güvenli kabul eder.
    Ters eğik çizgi, @ işareti veya boşluk içeren bozuk URL'leri doğrudan reddeder.
    """
    if not url or not isinstance(url, str):
        return False
    # Ters eğik çizgi, @ (kullanıcı kimliği taklidi) veya boşluk engelleme
    if any(ch in url for ch in ("\\", "@", " ", "\t", "\r", "\n")):
        return False
    try:
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme.lower() != "https":
            return False
        hostname = parsed.hostname
        if not hostname:
            return False
        hostname = hostname.lower()
        return any(hostname == allowed or hostname.endswith("." + allowed) for allowed in ALLOWED_DOMAINS)
    except Exception:
        return False


def resolve_support_info(
    manufacturer: str,
    model: str,
    serial_number: str = "",
    is_vm: bool = False,
) -> Dict[str, Any]:
    """
    Sistem üreticisi, model ve seri numarasına göre en uygun resmi destek sayfasını ve pano metnini belirler.
    Sanal makinelerde destek sayfası üretmez.
    Üretici ve model bilgisi tamamen okunamadığında harici bağlantı açmaz.
    Tanınmayan markalarda güvenli Google sürücü arama bağlantısına düşer.
    """
    if is_vm:
        return {
            "brand": "Sanal Makine",
            "url": None,
            "can_open": False,
            "clipboard_text": "",
            "status_message": "Sanal makine ortamında donanım sürücüsü aranmaz.",
            "is_verified": False,
            "is_fallback": False,
            "note": "Sanal makinelerde konuk eklentileri (Guest Additions / VMware Tools) hipervizör menüsünden kurulur.",
        }

    raw_mfg = (manufacturer or "").strip()
    raw_model = (model or "").strip()
    serial_clean = (serial_number or "").strip()

    # Yer tutucu / anlamsız üretici ve model değerlerini temizle
    clean_mfg = "" if raw_mfg.lower() in PLACEHOLDER_MFGS else raw_mfg
    clean_model = "" if raw_model.lower() in PLACEHOLDER_MODELS else raw_model

    # Hem üretici hem model bilgisi yoksa veya yer tutucuysa bağlantı sunma
    if not clean_mfg and not clean_model:
        return {
            "brand": "Bilinmiyor",
            "url": None,
            "can_open": False,
            "clipboard_text": "",
            "status_message": "Model bilgisi okunamadı.",
            "is_verified": False,
            "is_fallback": False,
            "note": "Sistem üretici ve model bilgisi BIOS/anakart üzerinden okunamadı.",
        }

    matched_entry = None

    # 1. Aşama: Üretici adı üzerinden eşleme (Kelime sınırı kontrolü ile)
    if clean_mfg:
        for entry in MANUFACTURER_ENTRIES:
            if entry.get("require_model_pattern"):
                # Bu üretici (örn. Microsoft Surface) yalnızca model kalıbı eşleştiğinde geçerlidir
                if not any(_has_word(p, clean_model) for p in entry["model_patterns"]):
                    continue
            for p in entry["mfg_patterns"]:
                if _has_word(p, clean_mfg):
                    matched_entry = entry
                    break
            if matched_entry:
                break

    # 2. Aşama: Üretici adından bulunamadıysa model ailesi üzerinden eşleme
    if not matched_entry and clean_model:
        for entry in MANUFACTURER_ENTRIES:
            # Önce model aile kalıplarını (ThinkPad, ROG, Victus vb.) dene
            for p in entry["model_patterns"]:
                if _has_word(p, clean_model):
                    matched_entry = entry
                    break
            if matched_entry:
                break
            # Eğer model adı içinde üretici adı geçiyorsa (örn. "HP Pavilion 15")
            for p in entry["mfg_patterns"]:
                if _has_word(p, clean_model):
                    matched_entry = entry
                    break
            if matched_entry:
                break

    if matched_entry:
        brand_name = matched_entry["name"]
        verified = matched_entry["verified"]
        note = matched_entry["note"]

        # Dell Service Tag özel denetimi
        if matched_entry["id"] == "dell" and serial_clean:
            tag_regex = matched_entry.get("tag_regex")
            if tag_regex and re.match(tag_regex, serial_clean.upper()):
                safe_tag = urllib.parse.quote(serial_clean.upper())
                target_url = matched_entry["direct_template"].format(tag=safe_tag)
                is_safe = is_url_safe(target_url)
                return {
                    "brand": brand_name,
                    "url": target_url if is_safe else None,
                    "can_open": is_safe,
                    "clipboard_text": serial_clean.upper(),
                    "status_message": "Dell Servis Etiketi panoya kopyalandı. (Not: Windows Pano Geçmişi açıksa seri numarası panoda kalabilir.)",
                    "is_verified": verified and is_safe,
                    "is_fallback": False,
                    "note": note,
                }

        # Standart marka portalları
        portal_url = matched_entry["portal_url"]
        is_safe = is_url_safe(portal_url)
        # Panoya kopyalanacak metin: Varsa seri numarası, yoksa tam model adı
        if serial_clean and not serial_clean.startswith("Okunamadı"):
            clip_val = serial_clean
            status_msg = f"{brand_name} seri numarası panoya kopyalandı. (Not: Windows Pano Geçmişi açıksa seri numarası panoda kalabilir.)"
        else:
            clip_val = clean_model if clean_model else (clean_mfg or brand_name)
            status_msg = f"{brand_name} model bilgisi panoya kopyalandı."

        return {
            "brand": brand_name,
            "url": portal_url if is_safe else None,
            "can_open": is_safe,
            "clipboard_text": clip_val,
            "status_message": status_msg,
            "is_verified": verified and is_safe,
            "is_fallback": False,
            "note": note,
        }

    # Tanınmayan Marka veya Özel Toplama Masaüstü -> Güvenli Google Arama Yedeği
    brand_display = clean_mfg if clean_mfg else (clean_model if clean_model else "Özel Yapım / Masaüstü")
    search_query = f"{clean_mfg} {clean_model} driver surucu".strip()
    safe_query = urllib.parse.quote_plus(search_query)
    fallback_url = f"https://www.google.com/search?q={safe_query}"
    clip_val = clean_model if clean_model else clean_mfg
    is_safe = is_url_safe(fallback_url)

    return {
        "brand": brand_display,
        "url": fallback_url if is_safe else None,
        "can_open": is_safe,
        "clipboard_text": clip_val,
        "status_message": "Model bilgisi panoya kopyalandı ve arama sayfası açılıyor.",
        "is_verified": False,
        "is_fallback": True,
        "note": "Üretici resmi portalı otomatik tespit edilemedi; Google sürücü araması açılır.",
    }
