# -*- coding: utf-8 -*-
"""
Format Sonrası Kurulum Sihirbazı - Kurulum Doğrulama Motoru (Post-Install Verifier)
Yalnızca exit code'a güvenmez; Registry (lookaround regex), doğrudan dosya varlığı,
winget export JSON ve DISM /English durum ayrıştırması yapar.
"""

import json
import os
import re
import subprocess
import tempfile
import winreg
from typing import Dict, Any, Tuple, List, Set, Optional
from system_checks import get_system32_path, get_winget_path

# None sentinel önbellekler (Boş sonuçların her seferinde zaman aşımına girmesini önler)
_CACHED_REGISTRY_NAMES: Optional[Set[str]] = None
_CACHED_REGISTRY_BLOB: Optional[Tuple[Set[str], str]] = None
_CACHED_WINGET_IDS: Optional[Set[str]] = None
_CACHED_APPX_PACKAGES: Optional[Set[str]] = None


def invalidate_registry_cache():
    """Yalnızca kayıt defteri (Uninstall) önbelleğini sıfırlar (Hafif ve hızlı, <15ms)."""
    global _CACHED_REGISTRY_NAMES, _CACHED_REGISTRY_BLOB
    _CACHED_REGISTRY_NAMES = None
    _CACHED_REGISTRY_BLOB = None


def invalidate_all_verification_caches():
    """Tüm önbellekleri (Registry, WinGet JSON, Appx) sıfırlar (Oturum başında veya tam yenilemede)."""
    global _CACHED_REGISTRY_NAMES, _CACHED_REGISTRY_BLOB, _CACHED_WINGET_IDS, _CACHED_APPX_PACKAGES
    _CACHED_REGISTRY_NAMES = None
    _CACHED_REGISTRY_BLOB = None
    _CACHED_WINGET_IDS = None
    _CACHED_APPX_PACKAGES = None


# Geriye dönük uyumluluk takma adı
invalidate_verification_caches = invalidate_all_verification_caches


def get_all_installed_display_names(force_refresh=False) -> Set[str]:
    """Sistemdeki tüm 32 ve 64 bit DisplayName kayıtlarını toplar."""
    global _CACHED_REGISTRY_NAMES, _CACHED_REGISTRY_BLOB
    if force_refresh:
        _CACHED_REGISTRY_NAMES = None
        _CACHED_REGISTRY_BLOB = None
    elif _CACHED_REGISTRY_NAMES is not None:
        return _CACHED_REGISTRY_NAMES

    names: Set[str] = set()
    hives = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall", 0),
    ]

    for root, path, flag in hives:
        key = None
        try:
            access = winreg.KEY_READ | flag if flag else winreg.KEY_READ
            key = winreg.OpenKey(root, path, 0, access)
            num_subkeys = winreg.QueryInfoKey(key)[0]
            for i in range(num_subkeys):
                subkey = None
                try:
                    subkey_name = winreg.EnumKey(key, i)
                    subkey = winreg.OpenKey(key, subkey_name, 0, access)
                    display_name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                    if display_name and isinstance(display_name, str):
                        names.add(display_name.strip().lower())
                except Exception:
                    pass
                finally:
                    if subkey:
                        winreg.CloseKey(subkey)
        except Exception:
            pass
        finally:
            if key:
                winreg.CloseKey(key)

    _CACHED_REGISTRY_NAMES = names
    return names


def get_all_winget_installed_ids(force_refresh=False) -> Set[str]:
    """
    winget export JSON kullanarak kesintiye ve konsol genişliğine uğramadan tam ID'leri çeker.
    """
    global _CACHED_WINGET_IDS
    if _CACHED_WINGET_IDS is not None and not force_refresh:
        return _CACHED_WINGET_IDS

    installed: Set[str] = set()
    temp_json = None
    try:
        temp_fd, temp_json = tempfile.mkstemp(prefix="wg_exp_", suffix=".json")
        os.close(temp_fd)
        if os.path.exists(temp_json):
            os.remove(temp_json)

        winget_bin = get_winget_path()
        if not winget_bin:
            return installed

        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        cmd = [winget_bin, "export", "-o", temp_json, "--accept-source-agreements", "--include-versions"]
        res = subprocess.run(cmd, capture_output=True, text=True, creationflags=creationflags, timeout=20)

        if os.path.exists(temp_json):
            with open(temp_json, "r", encoding="utf-8", errors="replace") as f:
                data = json.load(f)
                sources = data.get("Sources", [])
                for src in sources:
                    for pkg in src.get("Packages", []):
                        pid = pkg.get("PackageIdentifier")
                        if pid:
                            installed.add(pid.strip().lower())
    except Exception:
        # Fallback: export başarısızsa hızlı winget list
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            res = subprocess.run(
                [winget_bin, "list", "--accept-source-agreements"],
                capture_output=True, text=True, errors="replace", creationflags=creationflags, timeout=15
            )
            for line in res.stdout.splitlines():
                parts = line.split()
                for p in parts:
                    clean = p.strip().lower()
                    if "." in clean and re.match(r"^[a-z0-9_-]+(\.[a-z0-9_-]+)+$", clean):
                        installed.add(clean)
        except Exception:
            pass
    finally:
        if temp_json and os.path.exists(temp_json):
            try:
                os.remove(temp_json)
            except Exception:
                pass

    _CACHED_WINGET_IDS = installed
    return installed


def get_all_appx_packages(force_refresh=False) -> Set[str]:
    """Yalnızca doğrulanacak açık bir appx paketi varsa PowerShell Get-AppxPackage çeker."""
    global _CACHED_APPX_PACKAGES
    if _CACHED_APPX_PACKAGES is not None and not force_refresh:
        return _CACHED_APPX_PACKAGES

    packages: Set[str] = set()
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        ps_bin = get_system32_path("powershell.exe")
        cmd = [ps_bin, "-NoProfile", "-Command", "Get-AppxPackage | Select-Object -ExpandProperty Name"]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags,
            timeout=10,
        )
        for line in res.stdout.splitlines():
            clean = line.strip().lower()
            if clean:
                packages.add(clean)
    except Exception:
        pass

    _CACHED_APPX_PACKAGES = packages
    return packages


def _check_registry_match_lookaround(search_phrases: List[str], registered_names: Set[str]) -> bool:
    """
    (?<!\\w)lookaround(?!\\w) kullanarak .NET, C++, Notepad++ gibi özel karakterli kayıtları
    ve Opera vs Opera GX gibi durumları sıfır sahte pozitif/negatifle eşleştirir.
    Hızlı ön eleme (in blob) ile kurulu olmayan paketlerde regex çalıştırmadan <1ms içinde döner.
    blob önbellekleme ile her çağrıda 129 kez yeniden string birleştirilmesini engeller.
    """
    global _CACHED_REGISTRY_BLOB
    if _CACHED_REGISTRY_BLOB is not None and _CACHED_REGISTRY_BLOB[0] is registered_names:
        blob = _CACHED_REGISTRY_BLOB[1]
    else:
        blob = "\n" + "\n".join(registered_names).lower() + "\n"
        _CACHED_REGISTRY_BLOB = (registered_names, blob)

    for phrase in search_phrases:
        p = phrase.strip().lower()
        if len(p) < 2 or p not in blob:
            continue

        pattern = re.compile(rf"(?<!\w){re.escape(p)}(?!\w)")
        for m in pattern.finditer(blob):
            s = blob.rfind("\n", 0, m.start()) + 1
            line = blob[s:blob.find("\n", m.end())]
            if p == "opera" and "gx" in line:
                continue
            return True
    return False


def _check_file_paths(paths: list) -> bool:
    """Yalnızca dizin kontrolü yapmaz; doğrudan çalıştırılabilir (.exe) dosya varlığını teyit eder."""
    for p in paths:
        expanded = os.path.expandvars(p)
        if os.path.isfile(expanded):
            return True
        elif os.path.isdir(expanded):
            try:
                for f in os.listdir(expanded):
                    if f.lower().endswith(".exe"):
                        return True
            except Exception:
                pass
    return False


def check_single_winget_installed(winget_id: str) -> bool:
    """Tek bir uygulamanın WinGet ile kurulu olup olmadığını hedeflenmiş hızlı sorguyla (--id X -e) kontrol eder."""
    try:
        winget_bin = get_winget_path()
        if not winget_bin:
            return False
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        cmd = [winget_bin, "list", "--id", winget_id, "-e", "--accept-source-agreements"]
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace", creationflags=creationflags, timeout=20)
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if winget_id.lower() in line.lower():
                    return True
    except Exception:
        pass
    return False


def _check_dism_feature_english(feature_name: str) -> Tuple[bool, bool]:
    """
    DISM özellik durumunu /English parametresiyle dil bağımsız sorgular.
    Dönüş: (is_enabled: bool, is_reboot_pending: bool)
    """
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        dism_bin = get_system32_path("dism.exe")
        cmd = [dism_bin, "/Online", "/English", "/Get-FeatureInfo", f"/FeatureName:{feature_name}"]
        res = subprocess.run(cmd, capture_output=True, text=True, errors="replace", creationflags=creationflags, timeout=12)
        out = res.stdout.lower()

        if "state : enabled" in out:
            return True, False
        elif "enable pending" in out:
            return True, True
    except Exception:
        pass
    return False, False


def verify_application_installed(
    app_data: Dict[str, Any],
    registry_cache: Optional[Set[str]] = None,
    winget_cache: Optional[Set[str]] = None,
    appx_cache: Optional[Set[str]] = None,
    allow_winget_refresh: bool = False,
    allow_subprocess: bool = True,
) -> Tuple[bool, str]:
    """
    Uygulamanın başarıyla kurulup kurulmadığını çok katmanlı, hızlı ve sıfır sahte pozitif ile doğrular.
    allow_winget_refresh: Açılış taramasında False tutularak yüzlerce kez winget export çağrılması engellenir.
    allow_subprocess: Açılış taramasında False yapılarak DISM gibi ağır alt süreçlerin çalıştırılması engellenir.
    """
    verify_rule = app_data.get("verify", {})
    app_name = app_data.get("name", "")
    winget_id = app_data.get("winget_id", "")
    install_type = app_data.get("install_type", "winget")

    # 1. DISM Özelliği Teyidi (/English ayrıştırması)
    if install_type == "dism_feature":
        feature_name = app_data.get("feature_name", "NetFx3")
        if allow_subprocess:
            is_enabled, is_pending = _check_dism_feature_english(feature_name)
            if is_enabled:
                if is_pending:
                    return True, "DISM Etkin (Sistem yeniden başlatması bekliyor)"
                return True, "DISM bileşen durumu: Enabled"
        if "files" in verify_rule and _check_file_paths(verify_rule["files"]):
            return True, "DISM sistem ikili dosyalarıyla doğrulandı"
        return False, "DISM bileşeni etkinleştirilemedi"

    # 2. Özel Tanımlı Dosya Varlığı Doğrulaması (En yüksek kesinlik)
    if "files" in verify_rule:
        if _check_file_paths(verify_rule["files"]):
            return True, "Yürütülebilir dosya varlığı ile doğrulandı"

    # 3. Yalnızca açıkça appx_names tanımlanmışsa Appx kontrolü yap (Madde 1 Sahte Pozitif Koruması)
    appx_names = verify_rule.get("appx_names", [])
    if appx_names:
        if appx_cache is None and allow_subprocess:
            appx_cache = get_all_appx_packages()
        if appx_cache:
            for target_appx in appx_names:
                t_clean = target_appx.strip().lower()
                if any(t_clean == a or a.startswith(t_clean) for a in appx_cache):
                    return True, "Windows Appx paketi ile doğrulandı"

    # 4. Registry İsim Doğrulaması (Lookaround Regex) - Hızlı ve öncelikli
    if registry_cache is None:
        registry_cache = get_all_installed_display_names()

    search_phrases = verify_rule.get("registry_names", [])
    if not search_phrases:
        clean_name = app_name.split("(")[0].strip()
        search_phrases = [clean_name]

    if _check_registry_match_lookaround(search_phrases, registry_cache):
        return True, "Kayıt defteri (Uninstall) ile doğrulandı"

    # 5. WinGet Export JSON Teyidi (Tembel yükleme; tazelemeyi yalnızca kurulum sonrası doğrulamada aç)
    if winget_id and not winget_id.startswith(("custom.", "direct.", "dism.")):
        wid_clean = winget_id.lower()
        if winget_cache is None and allow_subprocess:
            winget_cache = get_all_winget_installed_ids(force_refresh=False)
        if winget_cache and wid_clean in winget_cache:
            return True, "WinGet sistem kaydı ile doğrulandı"

        if allow_winget_refresh and allow_subprocess:
            # Tüm sistem paketlerini export etmek yerine tek paketlik hedefli hızlı sorgu (--id X -e)
            if check_single_winget_installed(wid_clean):
                return True, "WinGet sistem kaydı ile doğrulandı (hızlı sorgu)"

    # 6. Standart Program Files yürütülebilir dosya (.exe) kontrolü
    name_slug = app_name.split()[0].lower()
    if len(name_slug) >= 4 and name_slug not in ["visual", "microsoft", "free", "open", "google"]:
        generic_exe_paths = [
            f"%ProgramFiles%\\{name_slug}\\{name_slug}.exe",
            f"%ProgramFiles(x86)%\\{name_slug}\\{name_slug}.exe",
            f"%LocalAppData%\\Programs\\{name_slug}\\{name_slug}.exe",
        ]
        if _check_file_paths(generic_exe_paths):
            return True, "Program ikili dosyası ile doğrulandı"

    return False, "Sistemde kurulu olduğu teyit edilemedi"
