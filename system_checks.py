# -*- coding: utf-8 -*-
"""
Format Sonrası Kurulum Sihirbazı - Sistem Ön Kontrol Motoru (Pre-Flight Checks)
Kurulum başlamadan önce sistem mimarisi, yetkiler, ağ ve bekleyen yeniden başlatmaları doğrular.
Gelişmiş Windows 10/11 tespiti, gerçek HTTPS 443 host kontrolü ve dinamik disk hesaplama içerir.
"""

import concurrent.futures
import ctypes
import functools
import os
import platform
import shutil
import socket
import subprocess
import winreg
from typing import Dict, Any, List, Optional, Set, Tuple

_SECURE_DIRS_VERIFIED: Set[str] = set()


def is_admin() -> bool:
    """Yönetici hakları kontrolü."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False


SAFE_OWNERS = {"S-1-5-32-544", "S-1-5-18"}  # Administrators, SYSTEM


@functools.lru_cache(maxsize=32)
def get_system32_path(binary_name: str) -> str:
    """System32 dizinindeki sistem yürütülebilir dosyasının tam yolunu döner (binary planting önleme)."""
    if os.name != "nt":
        return binary_name
    sys_root = os.environ.get("SystemRoot", r"C:\Windows")
    clean_name = binary_name.strip()
    if clean_name.lower() in ("powershell.exe", "powershell"):
        ps = os.path.join(sys_root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
        if os.path.isfile(ps):
            return ps
    exe_name = clean_name if clean_name.lower().endswith(".exe") else f"{clean_name}.exe"
    cand = os.path.join(sys_root, "System32", exe_name)
    if os.path.isfile(cand):
        return cand
    return clean_name


@functools.lru_cache(maxsize=1)
def get_winget_path() -> str:
    """Güvenli WinGet yürütülebilir dosya yolunu çözümler (göreli yol ve binary planting önleme)."""
    if os.name != "nt":
        return "winget"
    # 1. Kullanıcı profili App Execution Alias
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if local_app_data:
        p1 = os.path.join(local_app_data, "Microsoft", "WindowsApps", "winget.exe")
        if os.path.isfile(p1):
            return p1
    # 2. Program Files WindowsApps DesktopAppInstaller
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    wa = os.path.join(pf, "WindowsApps")
    if os.path.isdir(wa):
        try:
            for entry in os.listdir(wa):
                if entry.startswith("Microsoft.DesktopAppInstaller_") and entry.endswith("_8wekyb3d8bbwe"):
                    cand = os.path.join(wa, entry, "winget.exe")
                    if os.path.isfile(cand):
                        return cand
        except Exception:
            pass
    # 3. Güvenli mutlak PATH yolu (çalışma dizini dışı)
    w = shutil.which("winget")
    if w and os.path.isabs(w) and not w.lower().startswith(os.getcwd().lower()):
        return w
    return "winget.exe"


def is_reparse_point(path: str) -> bool:
    """Yolun reparse point (junction / sembolik bağ) olup olmadığını denetler."""
    if not os.path.exists(path):
        return False
    if os.path.islink(path):
        return True
    try:
        attrs = os.stat(path).st_file_attributes
        return bool(attrs & 0x400)  # FILE_ATTRIBUTE_REPARSE_POINT (1024)
    except Exception:
        return False


def _owner_sid(path: str) -> str:
    """Belirtilen dizinin sahibinin SID değerini PowerShell Get-Acl ile döner."""
    if os.name != "nt":
        return "S-1-5-32-544"
    ps_exe = get_system32_path("powershell.exe")
    ps_cmd = "(Get-Acl -LiteralPath $env:FS_DIR).GetOwner([System.Security.Principal.SecurityIdentifier]).Value"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        r = subprocess.run(
            [ps_exe, "-NoProfile", "-Command", ps_cmd],
            env=dict(os.environ, FS_DIR=path),
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=creationflags,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def ensure_secure_dir(path: str) -> str:
    """
    Yalnızca Administrators ve SYSTEM'in sahip olduğu ve tam erişime sahip olduğu
    güvenli bir dizin oluşturur veya doğrular.
    Standart kullanıcı sahipliğinde veya reparse point (junction) tespit edilirse silinir ve yeniden kurulur.
    Hata durumunda RuntimeError fırlatır (asla %TEMP%'e düşmez).
    """
    if os.name != "nt":
        os.makedirs(path, exist_ok=True)
        return path

    abs_path = os.path.abspath(path)
    if abs_path.lower() in _SECURE_DIRS_VERIFIED:
        if os.path.isdir(abs_path) and not is_reparse_point(abs_path):
            return abs_path

    # 1. Eğer FormatSonrasi alt dizini ise önce ana C:\ProgramData\FormatSonrasi kökünü güvenceye al
    program_data = os.environ.get("ProgramData", r"C:\ProgramData")
    root_base = os.path.abspath(os.path.join(program_data, "FormatSonrasi"))
    if abs_path.lower() != root_base.lower() and abs_path.lower().startswith(root_base.lower() + os.sep):
        ensure_secure_dir(root_base)

    # 2. Reparse point (junction / symlink) temizliği (junction hijacking önleme)
    if is_reparse_point(abs_path):
        try:
            if os.path.islink(abs_path):
                os.unlink(abs_path)
            else:
                os.rmdir(abs_path)
        except Exception as e:
            raise RuntimeError(f"Reparse point (junction) temizlenemedi: {abs_path} ({e})")

    # 3. Dosya veya yetkisiz kullanıcı sahipliğindeki klasör temizliği
    if os.path.exists(abs_path):
        if not os.path.isdir(abs_path):
            try:
                os.remove(abs_path)
            except Exception as e:
                raise RuntimeError(f"Güvenli dizin yolundaki dosya temizlenemedi: {abs_path} ({e})")
        else:
            owner = _owner_sid(abs_path)
            if owner not in SAFE_OWNERS:
                # Standart kullanıcı veya farklı sahiplik:
                # tweaks_backup.json dosyasını korumak için klasörü silmek yerine
                # sahipliği Administrators grubuna devral.
                preserved_backups = {}
                try:
                    for fname in os.listdir(abs_path):
                        if fname.startswith("tweaks_backup.json"):
                            fpath = os.path.join(abs_path, fname)
                            if os.path.isfile(fpath):
                                with open(fpath, "rb") as bf:
                                    preserved_backups[fname] = bf.read()
                except Exception:
                    pass

                takeown_exe = get_system32_path("takeown.exe")
                cflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                subprocess.run([takeown_exe, "/f", abs_path, "/a"], capture_output=True, creationflags=cflags)
                owner = _owner_sid(abs_path)
                if owner not in SAFE_OWNERS:
                    # Sahiplik devralınamadıysa güvenilmez dizini temizle ama yedeği koru
                    shutil.rmtree(abs_path, ignore_errors=True)
                    os.makedirs(abs_path, exist_ok=True)
                    for fname, bdata in preserved_backups.items():
                        try:
                            with open(os.path.join(abs_path, fname), "wb") as bf:
                                bf.write(bdata)
                        except Exception:
                            pass

    os.makedirs(abs_path, exist_ok=True)
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0

    takeown_exe = get_system32_path("takeown.exe")
    icacls_exe = get_system32_path("icacls.exe")

    # Sahipliği Administrators grubuna ver
    subprocess.run(
        [takeown_exe, "/f", abs_path, "/a"],
        capture_output=True,
        creationflags=creationflags,
    )

    # İzinleri yalnızca Administrators ve SYSTEM ile sınırla
    r = subprocess.run(
        [
            icacls_exe, abs_path,
            "/inheritance:r",
            "/grant:r", "*S-1-5-32-544:(OI)(CI)F",  # Administrators
            "/grant:r", "*S-1-5-18:(OI)(CI)F",       # SYSTEM
        ],
        capture_output=True,
        creationflags=creationflags,
    )
    owner = _owner_sid(abs_path)
    if r.returncode != 0 or owner not in SAFE_OWNERS:
        raise RuntimeError(f"Güvenli dizin oluşturulamadı veya sahipliği doğrulanamadı: {abs_path} (Sahip: {owner})")

    if is_reparse_point(abs_path):
        raise RuntimeError(f"Güvenli dizin bir reparse point (junction) olarak tespit edildi: {abs_path}")

    _SECURE_DIRS_VERIFIED.add(abs_path.lower())
    return abs_path


def check_windows_version() -> Dict[str, Any]:
    """Windows sürüm ve derleme numarası kontrolü."""
    ver = platform.version()
    try:
        build = int(ver.split(".")[-1])
    except Exception:
        build = 0

    # Windows 11 Build >= 22000, Windows 10 Build >= 17763 (1809 LTSC / SAC)
    is_win11 = build >= 22000
    is_win10_supported = 17763 <= build < 22000
    supported = is_win11 or is_win10_supported

    os_name = "Windows 11" if is_win11 else ("Windows 10" if build >= 10240 else "Eski Windows Sürümü")
    detail = f"{os_name} (Derleme: {build})"
    if not supported:
        detail += " - UYARI: WinGet ve modern paketler için Windows 10 1809 (17763) veya Windows 11 gereklidir."

    return {
        "name": "Windows Sürümü",
        "status": supported,
        "detail": detail,
        "critical": True,
    }


def check_architecture() -> Dict[str, Any]:
    """İşlemci ve işletim sistemi mimarisi kontrolü."""
    arch = platform.machine()
    is_64bit = "64" in arch or platform.architecture()[0] == "64bit"
    return {
        "name": "Sistem Mimarisi",
        "status": is_64bit,
        "detail": f"{arch} mimarisi (64-bit)" if is_64bit else f"{arch} (32-bit desteklenmez)",
        "critical": True,
    }


def check_admin_privileges() -> Dict[str, Any]:
    """Yönetici yetkisi kontrolü."""
    admin = is_admin()
    return {
        "name": "Yönetici İzni",
        "status": admin,
        "detail": "Yönetici hakları aktif" if admin else "Yönetici izni yok (Makine geneli kurulumlar ve ayarlar için gereklidir)",
        "critical": True,  # Makine geneli registry ve yazılımlar için artık kritik
    }


def check_internet_connection() -> Dict[str, Any]:
    """
    Paket sunucularına 443 üzerinden paralel bağlantı kontrolü (ThreadPoolExecutor).
    Ana iş parçacığını dondurmadan eşzamanlı test eder.
    Sadece ana paket dağıtım sunucusu (cdn.winget.microsoft.com) kritik kabul edilir.
    """
    hosts = [
        ("cdn.winget.microsoft.com", True),   # Kritik paket sunucusu
        ("github.com", False),                # Yardımcı (doğrudan araçlar ve indirmeler)
        ("community.chocolatey.org", False),  # Yedek paket kaynağı
    ]
    ok, failed = [], []

    def _probe_host(target_host: str) -> Tuple[str, bool]:
        try:
            with socket.create_connection((target_host, 443), timeout=2.5):
                return target_host, True
        except OSError:
            return target_host, False

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(hosts)) as executor:
        future_map = {executor.submit(_probe_host, h[0]): h[0] for h in hosts}
        for future in concurrent.futures.as_completed(future_map):
            h, success = future.result()
            if success:
                ok.append(h)
            else:
                failed.append(h)

    winget_ok = "cdn.winget.microsoft.com" in ok
    detail = f"Erişilebilir: {', '.join(ok) or 'Yok'}"
    if failed:
        detail += f" | Erişilemeyen: {', '.join(failed)}"

    return {
        "name": "İnternet ve Paket Sunucusu Erişimi",
        "status": winget_ok,
        "detail": detail,
        "critical": True,
    }


def check_winget_availability() -> Dict[str, Any]:
    """Winget komut satırı aracının varlığı ve çalışabilirliği."""
    available = False
    detail = "WinGet bulunamadı"
    try:
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        winget_bin = get_winget_path()
        res = subprocess.run(
            [winget_bin, "--version"],
            capture_output=True,
            text=True,
            creationflags=creationflags,
            timeout=8,
        )
        if res.returncode == 0:
            available = True
            clean_ver = res.stdout.strip().lstrip("v")
            detail = f"WinGet v{clean_ver} hazır"
        else:
            detail = "WinGet çağrılamadı veya hata kodu döndürdü"
    except Exception as e:
        detail = f"WinGet bulunamadı: {e}"

    return {
        "name": "WinGet Paket Motoru",
        "status": available,
        "detail": detail,
        "critical": True,
    }


def check_disk_space(required_mb: Optional[int] = None) -> Dict[str, Any]:
    """
    Sistem sürücüsündeki (%SystemDrive%) boş disk alanı kontrolü.
    Seçilen uygulamaların tahmini boyutuna göre dinamik eşik hesaplar.
    """
    try:
        sys_drive = os.environ.get("SystemDrive", "C:")
        if not sys_drive.endswith("\\"):
            sys_drive += "\\"

        total, used, free = shutil.disk_usage(sys_drive)
        free_gb = round(free / (1024**3), 1)

        # Taban 5 GB sistem çalışma payı + seçilen uygulamaların boyutu
        min_required_gb = 5.0
        if required_mb:
            min_required_gb += round((required_mb * 1.5) / 1024, 1)

        sufficient = free_gb >= min_required_gb
        return {
            "name": f"Boş Disk Alanı ({sys_drive})",
            "status": sufficient,
            "detail": f"{free_gb} GB boş alan mevcut (Gereken asgari: ~{min_required_gb:.1f} GB)",
            "critical": not sufficient,
        }
    except Exception as e:
        return {
            "name": "Boş Disk Alanı",
            "status": True,
            "detail": f"Disk alanı okunamadı: {e}",
            "critical": False,
        }


def check_pending_reboot() -> Dict[str, Any]:
    """Sistemde bekleyen bir Windows yeniden başlatması olup olmadığını tespit eder."""
    reboot_pending = False
    reasons = []

    # 1. Component Based Servicing (CBS)
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
        )
        winreg.CloseKey(key)
        reboot_pending = True
        reasons.append("Windows Bileşen Güncellemesi")
    except Exception:
        pass

    # 2. Windows Update Auto Update
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
        )
        winreg.CloseKey(key)
        reboot_pending = True
        reasons.append("Windows Update Güncellemesi")
    except Exception:
        pass

    # Not: PendingFileRenameOperations temiz sistemlerde bile sürücü kilitleri yüzünden
    # sıkça dolu çıktığından tek başına reboot_pending sayılmaz (false-positive önleme).

    return {
        "name": "Bekleyen Yeniden Başlatma",
        "status": not reboot_pending,
        "detail": "Temiz (Yeniden başlatma gerekmiyor)" if not reboot_pending else f"Dikkat: {', '.join(reasons)} için sistem yeniden başlatma bekliyor",
        "critical": False,
    }


def run_all_preflight_checks(required_mb: Optional[int] = None) -> List[Dict[str, Any]]:
    """Tüm ön kontrolleri çalıştırıp sonuç listesi döner."""
    return [
        check_windows_version(),
        check_architecture(),
        check_admin_privileges(),
        check_internet_connection(),
        check_winget_availability(),
        check_disk_space(required_mb),
        check_pending_reboot(),
    ]


def get_interactive_console_user() -> Optional[str]:
    """Aktif etkileşimli konsol oturumunun kullanıcı adını döner."""
    if os.name != "nt":
        return None
    try:
        import ctypes
        from ctypes import wintypes
        wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
        buf = ctypes.c_wchar_p()
        ret_bytes = wintypes.DWORD()
        # WTS_CURRENT_SERVER_HANDLE = 0, WTS_CURRENT_SESSION = -1, WTSUserName = 5
        if wtsapi32.WTSQuerySessionInformationW(0, -1, 5, ctypes.byref(buf), ctypes.byref(ret_bytes)):
            user = buf.value
            wtsapi32.WTSFreeMemory(buf)
            return user
    except Exception:
        pass
    return None


def detect_elevation_user_mismatch() -> Optional[Tuple[str, str]]:
    """
    Uygulama yöneticisi ile masaüstünde oturum açan kullanıcı farklı ise
    (örn: standart kullanıcının UAC'de başka bir yöneticinin parolasını girmesi),
    (process_user, interactive_user) çifti döner; aksi halde None döner.
    """
    if os.name != "nt":
        return None
    try:
        process_user = os.environ.get("USERNAME", "")
        interactive_user = get_interactive_console_user()
        if process_user and interactive_user:
            if process_user.strip().lower() != interactive_user.strip().lower():
                return (process_user.strip(), interactive_user.strip())
    except Exception:
        pass
    return None
