# -*- coding: utf-8 -*-
"""
Format Sonrası Kurulum Sihirbazı - Windows İnce Ayarları ve Gerçek Geri Alma (Rollback) Motoru
Kayıt Defteri (Registry) ayarlarını uygulamadan önce orijinal değerlerini tweaks_backup.json dosyasına yedekler.
Geri alma (Revert) işlemi yalnızca uygulanan ayarları ve tam olarak önceki durumlarını (veya yokluklarını) geri yükler.
Güç planı, UAC, telemetri, Windows Gezgini ve sistem servisleri için güvenli yapılandırma içerir.
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import winreg
from typing import Any, Dict, List, Tuple, Optional
import shutil
from system_checks import ensure_secure_dir, is_admin, get_system32_path
from app_logger import get_logger

logger = get_logger('tweaks')


def _get_backup_file() -> str:
    """Yedek dosyasının hedef yolunu döner (dizin oluşturma ilk yazmaya ertelenir)."""
    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    return os.path.join(program_data, "FormatSonrasi", "tweaks_backup.json")


BACKUP_FILE = _get_backup_file()

TWEAKS = [
    {
        "id": "classic_context_menu",
        "name": "Windows 11 Klasik Sağ Tık Menüsü",
        "desc": "Windows 11 sınırlı menüsü yerine Windows 10 klasik tam menüsünü aktif eder.",
        "default": True,
        "scope_support": True,
    },
    {
        "id": "show_file_extensions",
        "name": "Dosya Uzantılarını Göster",
        "desc": "Güvenlik için .exe, .zip, .pdf gibi tüm dosya uzantılarını görünür yapar.",
        "default": True,
        "scope_support": True,
    },
    {
        "id": "show_hidden_files",
        "name": "Gizli Dosya ve Klasörleri Göster",
        "desc": "Windows Gezgini'nde gizli dosyaların görünmesini sağlar.",
        "default": False,
        "scope_support": True,
    },
    {
        "id": "show_this_pc_desktop",
        "name": "Masaüstüne Bu Bilgisayar Simgesi Ekle",
        "desc": "Masaüstüne klasik Bu Bilgisayar simgesini yerleştirir.",
        "default": True,
        "scope_support": True,
    },
    {
        "id": "disable_telemetry",
        "name": "Windows Telemetri ve Tanılama Verilerini Azalt",
        "desc": "Microsoft'a gönderilen tanılama verilerini en alt seviyeye çeker (AllowTelemetry=0 değeri Enterprise ve Education sürümlerinde tam kapatma sağlar; Home ve Pro sürümlerinde ise Windows bunu en düşük seviye olan Temel (1) olarak uygular).",
        "default": True,
        "scope_support": False,  # Sistem genelidir (HKLM)
    },
    {
        "id": "disable_bing_search",
        "name": "Başlat Menüsü Web (Bing) Aramasını Kapat",
        "desc": "Başlat menüsünde arama yaparken internette arama yapıp yavaşlamasını engeller.",
        "default": True,
        "scope_support": True,
    },
    {
        "id": "disable_widgets",
        "name": "Görev Çubuğu Widget ve Haberleri Gizle",
        "desc": "Windows 11 görev çubuğunda beliren haber ve widget ikonunu gizler.",
        "default": True,
        "scope_support": True,
    },
    {
        "id": "disable_fast_startup",
        "name": "Hızlı Başlatmayı Kapat (Fast Startup)",
        "desc": "Dual-boot sistemler ve SSD sağlığı için kernel hafızasını şişiren hızlı başlatmayı kapatır.",
        "default": True,
        "scope_support": False,  # Sistem genelidir (HKLM)
    },
    {
        "id": "unlock_cpu_boost",
        "name": "İşlemci Güç ve Turbo Boost Menüsünü Görünür Yap",
        "desc": "Denetim Masası Güç Seçenekleri'nde gizli olan İşlemci Performansını Artırma modunu açığa çıkarır.",
        "default": True,
        "scope_support": False,  # Sistem genelidir (HKLM)
    },
    {
        "id": "ultimate_performance",
        "name": "Nihai Performans Güç Planını Etkinleştir",
        "desc": "Gizli Windows Nihai Performans modunu aktif eder (Masaüstü/iş istasyonları için önerilir).",
        "default": False,  # Dizüstü pil tüketimi için varsayılan False
        "scope_support": False,
    },
    {
        "id": "install_wsl2",
        "name": "WSL2 ve Ubuntu Linux Kurulumu",
        "desc": "Windows Subsystem for Linux (WSL2) sanallaştırma mimarisini ve Ubuntu'yu sisteme kurar.",
        "default": False,
        "scope_support": False,
    },
    {
        "id": "virtual_machine_platform",
        "name": "Sanal Makine Platformu (DISM)",
        "desc": "WSL2, Docker ve Android emülatörleri için gerekli Sanal Makine Platformunu etkinleştirir.",
        "default": False,
        "scope_support": False,
    },
    {
        "id": "enable_long_paths",
        "name": "Uzun Dosya Yolu Desteğini Etkinleştir (MAX_PATH 260+)",
        "desc": "260 karakterlik sınırını kaldırır (manifestinde destekleyen Python, Node.js ve modern derleme araçları için geçerlidir; Gezgin doğrudan etkilenmeyebilir).",
        "default": True,
        "scope_support": False,  # Sistem genelidir (HKLM)
    },
    {
        "id": "show_seconds_taskbar",
        "name": "Görev Çubuğu Saatinde Saniyeleri Göster",
        "desc": "Windows 11 ve 10 görev çubuğu saatinde saniyeleri görünür yapar (Ayarın anında görünmesi için Gezgin'in yeniden başlatılması gerekir).",
        "default": True,
        "scope_support": True,  # Kullanıcı bazlıdır (HKCU)
    },
]


def _load_backup() -> Dict[str, Any]:
    """tweaks_backup.json dosyasından kayıtlı önceki ayarları okur.
    Bozuk JSON görüldüğünde üzerine yazıp orijinal değerleri ezmemek için
    dosyayı .corrupt uzantısıyla kenara alır.
    """
    if not os.path.exists(BACKUP_FILE):
        return {}
    try:
        with open(BACKUP_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"tweaks_backup.json bozuk veya okunamadı: {e}. Dosya .corrupt olarak yedekleniyor.")
        try:
            corrupt_dest = BACKUP_FILE + ".corrupt"
            timestamp_dest = BACKUP_FILE + f".corrupt_{int(time.time())}"
            shutil.copy2(BACKUP_FILE, timestamp_dest)
            if os.path.exists(corrupt_dest):
                try:
                    os.remove(corrupt_dest)
                except Exception:
                    pass
            os.replace(BACKUP_FILE, corrupt_dest)
        except Exception as copy_err:
            logger.error(f"Bozuk yedek dosyası taşınamadı: {copy_err}")
        return {}


def _save_backup(data: Dict[str, Any]):
    """Önceki ayarları tweaks_backup.json dosyasına atomik şekilde kaydeder."""
    target_dir = os.path.dirname(BACKUP_FILE)
    try:
        if is_admin():
            ensure_secure_dir(target_dir)
        else:
            os.makedirs(target_dir, exist_ok=True)
    except Exception as e:
        sys.stderr.write(f"[UYARI] Güvenli dizin hazırlanamadı: {e}\n")

    temp_path = BACKUP_FILE + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(temp_path, BACKUP_FILE)
    except Exception as e:
        sys.stderr.write(f"[UYARI] İnce ayar yedeği kaydedilemedi: {e}\n")


def _backup_registry_value(tweak_id: str, root_name: str, key_path: str, value_name: str):
    """
    Değer değiştirilmeden önce mevcut orijinal durumu tweaks_backup.json içine kaydeder.
    Eğer değer daha önce yedeklenmişse üzerine yazmaz (orijinal fabrika/kullanıcı halini korur).
    """
    backup = _load_backup()
    if tweak_id not in backup:
        backup[tweak_id] = {}

    entry_key = f"{root_name}\\{key_path}\\{value_name}"
    if entry_key in backup[tweak_id]:
        return  # İlk orijinal hal zaten saklı

    root = winreg.HKEY_LOCAL_MACHINE if root_name == "HKLM" else winreg.HKEY_CURRENT_USER
    existed = False
    val_data = None
    val_type = None

    try:
        with winreg.OpenKey(root, key_path, 0, winreg.KEY_READ) as k:
            val_data, val_type = winreg.QueryValueEx(k, value_name)
            existed = True
    except FileNotFoundError:
        existed = False
    except Exception:
        existed = False

    backup[tweak_id][entry_key] = {
        "root": root_name,
        "key_path": key_path,
        "value_name": value_name,
        "existed": existed,
        "data": val_data,
        "type": val_type,
    }
    _save_backup(backup)


def _safe_write_reg(root, root_name: str, key_path: str, value_name: str, value_type: int, value_data: Any, tweak_id: str) -> bool:
    """Değeri yedekler, yazar ve geri okuma doğrulaması (read-back verification) yapar."""
    _backup_registry_value(tweak_id, root_name, key_path, value_name)
    try:
        with winreg.CreateKey(root, key_path) as k:
            winreg.SetValueEx(k, value_name, 0, value_type, value_data)
        # Geri okuma doğrulaması
        with winreg.OpenKey(root, key_path, 0, winreg.KEY_READ) as k:
            read_data, _ = winreg.QueryValueEx(k, value_name)
            return read_data == value_data
    except Exception as e:
        sys.stderr.write(f"[HATA] Kayıt defteri yazma başarısız ({root_name}\\{key_path}): {e}\n")
        return False


def _safe_delete_reg_value(root, key_path: str, value_name: str):
    """Değeri siler, anahtar veya değer zaten yoksa hata vermez."""
    try:
        with winreg.OpenKey(root, key_path, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, value_name)
    except FileNotFoundError:
        pass
    except Exception as e:
        sys.stderr.write(f"[UYARI] Değer silinemedi ({key_path}\\{value_name}): {e}\n")


def apply_classic_context_menu(enable=True, scope="all") -> Tuple[bool, str]:
    tweak_id = "classic_context_menu"
    key_path = r"Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}\InprocServer32"
    parent_path = r"Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}"

    if enable:
        _backup_registry_value(tweak_id, "HKCU", key_path, "")
        try:
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as k:
                winreg.SetValueEx(k, "", 0, winreg.REG_SZ, "")
            return True, "Klasik sağ tık menüsü aktif edildi."
        except Exception as e:
            return False, f"Hata: {e}"
    else:
        # Geri alma
        backup = _load_backup().get(tweak_id, {})
        entry_key = f"HKCU\\{key_path}\\"
        backup_info = backup.get(entry_key)
        if backup_info and backup_info.get("existed"):
            # Ayar uygulanmadan önce kullanıcıda bu anahtar zaten mevcuttu; silme, önceki veriyi geri yükle
            try:
                old_val = backup_info.get("data")
                old_type = backup_info.get("type", winreg.REG_SZ)
                if old_val is not None:
                    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as k:
                        winreg.SetValueEx(k, "", 0, old_type, old_val)
                return True, "Önceki sağ tık menüsü kaydı korundu ve geri yüklendi."
            except Exception as e:
                return False, f"Hata: {e}"
        else:
            # Önceden yoktu; oluşturulan anahtarları temizle
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
            except FileNotFoundError:
                pass
            except Exception:
                pass
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, parent_path)
            except FileNotFoundError:
                pass
            except Exception:
                pass
            return True, "Varsayılan sağ tık menüsüne dönüldü."


def apply_show_file_extensions(enable=True, scope="all") -> Tuple[bool, str]:
    tweak_id = "show_file_extensions"
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
    val = 0 if enable else 1
    ok = _safe_write_reg(winreg.HKEY_CURRENT_USER, "HKCU", key_path, "HideFileExt", winreg.REG_DWORD, val, tweak_id)
    if ok:
        return True, "Dosya uzantıları görünür yapıldı." if enable else "Dosya uzantıları gizlendi."
    return False, "Kayıt defteri doğrulanamadı."


def apply_show_hidden_files(enable=True, scope="all") -> Tuple[bool, str]:
    tweak_id = "show_hidden_files"
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
    val = 1 if enable else 2
    ok = _safe_write_reg(winreg.HKEY_CURRENT_USER, "HKCU", key_path, "Hidden", winreg.REG_DWORD, val, tweak_id)
    if ok:
        return True, "Gizli dosyalar görünür yapıldı." if enable else "Gizli dosyalar gizlendi."
    return False, "Kayıt defteri doğrulanamadı."


def apply_show_this_pc_desktop(enable=True, scope="all") -> Tuple[bool, str]:
    tweak_id = "show_this_pc_desktop"
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\HideDesktopIcons\NewStartPanel"
    clsid = "{20D04FE0-3AEA-1069-A2D8-08002B30309D}"
    val = 0 if enable else 1
    ok = _safe_write_reg(winreg.HKEY_CURRENT_USER, "HKCU", key_path, clsid, winreg.REG_DWORD, val, tweak_id)
    if ok:
        return True, "Masaüstüne Bu Bilgisayar simgesi eklendi." if enable else "Bu Bilgisayar simgesi kaldırıldı."
    return False, "Kayıt defteri doğrulanamadı."



def _revert_single_tweak(tweak_id: str, scope="all") -> Tuple[bool, str]:
    """Tek bir ayarı tweaks_backup.json içindeki orijinal değerine geri döndürür."""
    backup = _load_backup()
    if not backup or tweak_id not in backup:
        return False, "Yedekte bu ayara ait kayıtlı bir durum bulunamadı."

    entries = backup[tweak_id]
    try:
        for entry_key, info in entries.items():
            root_name = info["root"]
            key_path = info["key_path"]
            value_name = info["value_name"]
            existed = info["existed"]
            val_data = info["data"]
            val_type = info["type"]

            if not _location_allowed(tweak_id, root_name, key_path, value_name):
                return False, f"Geri alma konumu izinli listede değil: {key_path}\\{value_name}"

            root = winreg.HKEY_LOCAL_MACHINE if root_name == "HKLM" else winreg.HKEY_CURRENT_USER

            if existed and val_data is not None and val_type is not None:
                if not _entry_allowed(tweak_id, root_name, key_path, value_name, val_type, val_data):
                    return False, f"Geri alma verisi geçersiz: {key_path}\\{value_name}"
                with winreg.CreateKeyEx(root, key_path, 0, winreg.KEY_SET_VALUE) as k:
                    winreg.SetValueEx(k, value_name, 0, val_type, val_data)
            else:
                _safe_delete_reg_value(root, key_path, value_name)

        backup.pop(tweak_id, None)
        if not backup:
            if os.path.exists(BACKUP_FILE):
                try:
                    os.remove(BACKUP_FILE)
                except Exception:
                    pass
        else:
            _save_backup(backup)

        return True, "Önceki orijinal durumuna geri döndürüldü."
    except Exception as e:
        return False, f"Geri alma hatası: {e}"


def apply_disable_telemetry(enable=True, scope="all") -> Tuple[bool, str]:
    tweak_id = "disable_telemetry"
    key_path = r"SOFTWARE\Policies\Microsoft\Windows\DataCollection"
    if enable:
        ok = _safe_write_reg(winreg.HKEY_LOCAL_MACHINE, "HKLM", key_path, "AllowTelemetry", winreg.REG_DWORD, 0, tweak_id)
        if ok:
            return True, "Telemetri veri toplama izin verilen en alt seviyeye ayarlandı (Enterprise/Edu: Kapalı, Pro/Home: Temel seviye)."
        return False, "Telemetri kaydı yazılamadı (Yönetici izni gereklidir)."
    else:
        # Tekil kapatma çağrısında öncelikle orijinal yedeği geri yükle
        reverted, msg = _revert_single_tweak(tweak_id, scope=scope)
        if reverted:
            return True, f"Telemetri {msg.lower()}"
        _safe_delete_reg_value(winreg.HKEY_LOCAL_MACHINE, key_path, "AllowTelemetry")
        return True, "Telemetri politikası temizlendi (Windows varsayılanına dönüldü)."


def apply_disable_bing_search(enable=True, scope="all") -> Tuple[bool, str]:
    tweak_id = "disable_bing_search"
    p1 = r"Software\Policies\Microsoft\Windows\Explorer"
    p2 = r"Software\Microsoft\Windows\CurrentVersion\Search"
    if enable:
        ok1 = _safe_write_reg(winreg.HKEY_CURRENT_USER, "HKCU", p1, "DisableSearchBoxSuggestions", winreg.REG_DWORD, 1, tweak_id)
        ok2 = _safe_write_reg(winreg.HKEY_CURRENT_USER, "HKCU", p2, "BingSearchEnabled", winreg.REG_DWORD, 0, tweak_id)
        ok3 = _safe_write_reg(winreg.HKEY_CURRENT_USER, "HKCU", p2, "CortanaConsent", winreg.REG_DWORD, 0, tweak_id)
        if ok1 and ok2 and ok3:
            return True, "Başlat menüsü web aramaları kapatıldı."
        return False, "Web aramaları kapatılırken bazı anahtarlar doğrulanamadı."
    else:
        # Tekil kapatma çağrısında öncelikle orijinal yedeği geri yükle
        reverted, msg = _revert_single_tweak(tweak_id, scope=scope)
        if reverted:
            return True, f"Web aramaları {msg.lower()}"
        _safe_delete_reg_value(winreg.HKEY_CURRENT_USER, p1, "DisableSearchBoxSuggestions")
        _safe_write_reg(winreg.HKEY_CURRENT_USER, "HKCU", p2, "BingSearchEnabled", winreg.REG_DWORD, 1, tweak_id)
        _safe_write_reg(winreg.HKEY_CURRENT_USER, "HKCU", p2, "CortanaConsent", winreg.REG_DWORD, 1, tweak_id)
        return True, "Başlat menüsü web aramaları açıldı."


def apply_disable_widgets(enable=True, scope="all") -> Tuple[bool, str]:
    tweak_id = "disable_widgets"
    key_path = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"
    val = 0 if enable else 1
    ok = _safe_write_reg(winreg.HKEY_CURRENT_USER, "HKCU", key_path, "TaskbarDa", winreg.REG_DWORD, val, tweak_id)
    if ok:
        return True, "Görev çubuğu widget'ı gizlendi." if enable else "Widget'lar görünür yapıldı."
    return False, "Kayıt defteri doğrulanamadı."


def apply_disable_fast_startup(enable=True, scope="all") -> Tuple[bool, str]:
    tweak_id = "disable_fast_startup"
    key_path = r"SYSTEM\CurrentControlSet\Control\Session Manager\Power"
    val = 0 if enable else 1
    ok = _safe_write_reg(winreg.HKEY_LOCAL_MACHINE, "HKLM", key_path, "HiberbootEnabled", winreg.REG_DWORD, val, tweak_id)
    if ok:
        return True, "Hızlı Başlatma (Fast Startup) kapatıldı." if enable else "Hızlı Başlatma açıldı."
    return False, "Hızlı başlatma anahtarı yazılamadı (Yönetici izni gereklidir)."


def apply_unlock_cpu_boost(enable=True, scope="all") -> Tuple[bool, str]:
    tweak_id = "unlock_cpu_boost"
    key_path = r"SYSTEM\CurrentControlSet\Control\Power\PowerSettings\54533251-82be-4824-96c1-47b60b740d00\be337238-0d82-4146-a960-4f3749d470c7"
    val = 2 if enable else 1
    ok = _safe_write_reg(winreg.HKEY_LOCAL_MACHINE, "HKLM", key_path, "Attributes", winreg.REG_DWORD, val, tweak_id)
    if ok:
        return True, "İşlemci Güç Menüsü (Turbo Boost kontrolü) Denetim Masası'nda açığa çıkarıldı." if enable else "İşlemci güç ayarı gizlendi."
    return False, "İşlemci güç ayarı yazılamadı."


def apply_ultimate_performance(enable=True, scope="all") -> Tuple[bool, str]:
    tweak_id = "ultimate_performance"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    powercfg_cmd = get_system32_path("powercfg.exe")
    backup = _load_backup()

    if enable:
        # 1. Mevcut aktif güç planı GUID'ini yedekle (İlk orijinal planı koru, tekrar uygulamada ezme)
        try:
            curr_res = subprocess.run([powercfg_cmd, "/getactivescheme"], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=creationflags, timeout=8)
            guid_match = re.search(r"([0-9a-fA-F-]{36})", curr_res.stdout)
            if guid_match:
                if tweak_id not in backup:
                    backup[tweak_id] = {}
                if "previous_active_scheme" not in backup[tweak_id]:
                    backup[tweak_id]["previous_active_scheme"] = guid_match.group(1)
                    _save_backup(backup)
        except Exception:
            pass

        # 2. Sistemde zaten kayıtlı bir Nihai Performans planı var mı kontrol et (tekrarı önleme)
        target_guid = None
        try:
            list_res = subprocess.run([powercfg_cmd, "/list"], capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=creationflags, timeout=8)
            for line in list_res.stdout.splitlines():
                if "ultimate" in line.lower() or "nihai" in line.lower():
                    m = re.search(r"([0-9a-fA-F-]{36})", line)
                    if m:
                        target_guid = m.group(1)
                        break
        except Exception:
            pass

        # 3. Yoksa şablondan kopyala ve yeni oluşturulan GUID'i yakala
        if not target_guid:
            cmd = [powercfg_cmd, "-duplicatescheme", "e9a42b02-d5df-448d-aa00-03f14749eb61"]
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=creationflags, timeout=10)
            if res.returncode == 0:
                m = re.search(r"([0-9a-fA-F-]{36})", res.stdout)
                if m:
                    target_guid = m.group(1)
                    if tweak_id not in backup:
                        backup[tweak_id] = {}
                    backup[tweak_id]["created_scheme"] = target_guid
                    _save_backup(backup)
            else:
                return False, f"Nihai performans şablonu kopyalanamadı (Kod {res.returncode})"

        if not target_guid:
            return False, "Oluşturulan güç planı GUID'i tespit edilemedi."

        # 4. Yakalanan yeni GUID'i etkinleştir ve dönüş kodunu doğrula
        act_res = subprocess.run([powercfg_cmd, "-setactive", target_guid], capture_output=True, text=True, creationflags=creationflags, timeout=10)
        if act_res.returncode == 0:
            return True, f"Nihai Performans güç planı başarıyla etkinleştirildi ({target_guid})."
        else:
            return False, f"Güç planı etkinleştirilemedi (Kod: {act_res.returncode})"
    else:
        # Geri alma: Önceki kaydedilen plana geri dön
        prev_scheme = backup.get(tweak_id, {}).get("previous_active_scheme")
        created_scheme = backup.get(tweak_id, {}).get("created_scheme")
        target = prev_scheme or "381b4222-f694-41f0-9685-ff5bb260df2e"

        act = subprocess.run([powercfg_cmd, "-setactive", target], capture_output=True, text=True, creationflags=creationflags, timeout=10)
        if act.returncode != 0 and target != "381b4222-f694-41f0-9685-ff5bb260df2e":
            # Önceki plan sistemde artık mevcut değilse standart Dengeli (Balanced) plana dön
            target = "381b4222-f694-41f0-9685-ff5bb260df2e"
            act = subprocess.run([powercfg_cmd, "-setactive", target], capture_output=True, text=True, creationflags=creationflags, timeout=10)

        if act.returncode != 0:
            return False, f"Güç planı eski haline getirilemedi (Kod: {act.returncode})"

        # Oluşturulan şablonu sistemden sil (birikmeyi önle)
        if created_scheme:
            try:
                subprocess.run([powercfg_cmd, "-delete", created_scheme], capture_output=True, creationflags=creationflags, timeout=8)
            except Exception:
                pass

        msg = f"Önceki güç planına başarıyla dönüldü ({target})." if prev_scheme else "Varsayılan Dengeli güç planına dönüldü."
        return True, msg


def apply_virtual_machine_platform(enable=True, scope="all") -> Tuple[bool, str]:
    if not enable:
        return True, "Atlandı"
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        cmd = [get_system32_path("dism.exe"), "/Online", "/Enable-Feature", "/FeatureName:VirtualMachinePlatform", "/All", "/NoRestart"]
        res = subprocess.run(cmd, capture_output=True, text=True, creationflags=creationflags, timeout=120)
        if res.returncode == 3010:
            try:
                from session_manager import SessionManager
                SessionManager.mark_reboot_required()
            except Exception:
                pass
            return True, "Sanal Makine Platformu etkinleştirildi (Sistemin yeniden başlatılması gerekiyor)."
        elif res.returncode == 0:
            return True, "Sanal Makine Platformu başarıyla etkinleştirildi."
        else:
            return False, f"DISM kodu: {res.returncode}"
    except Exception as e:
        return False, f"Sanal Makine hatası: {e}"


def apply_install_wsl2(enable=True, scope="all") -> Tuple[bool, str]:
    if not enable:
        return True, "Atlandı"

    # Windows 10 sürüm kontrolü: WSL2 için Build >= 19041 gereklidir
    import platform
    try:
        build = int(platform.version().split(".")[-1])
        if build < 19041:
            return False, f"WSL2 için Windows 10 2004 (Build 19041) veya Windows 11 gereklidir (Mevcut: {build})."
    except Exception:
        pass

    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        wsl_cmd = get_system32_path("wsl.exe")
        taskkill_cmd = get_system32_path("taskkill.exe")
        proc = subprocess.Popen(
            [wsl_cmd, "--install", "-d", "Ubuntu", "--no-launch"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )

        timed_out = threading.Event()

        def _timeout():
            timed_out.set()
            try:
                subprocess.run([taskkill_cmd, "/F", "/T", "/PID", str(proc.pid)], capture_output=True, creationflags=creationflags)
                proc.kill()
            except Exception:
                pass

        timer = threading.Timer(600, _timeout)  # 10 dakika indirme ve kurulum payı
        timer.daemon = True
        timer.start()

        proc.wait()
        timer.cancel()

        if timed_out.is_set():
            return False, "WSL kurulumu zaman aşımına uğradı (10 dk)."

        if proc.returncode in [0, 3010]:
            try:
                from session_manager import SessionManager
                SessionManager.mark_reboot_required()
            except Exception:
                pass
            return True, "WSL2 ve Ubuntu Linux başarıyla kuruldu (Sistemi yeniden başlatmanız gereklidir)."
        else:
            return False, f"WSL kurulumu kod verdi: {proc.returncode}. (Yönetici izni gereklidir)"
    except Exception as e:
        return False, f"WSL hatası: {e}"


def restart_explorer() -> Tuple[bool, str]:
    """Explorer kabuğunu güvenle yeniden başlatır; yönetici yetkisi sızıntısını önler."""
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        taskkill_cmd = get_system32_path("taskkill.exe")
        tasklist_cmd = get_system32_path("tasklist.exe")
        explorer_cmd = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "explorer.exe")

        subprocess.run([taskkill_cmd, "/f", "/im", "explorer.exe"], capture_output=True, creationflags=creationflags, timeout=8)
        time.sleep(2)  # Windows shell'in kendini otomatik ayağa kaldırması için bekle

        # Hâlâ çalışmıyorsa başlat
        chk = subprocess.run([tasklist_cmd, "/fi", "imagename eq explorer.exe"], capture_output=True, text=True, creationflags=creationflags)
        if "explorer.exe" not in chk.stdout.lower():
            subprocess.Popen([explorer_cmd], creationflags=creationflags)

        return True, "Windows Gezgini başarıyla tazelendi."
    except Exception as e:
        return False, f"Gezgin tazelenemedi: {e}"


def apply_enable_long_paths(enable=True, scope="all") -> Tuple[bool, str]:
    tweak_id = "enable_long_paths"
    key_path = r"SYSTEM\CurrentControlSet\Control\FileSystem"
    val = 1 if enable else 0
    ok = _safe_write_reg(winreg.HKEY_LOCAL_MACHINE, "HKLM", key_path, "LongPathsEnabled", winreg.REG_DWORD, val, tweak_id)
    if ok:
        return True, "Uzun dosya yolu desteği (260+ karakter) etkinleştirildi." if enable else "Uzun dosya yolu desteği kapatıldı."
    return False, "Uzun dosya yolu ayarı kayıt defterine yazılamadı."


def apply_show_seconds_taskbar(enable=True, scope="all") -> Tuple[bool, str]:
    tweak_id = "show_seconds_taskbar"
    val = 1 if enable else 0
    ok = False
    if scope in ("user", "all"):
        ok = _safe_write_reg(winreg.HKEY_CURRENT_USER, "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "ShowSecondsInSystemClock", winreg.REG_DWORD, val, tweak_id)
    if ok:
        return True, "Görev çubuğu saatinde saniyeler görünür yapıldı." if enable else "Görev çubuğu saatinde saniyeler gizlendi."
    return False, "Görev çubuğu saniye ayarı yazılamadı."


TWEAK_ACTIONS = {
    "classic_context_menu": apply_classic_context_menu,
    "show_file_extensions": apply_show_file_extensions,
    "show_hidden_files": apply_show_hidden_files,
    "show_this_pc_desktop": apply_show_this_pc_desktop,
    "disable_telemetry": apply_disable_telemetry,
    "disable_bing_search": apply_disable_bing_search,
    "disable_widgets": apply_disable_widgets,
    "disable_fast_startup": apply_disable_fast_startup,
    "unlock_cpu_boost": apply_unlock_cpu_boost,
    "ultimate_performance": apply_ultimate_performance,
    "virtual_machine_platform": apply_virtual_machine_platform,
    "install_wsl2": apply_install_wsl2,
    "enable_long_paths": apply_enable_long_paths,
    "show_seconds_taskbar": apply_show_seconds_taskbar,
}

# Geri alma sırasında registry'e yazılmasına izin verilen (kök, anahtar, değer adı) üçlüleri.
# tweaks_backup.json kullanıcı yetkisinde değiştirilebileceğinden bu beyaz liste zorunludur:
# yalnızca bilinen ince ayarların dokunduğu konumlara yazılır.
_ALLOWED_REVERT: Dict[str, set] = {
    "show_file_extensions": {
        ("HKCU", r"software\microsoft\windows\currentversion\explorer\advanced", "hidefileext"),
    },
    "show_hidden_files": {
        ("HKCU", r"software\microsoft\windows\currentversion\explorer\advanced", "hidden"),
    },
    "show_this_pc_desktop": {
        ("HKCU", r"software\microsoft\windows\currentversion\explorer\hidedesktopicons\newstartpanel", "{20d04fe0-3aea-1069-a2d8-08002b30309d}"),
    },
    "disable_telemetry": {
        ("HKLM", r"software\policies\microsoft\windows\datacollection", "allowtelemetry"),
    },
    "disable_bing_search": {
        ("HKCU", r"software\policies\microsoft\windows\explorer", "disablesearchboxsuggestions"),
        ("HKCU", r"software\microsoft\windows\currentversion\search", "bingsearchenabled"),
        ("HKCU", r"software\microsoft\windows\currentversion\search", "cortanaconsent"),
    },
    "disable_widgets": {
        ("HKCU", r"software\microsoft\windows\currentversion\explorer\advanced", "taskbarda"),
    },
    "disable_fast_startup": {
        ("HKLM", r"system\currentcontrolset\control\session manager\power", "hiberbootenabled"),
    },
    "unlock_cpu_boost": {
        ("HKLM", r"system\currentcontrolset\control\power\powersettings\54533251-82be-4824-96c1-47b60b740d00\be337238-0d82-4146-a960-4f3749d470c7", "attributes"),
    },
    "enable_long_paths": {
        ("HKLM", r"system\currentcontrolset\control\filesystem", "longpathsenabled"),
    },
    "show_seconds_taskbar": {
        ("HKCU", r"software\microsoft\windows\currentversion\explorer\advanced", "showsecondsinsystemclock"),
    },
}

_ALLOWED_REVERT_TYPES = {winreg.REG_DWORD, winreg.REG_SZ, winreg.REG_EXPAND_SZ}


def _location_allowed(tweak_id: str, root_name: str, key_path: str, value_name: str) -> bool:
    """Geri alma için hedef konumun (kök, anahtar, değer) beyaz listede olup olmadığını denetler."""
    allowed_entries = _ALLOWED_REVERT.get(tweak_id)
    if not allowed_entries:
        return False
    return (root_name.upper(), key_path.lower(), value_name.lower()) in allowed_entries


def _entry_allowed(tweak_id: str, root_name: str, key_path: str, value_name: str, val_type, val_data) -> bool:
    """
    Geri alma için güvenlik beyaz liste doğrulaması.
    JSON'dan okunan girdi yalnızca bilinen (kök, anahtar, değer) üçlüsünde ve
    izin verilen veri tiplerinde ise True döner.
    """
    if not _location_allowed(tweak_id, root_name, key_path, value_name):
        return False
    if val_type not in _ALLOWED_REVERT_TYPES:
        return False
    if val_type == winreg.REG_DWORD and not isinstance(val_data, int):
        return False
    if val_type in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) and not isinstance(val_data, str):
        return False
    return True


def revert_all_tweaks(scope="all") -> List[Tuple[str, bool, str]]:
    """
    Yalnızca tweaks_backup.json dosyasında kayıtlı olan ve daha önce uygulanmış ayarları
    tam olarak orijinal önceki değerlerine döndürür. Hiç uygulanmamış ayarları ezmez.
    Kısmi hata durumunda yalnızca başarılı ayarlar yedekten silinir; başarısız olanlar korunur.
    """
    backup = _load_backup()
    if not backup:
        return [("none", True, "Geri alınacak kayıtlı bir ayar bulunamadı (Henüz bir ince ayar uygulanmamış).")]

    results = []
    successful_tweaks = []

    # 1. Kayıt defteri ayarlarını orijinal hallerine geri yükle
    for tweak_id, entries in list(backup.items()):
        if tweak_id in ["install_wsl2", "virtual_machine_platform"]:
            continue

        if tweak_id == "classic_context_menu":
            try:
                ok, msg = apply_classic_context_menu(False, scope=scope)
                results.append((tweak_id, ok, msg))
                if ok:
                    successful_tweaks.append(tweak_id)
            except Exception as e:
                results.append((tweak_id, False, str(e)))
            continue

        if tweak_id == "ultimate_performance":
            try:
                ok, msg = apply_ultimate_performance(False, scope=scope)
                results.append((tweak_id, ok, msg))
                if ok:
                    successful_tweaks.append(tweak_id)
            except Exception as e:
                results.append((tweak_id, False, str(e)))
            continue

        try:
            rejected = False
            for entry_key, info in entries.items():
                root_name = info["root"]
                key_path = info["key_path"]
                value_name = info["value_name"]
                existed = info["existed"]
                val_data = info["data"]
                val_type = info["type"]

                # 1. Her iki dal için de konum (root, key_path, value_name) beyaz listede olmalı
                if not _location_allowed(tweak_id, root_name, key_path, value_name):
                    sys.stderr.write(
                        f"[GUVENLIK] Geri alma konumu reddedildi ({tweak_id}): "
                        f"{root_name}\\{key_path}\\{value_name} beyaz listede yok.\n"
                    )
                    rejected = True
                    continue

                root = winreg.HKEY_LOCAL_MACHINE if root_name == "HKLM" else winreg.HKEY_CURRENT_USER

                if existed and val_data is not None and val_type is not None:
                    # 2. Geri yazma dalı için veri tipi ve içeriği de doğrula
                    if not _entry_allowed(tweak_id, root_name, key_path, value_name, val_type, val_data):
                        sys.stderr.write(
                            f"[GUVENLIK] Geri alma verisi geçersiz ({tweak_id}): "
                            f"{root_name}\\{key_path}\\{value_name} tip/veri uyumsuz.\n"
                        )
                        rejected = True
                        continue
                    # Beyaz liste doğrulamasından geçti; orijinal değeri geri yaz
                    with winreg.CreateKey(root, key_path) as k:
                        winreg.SetValueEx(k, value_name, 0, val_type, val_data)
                else:
                    # Ayar uygulanmadan önce yoktu; izin verilen değeri sil (beyaz liste onaylı)
                    _safe_delete_reg_value(root, key_path, value_name)

            if rejected:
                results.append((tweak_id, False, "Geri alma reddedildi: yedek dosyası beklenmeyen bir kayıt içeriyor."))
                continue

            results.append((tweak_id, True, "Önceki orijinal durumuna geri döndürüldü."))
            successful_tweaks.append(tweak_id)
        except Exception as e:
            results.append((tweak_id, False, f"Geri alma hatası: {e}"))

    # Yalnızca başarıyla geri alınan ayarları yedekten sil; hatalı olanları koru
    for st in successful_tweaks:
        backup.pop(st, None)

    try:
        if not backup:
            if os.path.exists(BACKUP_FILE):
                os.remove(BACKUP_FILE)
        else:
            _save_backup(backup)
    except Exception as e:
        logger.warning(f"Yedek dosyası güncellenemedi: {e}")

    return results


def create_system_restore_point(description: str = "FormatSonrasi_Tweaks_Backup") -> Tuple[bool, str]:
    """İnce ayarlar öncesinde Windows Sistem Geri Yükleme Noktası (Restore Point) oluşturur.
    Temiz kurulumlarda Sistem Koruması'nı açar ve 24 saat kısıtlamasını aşmak için frekansı ayarlar.
    """
    try:
        clean_desc = re.sub(r"[^A-Za-z0-9_\- ]", "", description)
        ps_cmd = (
            f"try {{ "
            f"  $drive = if ($env:SystemDrive) {{ \"$($env:SystemDrive)\\\" }} else {{ \"C:\\\" }}; "
            f"  Enable-ComputerRestore -Drive $drive -ErrorAction SilentlyContinue; "
            f"  $reg = 'HKLM:\\SOFTWARE\\Microsoft\\Windows NT\\CurrentVersion\\SystemRestore'; "
            f"  if (Test-Path $reg) {{ Set-ItemProperty -Path $reg -Name 'SystemRestorePointCreationFrequency' -Value 0 -Type DWord -ErrorAction SilentlyContinue }}; "
            f"  Checkpoint-Computer -Description '{clean_desc}' -RestorePointType 'MODIFY_SETTINGS' -ErrorAction Stop; "
            f"  exit 0 "
            f"}} catch {{ "
            f"  Write-Host $_.Exception.Message; "
            f"  exit 1 "
            f"}}"
        )
        ps_path = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        res = subprocess.run([ps_path, "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True, timeout=90, creationflags=creationflags)
        if res.returncode == 0:
            return True, "Sistem geri yükleme noktası başarıyla oluşturuldu."
        err_detail = (res.stdout or res.stderr).strip()
        if "1440" in err_detail or "frequency" in err_detail.lower():
            return False, f"Sistem geri yükleme noktası oluşturulamadı (24 saat kısıtı devrede): {err_detail}"
        return False, f"Sistem geri yükleme noktası oluşturulamadı (Sistem Koruması kapalı olabilir veya 24 saat kısıtı devrede): {err_detail or 'Bilinmeyen neden'}"
    except Exception as e:
        logger.warning(f"Geri yükleme noktası çağrısı başarısız: {e}")
        return False, f"Geri yükleme noktası çağrısı başarısız: {e}"
