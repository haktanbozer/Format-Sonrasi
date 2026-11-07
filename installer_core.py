# -*- coding: utf-8 -*-
"""
Format Sonrası Kurulum Sihirbazı - Kurulum Motoru (Installer Core)
Winget altyapısını, doğrudan resmi indirmeleri ve özel temiz paket yükleyicilerini destekler.
Güvenli geçici dosyalar, HTTPS zorunluluğu, SHA-256 hash doğrulaması ve girdi filtreleme içerir.
"""

import ctypes
import hashlib
import io
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import urllib.parse
import zipfile
from typing import Callable, List, Dict, Any, Set, Tuple, Optional

from verifier import verify_application_installed, invalidate_registry_cache, invalidate_all_verification_caches
from session_manager import SessionManager
from system_checks import is_admin, ensure_secure_dir, get_system32_path, get_winget_path

# WinGet / AppInstaller hata ve durum kodları
# 0x8A15002B = 2316632107 (işaretsiz) / -1978335189 (işaretli):
# APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE (paket güncel, uygulanabilir güncelleme yok)
APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE = 0x8A15002B


class StrictHTTPSRedirectHandler(urllib.request.HTTPRedirectHandler):
    """
    HTTP downgrade saldırılarını önler: Yalnızca HTTPS -> HTTPS yönlendirmelerine izin verir.
    Herhangi bir http:// yönlendirmesini veya izin verilmeyen hedef sunucuları derhal reddeder.
    """
    ALLOWED_HOST_SUFFIXES = (
        "microsoft.com", ".microsoft.com",
        "aka.ms",
        "github.com", ".github.com",
        "githubusercontent.com", ".githubusercontent.com",
        "chocolatey.org", ".chocolatey.org",
    )

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not newurl.lower().startswith("https://"):
            raise ValueError(f"Güvenlik Engeli: Güvenli olmayan HTTP protokolüne yönlendirme reddedildi: {newurl}")
        parsed = urllib.parse.urlparse(newurl)
        host = parsed.netloc.lower().split(":")[0]
        allowed = any(host == s or host.endswith(s if s.startswith(".") else "." + s) for s in self.ALLOWED_HOST_SUFFIXES)
        if not allowed:
            raise ValueError(f"Güvenlik Engeli: İzin verilmeyen sunucuya yönlendirme engellendi: {host}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def request_admin_elevation():
    """Programı yönetici olarak güvenle (komut enjeksiyonu korumalı) yeniden başlatır."""
    if getattr(sys, "frozen", False):
        exe = sys.executable
        args = subprocess.list2cmdline(sys.argv[1:])
    else:
        exe = sys.executable
        args = subprocess.list2cmdline(sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, args, None, 1)


def detect_installed_packages() -> Set[str]:
    """Sistemde kurulu olan winget paket kimliklerini doğrulanmış JSON motoruyla tespit eder."""
    try:
        from verifier import get_all_winget_installed_ids
        return get_all_winget_installed_ids()
    except Exception as e:
        sys.stderr.write(f"[UYARI] Kurulu paket tarama hatası: {e}\n")
        return set()


class InstallationWorker(threading.Thread):
    def __init__(
        self,
        app_list: List[Dict[str, Any]],
        on_log: Callable[[str], None],
        on_progress: Callable[[int, int, str, str], None],
        on_app_completed: Callable[[str, bool, str], None],
        on_finished: Callable[[Dict[str, Any]], None],
    ):
        super().__init__(daemon=True)
        self.app_list = app_list
        self.on_log = on_log
        self.on_progress = on_progress
        self.on_app_completed = on_app_completed
        self.on_finished = on_finished
        self.is_cancelled = False
        self.current_process = None

    def _kill_current_process(self):
        """Aktif alt süreç ağacını Windows üzerinde kalıntı bırakmadan zorla sonlandırır."""
        proc = self.current_process
        if proc:
            try:
                pid = proc.pid
                creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                subprocess.run(
                    [get_system32_path("taskkill.exe"), "/F", "/T", "/PID", str(pid)],
                    capture_output=True,
                    creationflags=creationflags,
                    timeout=5,
                )
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass
            self.current_process = None

    def cancel(self):
        """Devam eden ve sıradaki kurulumları iptal eder."""
        self.is_cancelled = True
        self._kill_current_process()

    def run(self):
        total = len(self.app_list)
        successful = 0
        verified_count = 0
        unverified_count = 0
        already_installed_count = 0
        failed = 0
        reboot_required = False
        results = []

        # Oturum kaydını başlat (kurtarma ve dayanıklılık mekanizması)
        SessionManager.create_session(self.app_list)
        invalidate_all_verification_caches()

        self.on_log(f"[ISLEM] Kurulum sirasi baslatildi. Toplam {total} uygulama kurulacak.")
        self.on_log("[BILGI] Uygulamalar dosya agirligina gore optimize edilerek siraya dizildi (Hafif -> Agir).\n")

        for index, app in enumerate(self.app_list, start=1):
            if self.is_cancelled:
                self.on_log("\n[UYARI] Kurulum kullanici tarafindan durduruldu.")
                break

            app_id = app["id"]
            app_name = app["name"]
            install_type = app.get("install_type", "winget")

            # Aktif kurulan uygulamayı oturuma işle
            SessionManager.update_current_app(app_id, app_name)

            self.on_progress(index, total, app_name, "Kuruluyor")
            success = False
            verified = False
            msg = ""

            try:
                if install_type == "filezilla_clean":
                    success, msg, is_reboot, is_already = self._install_filezilla_clean(index, total, app)
                elif install_type == "dism_feature":
                    success, msg, is_reboot, is_already = self._install_dism_feature(index, total, app_name, app.get("feature_name", "NetFx3"))
                elif install_type == "direct_exe":
                    success, msg, is_reboot, is_already = self._install_direct_exe(index, total, app)
                else:
                    success, msg, is_reboot, is_already = self._install_winget(index, total, app)

                if is_reboot:
                    reboot_required = True
                    task_ok = SessionManager.mark_reboot_required()
                    if not task_ok:
                        self.on_log(f"    [UYARI] Otomatik devam görevi zamanlanamadı. Sistemi yeniden başlattıktan sonra uygulamayı lütfen elle açın.")
                    self.on_log(f"    [REBOOT] '{app_name}' sistem yeniden baslatmasi istiyor.")

                # Kurulum sonrası hafif kayıt defteri önbelleğini yenile ve gerçek doğrulama motorunu çalıştır
                invalidate_registry_cache()
                if success:
                    is_ok, v_detail = verify_application_installed(app, allow_winget_refresh=True)
                    if is_ok:
                        verified = True
                        if is_already:
                            already_installed_count += 1
                            self.on_log(f"    > Dogrulama: [ONCEDEN KURULU] {v_detail}\n")
                        else:
                            verified_count += 1
                            self.on_log(f"    > Dogrulama: [BASARILI] {v_detail}\n")
                    else:
                        verified = False
                        unverified_count += 1
                        self.on_log(f"    > Dogrulama: [UYARI] Kurulum bitti fakat sistem kaydi dogrulanamadi ({v_detail})\n")
                else:
                    self.on_log(f"    > Kurulum basarisiz oldu: {msg}\n")

            except Exception as e:
                success = False
                verified = False
                msg = str(e)
                self.on_log(f"[{index}/{total}] [HATA] '{app_name}' calistirilirken istisna: {e}\n")

            if self.is_cancelled:
                if success:
                    successful += 1
                    SessionManager.record_app_result(app_id, app_name, success, verified, msg)
                    results.append({
                        "app": app,
                        "success": success,
                        "verified": verified,
                        "message": msg,
                    })
                    self.on_app_completed(app_id, success, msg)
                else:
                    self.on_log(f"[{index}/{total}] [İPTAL] '{app_name}' kurulumu kullanıcı tarafından durduruldu.")
                    self.on_app_completed(app_id, False, "İptal Edildi")
                break

            if success:
                successful += 1
            else:
                failed += 1

            # Oturumu güncelle
            SessionManager.record_app_result(app_id, app_name, success, verified, msg)

            results.append({
                "app": app,
                "success": success,
                "verified": verified,
                "message": msg,
            })
            self.on_app_completed(app_id, success, msg)

        if not self.is_cancelled:
            if failed == 0:
                SessionManager.finish_session()
            else:
                self.on_log(f"\n[BİLGİ] {failed} uygulama tamamlanamadı. Oturum açık tutuldu; 'Başarısızları Seç' butonu ile tekrar deneyebilirsiniz.")

        summary = {
            "total": total,
            "successful": successful,
            "verified_count": verified_count,
            "unverified_count": unverified_count,
            "already_installed_count": already_installed_count,
            "failed": failed,
            "cancelled": self.is_cancelled,
            "reboot_required": reboot_required,
            "results": results,
        }
        self.on_finished(summary)

    def _install_winget(self, index: int, total: int, app: Dict[str, Any], timeout_sec: int = 900) -> Tuple[bool, str, bool, bool]:
        app_name = app["name"]
        winget_id = app["winget_id"]
        self.on_log(f"[{index}/{total}] [INDIRILIYOR] '{app_name}' winget ile indiriliyor ve kuruluyor ({winget_id})...")

        source = app.get("source", "winget")
        # Yalnızca bilinen WinGet kaynak adlarına izin ver (komut listesi olsa da savunma derinliği)
        if source not in {"winget", "msstore"}:
            self.on_log(f"[{index}/{total}] [GUVENLIK HATASI] Bilinmeyen kaynak reddedildi: {source!r}\n")
            return False, f"Güvenlik Engeli: Bilinmeyen winget kaynağı ({source!r})", False, False
        winget_bin = get_winget_path()
        cmd = [
            winget_bin,
            "install",
            "--id",
            winget_id,
            "-e",
            "--silent",
            "--disable-interactivity",
            "--accept-package-agreements",
            "--accept-source-agreements",
            "--source",
            source,
        ]

        start_time = time.time()
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self.current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
        except Exception as e:
            return False, f"Başlatılamadı: {e}", False, False

        stdout_lines = []
        ret_code = -1
        timed_out = threading.Event()

        def _on_timeout():
            timed_out.set()
            self.on_log(f"[{index}/{total}] [ZAMAN AŞIMI] '{app_name}' kurulumu {timeout_sec} saniye zaman aşımına uğradı.\n")
            self._kill_current_process()

        timer = threading.Timer(timeout_sec, _on_timeout)
        timer.daemon = True
        timer.start()

        try:
            for line in iter(self.current_process.stdout.readline, ""):
                if self.is_cancelled or timed_out.is_set():
                    break
                clean_line = line.strip()
                if clean_line:
                    stdout_lines.append(clean_line)
                    if any(k in clean_line.lower() for k in ["indiriliyor", "downloading", "kuruluyor", "installing", "successfully", "başarıyla", "hata", "error"]):
                        self.on_log(f"    > {clean_line}")

            if timed_out.is_set():
                return False, f"Zaman aşımı ({timeout_sec // 60} dk)", False, False

            if self.is_cancelled:
                self._kill_current_process()
                return False, "Kullanıcı tarafından iptal edildi", False, False

            if self.current_process:
                self.current_process.wait(timeout=30)
                ret_code = self.current_process.returncode
        except subprocess.TimeoutExpired:
            self._kill_current_process()
            return False, "Zaman aşımı", False, False
        finally:
            timer.cancel()
            self.current_process = None

        if timed_out.is_set():
            return False, f"Zaman aşımı ({timeout_sec // 60} dk)", False, False

        elapsed = round(time.time() - start_time, 1)
        ret_u = ret_code & 0xFFFFFFFF

        if ret_u in (0, 3010):
            is_reboot = (ret_u == 3010)
            self.on_log(f"[{index}/{total}] [TAMAMLANDI] '{app_name}' basariyla kuruldu ({elapsed} sn).\n")
            return True, f"Kuruldu ({elapsed} sn)", is_reboot, False
        elif ret_u == APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE:
            # WinGet APPINSTALLER_CLI_ERROR_UPDATE_NOT_APPLICABLE (0x8A15002B)
            # Paket sistemde zaten mevcut ve daha yeni bir sürümü yok
            self.on_log(f"[{index}/{total}] [BILGI] '{app_name}' zaten sistemde guncel surumde mevcut.\n")
            return True, "Zaten kurulu", False, True
        else:
            self.on_log(f"[{index}/{total}] [HATA] '{app_name}' kurulumu tamamlanamadi (Kod: {ret_code}).")
            if stdout_lines:
                self.on_log(f"    Son cikti: {stdout_lines[-1]}\n")
            return False, f"Hata Kodu: {ret_code}", False, False

    def _verify_authenticode(self, path: str, publisher: Optional[str] = None) -> Tuple[bool, str]:
        """PowerShell Get-AuthenticodeSignature ile güvenli imza ve yayıncı kontrolü yapar."""
        env = dict(os.environ, FS_PATH=path)
        ps = (
            "$s = Get-AuthenticodeSignature -LiteralPath $env:FS_PATH; "
            "$s.Status.ToString(); "
            "if ($s.SignerCertificate) { $s.SignerCertificate.Subject } else { '' }"
        )
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        ps_bin = get_system32_path("powershell.exe")
        try:
            r = subprocess.run(
                [ps_bin, "-NoProfile", "-Command", ps],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
                creationflags=creationflags,
            )
            lines = [line.strip() for line in r.stdout.strip().splitlines() if line.strip()]
            status = lines[0] if lines else "Unknown"
            subject = lines[1] if len(lines) > 1 else ""
            # Tam CN= eşleşmesi — substring kontrolü "Tim Kosse Evil Corp" gibi sahte CN'leri geçirir.
            if publisher:
                m = re.search(r"(?:^|,\s*)CN=([^,]+)", subject)
                cn = m.group(1).strip().strip('"') if m else ""
                ok = (status == "Valid") and (publisher.lower() == cn.lower())
            else:
                ok = (status == "Valid")
            return ok, f"{status} | {subject}"
        except Exception as e:
            return False, f"Doğrulama Hatası: {e}"

    def _secure_download_dir(self) -> str:
        """
        Yalnızca Administrators ve SYSTEM'in yazabildiği güvenli indirme dizini döner.
        İmza kontrolü ile çalıştırma arasındaki TOCTOU penceresini kapatır.
        Hata durumunda RuntimeError fırlatır (güvenlik gereği asla %TEMP%'e düşmez).
        """
        program_data = os.environ.get("ProgramData", r"C:\ProgramData")
        base = os.path.join(program_data, "FormatSonrasi", "downloads")
        return ensure_secure_dir(base)

    def _install_direct_exe(self, index: int, total: int, app: Dict[str, Any]) -> Tuple[bool, str, bool, bool]:
        app_name = app["name"]
        download_url = app["download_url"]
        silent_args = app.get("silent_args", ["/quiet", "/norestart"])
        expected_sha256 = app.get("sha256")
        max_size_mb = max(app.get("size_mb", 100) * 3, 2048)  # Güvenlik sınırı
        max_bytes = max_size_mb * 1024 * 1024

        # 1. URL Güvenlik Doğrulaması (Yalnızca HTTPS kabul edilir)
        if not download_url.startswith("https://"):
            self.on_log(f"[{index}/{total}] [GUVENLIK HATASI] Güvenli olmayan URL reddedildi: {download_url}\n")
            return False, "Güvenlik Engeli: Yalnızca HTTPS URL'leri desteklenir", False, False

        # Güvenlik ilkesi: İndirilecek doğrudan ikilinin ya bilinen SHA-256 özeti ya da resmi yayıncısı tanımlı olmalıdır
        expected_pub = app.get("publisher")
        if not expected_sha256 and not expected_pub:
            self.on_log(f"[{index}/{total}] [GUVENLIK ENGELI] '{app_name}' için ne SHA-256 ne de yayıncı sertifikası tanımlı!\n")
            return False, "Güvenlik Engeli: Ne SHA-256 ne de yayıncı sertifikası tanımlanmış", False, False

        self.on_log(f"[{index}/{total}] [INDIRILIYOR] '{app_name}' resmi sunucudan güvenle indiriliyor...")
        start_time = time.time()

        temp_fd = None
        temp_exe = None
        try:
            # 2. Yalnızca yöneticinin yazabildiği güvenli dizine indirme (TOCTOU koruması)
            # İmza kontrolü ile çalıştırma arasındaki pencerede aynı kullanıcı dosyayı değiştiremez.
            secure_dir = self._secure_download_dir()
            temp_fd, temp_exe = tempfile.mkstemp(prefix="inst_", suffix=".exe", dir=secure_dir)
            hasher = hashlib.sha256()
            total_bytes = 0

            req = urllib.request.Request(
                download_url,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            )
            # HTTP Downgrade ve hedef alan adı kontrolü yapan özel yönlendirme yöneticisi
            opener = urllib.request.build_opener(StrictHTTPSRedirectHandler())
            with opener.open(req, timeout=120) as resp:
                with os.fdopen(temp_fd, "wb") as f:
                    temp_fd = None  # fdopen sahiplendi
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        total_bytes += len(chunk)
                        if total_bytes > max_bytes:
                            raise ValueError(f"İndirilen dosya boyutu güvenlik sınırını aştı ({max_size_mb} MB).")
                        hasher.update(chunk)
                        f.write(chunk)

            # 3. İsteğe Bağlı SHA-256 Hash veya Authenticode İmza Doğrulaması
            calculated_hash = hasher.hexdigest().lower()
            if expected_sha256:
                if calculated_hash != expected_sha256.lower():
                    self.on_log(f"[{index}/{total}] [GUVENLIK ENGELI] SHA-256 bütünlük doğrulaması başarısız!\n")
                    return False, "Hash Uyuşmazlığı (Dosya değiştirilmiş olabilir)", False, False
                self.on_log(f"    > SHA-256 bütünlük doğrulaması başarılı.")

            if not expected_sha256 or expected_pub:
                ok, sig_info = self._verify_authenticode(temp_exe, publisher=expected_pub)
                if not ok:
                    self.on_log(f"[{index}/{total}] [GUVENLIK ENGELI] Dijital imza doğrulaması başarısız ({sig_info})!\n")
                    return False, f"Güvenlik Engeli: Geçersiz Dijital İmza ({sig_info})", False, False
                self.on_log(f"    > Authenticode dijital imzası geçerli ({sig_info}).")

            # 4. Çalıştırmadan hemen önce diskteki dosyanın hash'ini yeniden doğrula (Zero TOCTOU güvencesi)
            if expected_sha256:
                h_final = hashlib.sha256()
                with open(temp_exe, "rb") as f_chk:
                    while chunk := f_chk.read(65536):
                        h_final.update(chunk)
                if h_final.hexdigest().lower() != expected_sha256.lower():
                    self.on_log(f"[{index}/{total}] [GUVENLIK ENGELI] Çalıştırma öncesi hash uyuşmazlığı!\n")
                    return False, "Güvenlik Engeli: Çalıştırma öncesi dosya bütünlüğü bozulmuş", False, False

            self.on_log(f"[{index}/{total}] [KURULUYOR] '{app_name}' sessiz kurulum çalıştırılıyor...")
            cmd = [temp_exe] + silent_args
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self.current_process = subprocess.Popen(cmd, creationflags=creationflags)
            try:
                self.current_process.wait(timeout=600)
                ret_code = self.current_process.returncode
            except subprocess.TimeoutExpired:
                self.on_log(f"[{index}/{total}] [ZAMAN AŞIMI] '{app_name}' sessiz kurulumu 10 dakika zaman aşımına uğradı.\n")
                self._kill_current_process()
                return False, "Zaman aşımı (10 dk)", False, False
            finally:
                self.current_process = None

            elapsed = round(time.time() - start_time, 1)
            if ret_code in [0, 3010]:
                is_reboot = (ret_code == 3010)
                self.on_log(f"[{index}/{total}] [TAMAMLANDI] '{app_name}' başarıyla kuruldu ({elapsed} sn).\n")
                return True, f"Kuruldu ({elapsed} sn)", is_reboot, False
            else:
                self.on_log(f"[{index}/{total}] [HATA] '{app_name}' hata kodu ile bitti: {ret_code}\n")
                return False, f"Hata: {ret_code}", False, False

        finally:
            if temp_fd is not None:
                try:
                    os.close(temp_fd)
                except Exception:
                    pass
            if temp_exe and os.path.exists(temp_exe):
                try:
                    os.remove(temp_exe)
                except Exception:
                    pass

    def _install_filezilla_clean(self, index: int, total: int, app: Dict[str, Any]) -> Tuple[bool, str, bool, bool]:
        app_name = app["name"]
        self.on_log(f"[{index}/{total}] [INDIRILIYOR] '{app_name}' reklamsiz paket indiriliyor...")
        start_time = time.time()

        max_pkg_size = 60 * 1024 * 1024  # En fazla 60 MB paket boyutu
        req = urllib.request.Request(
            "https://community.chocolatey.org/api/v2/package/filezilla",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        )
        opener = urllib.request.build_opener(StrictHTTPSRedirectHandler())
        with opener.open(req, timeout=40) as resp:
            pkg_data = resp.read(max_pkg_size + 1)
            if len(pkg_data) > max_pkg_size:
                return False, "Güvenlik Sınırı: Paket boyutu aşırı büyük", False, False

        z = zipfile.ZipFile(io.BytesIO(pkg_data))
        target_name = None
        for name in z.namelist():
            if name.startswith("tools/FileZilla_") and name.endswith("_win64-setup.exe"):
                # Zip bomb koruması: Açılmış boyut 80 MB'tan büyük olamaz
                info = z.getinfo(name)
                if info.file_size > 80 * 1024 * 1024:
                    return False, "Güvenlik Sınırı: Paketten çıkan dosya aşırı büyük (Zip bomb koruması)", False, False
                target_name = name
                break

        if not target_name:
            self.on_log(f"[{index}/{total}] [HATA] FileZilla kurulum ikili dosyasi bulunamadi.\n")
            return False, "Paket icerigi gecersiz", False, False

        installer_bytes = z.read(target_name)
        temp_fd = None
        temp_exe = None

        try:
            # Yalnızca yöneticinin yazabildiği güvenli dizine yaz (TOCTOU koruması)
            secure_dir = self._secure_download_dir()
            temp_fd, temp_exe = tempfile.mkstemp(prefix="fz_clean_", suffix=".exe", dir=secure_dir)
            with os.fdopen(temp_fd, "wb") as f:
                temp_fd = None
                f.write(installer_bytes)

            # FileZilla temiz paketinin dijital imzasını ve yayıncısını doğrula
            target_pub = app.get("publisher", "Tim Kosse")
            ok, sig_info = self._verify_authenticode(temp_exe, publisher=target_pub)
            if not ok:
                self.on_log(f"[{index}/{total}] [GUVENLIK ENGELI] FileZilla dijital imza doğrulaması başarısız ({sig_info})!\n")
                return False, f"Güvenlik Engeli: Geçersiz FileZilla İmzası ({sig_info})", False, False
            self.on_log(f"    > FileZilla resmi dijital imzası doğrulandı ({sig_info}).")

            self.on_log(f"[{index}/{total}] [KURULUYOR] Sessiz kurulum calistiriliyor...")
            cmd = [temp_exe, "/S"]
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self.current_process = subprocess.Popen(cmd, creationflags=creationflags)
            try:
                self.current_process.wait(timeout=300)
                ret_code = self.current_process.returncode
            except subprocess.TimeoutExpired:
                self.on_log(f"[{index}/{total}] [ZAMAN AŞIMI] '{app_name}' kurulumu zaman aşımına uğradı.\n")
                self._kill_current_process()
                return False, "Zaman aşımı (5 dk)", False, False
            finally:
                self.current_process = None

            elapsed = round(time.time() - start_time, 1)
            if ret_code in [0, 3010]:
                is_reboot = (ret_code == 3010)
                self.on_log(f"[{index}/{total}] [TAMAMLANDI] '{app_name}' basariyla kuruldu ({elapsed} sn).\n")
                return True, f"Kuruldu ({elapsed} sn)", is_reboot, False
            else:
                self.on_log(f"[{index}/{total}] [HATA] '{app_name}' kurulum kodu: {ret_code}\n")
                return False, f"Hata: {ret_code}", False, False
        finally:
            if temp_fd is not None:
                try:
                    os.close(temp_fd)
                except Exception:
                    pass
            if temp_exe and os.path.exists(temp_exe):
                try:
                    os.remove(temp_exe)
                except Exception:
                    pass

    def _install_dism_feature(self, index: int, total: int, app_name: str, feature_name: str) -> Tuple[bool, str, bool, bool]:
        # Girdi Temizliği (Komut enjeksiyonu önleme)
        if not re.match(r"^[A-Za-z0-9_.-]+$", feature_name):
            return False, "Geçersiz Windows bileşen adı", False, False

        self.on_log(f"[{index}/{total}] [ISLEM] '{app_name}' Windows bileseni etkinlestiriliyor (DISM)...")
        start_time = time.time()
        timeout_sec = 600

        dism_bin = get_system32_path("dism.exe")
        cmd = [dism_bin, "/Online", "/Enable-Feature", f"/FeatureName:{feature_name}", "/All", "/NoRestart"]
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self.current_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )
        except Exception as e:
            return False, f"DISM başlatılamadı: {e}", False, False

        ret_code = -1
        timed_out = threading.Event()

        def _on_timeout():
            timed_out.set()
            self.on_log(f"[{index}/{total}] [ZAMAN AŞIMI] DISM işlemi {timeout_sec} saniye zaman aşımına uğradı.\n")
            self._kill_current_process()

        timer = threading.Timer(timeout_sec, _on_timeout)
        timer.daemon = True
        timer.start()

        try:
            for line in iter(self.current_process.stdout.readline, ""):
                if self.is_cancelled or timed_out.is_set():
                    break
                clean = line.strip()
                if "%" in clean or "başarılı" in clean.lower() or "success" in clean.lower():
                    self.on_log(f"    > {clean}")

            if timed_out.is_set():
                return False, f"DISM zaman aşımı ({timeout_sec // 60} dk)", False, False

            if self.is_cancelled:
                self._kill_current_process()
                return False, "Kullanıcı tarafından iptal edildi", False, False

            if self.current_process:
                self.current_process.wait(timeout=30)
                ret_code = self.current_process.returncode
        except subprocess.TimeoutExpired:
            self._kill_current_process()
            return False, "DISM zaman aşımı", False, False
        finally:
            timer.cancel()
            self.current_process = None

        if timed_out.is_set():
            return False, f"DISM zaman aşımı ({timeout_sec // 60} dk)", False, False

        elapsed = round(time.time() - start_time, 1)

        if ret_code in [0, 3010]:
            is_reboot = (ret_code == 3010)
            self.on_log(f"[{index}/{total}] [TAMAMLANDI] '{app_name}' basariyla etkinlestirildi ({elapsed} sn).\n")
            return True, f"Etkinlestirildi ({elapsed} sn)", is_reboot, False
        else:
            self.on_log(f"[{index}/{total}] [HATA] DISM hatasi: Kod {ret_code}\n")
            return False, f"DISM Kodu: {ret_code}", False, False
