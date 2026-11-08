# -*- coding: utf-8 -*-
"""
Format Sonrası Kurulum Sihirbazı - Oturum ve Kurtarma Yöneticisi (Session Manager)
Elektrik kesintisi, sistem çökmesi veya yeniden başlatma durumlarında kaldığı yerden devam etmeyi sağlar.
Bozuk JSON koruması (.bak doğrulama), thread güvenliği (RLock), başarısız olanları yeniden deneme,
artık geçici dosya temizliği, geçmiş oturum arşivleme (history/) ve en yüksek yetkili Windows
Zamanlanmış Görev (schtasks) ile otomatik devam entegrasyonu içerir.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import winreg
from typing import Dict, Any, Optional, List, Tuple
from system_checks import ensure_secure_dir, get_system32_path
import apps_data
from app_logger import get_logger

logger = get_logger('session_manager')


def _get_session_dir() -> str:
    """Oturum dosyalarının güvenli ve yazılabilir bir dizinde saklanmasını sağlar."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data and os.path.isdir(local_app_data):
        target_dir = os.path.join(local_app_data, "FormatSonrasi")
    else:
        user_profile = os.environ.get("USERPROFILE", r"C:\Users\Default")
        target_dir = os.path.join(user_profile, "AppData", "Local", "FormatSonrasi")

    try:
        os.makedirs(target_dir, exist_ok=True)
    except Exception as e:
        logger.debug(f"Oturum dizini oluşturulamadı: {e}")
    return target_dir


SESSION_DIR = _get_session_dir()
SESSION_FILE = os.path.join(SESSION_DIR, "session_state.json")
BACKUP_SESSION_FILE = os.path.join(SESSION_DIR, "session_state.json.bak")


class SessionManager:
    _lock = threading.RLock()

    @staticmethod
    def cleanup_stale_temp_files():
        """Geçmiş çökmelerden kalan sess_*.tmp artık dosyalarını ve stale bin kopyasını temizler."""
        with SessionManager._lock:
            try:
                for item in os.listdir(SESSION_DIR):
                    if item.startswith("sess_") and item.endswith(".tmp"):
                        p = os.path.join(SESSION_DIR, item)
                        try:
                            os.remove(p)
                        except Exception:
                            pass
            except Exception:
                pass

            # ProgramData\FormatSonrasi\bin altındaki artık resume kopyasını (normal açılışta) temizle
            try:
                program_data = os.environ.get("ProgramData", r"C:\ProgramData")
                bin_dir = os.path.join(program_data, "FormatSonrasi", "bin")
                running_from_bin = os.path.dirname(os.path.abspath(sys.executable)).lower() == os.path.abspath(bin_dir).lower()
                if not running_from_bin and os.path.isdir(bin_dir):
                    shutil.rmtree(bin_dir, ignore_errors=True)
            except Exception:
                pass

    @staticmethod
    def create_session(app_list: List[Dict[str, Any]], inherit_completed: bool = True) -> Dict[str, Any]:
        """Yeni bir kurulum oturumu başlatır veya mevcut oturumdaki tamamlanmış uygulamaları devralarak kaydeder."""
        with SessionManager._lock:
            existing = SessionManager.get_current_session() if inherit_completed else None
            existing_completed = []
            new_ids = {a["id"] for a in app_list}

            if existing and "completed_apps" in existing:
                # Yeni kuyrukta tekrar denenecek olanları devralma listesinden çıkar, diğer başarıları koru
                existing_completed = [c for c in existing["completed_apps"] if c.get("id") not in new_ids]

            SessionManager.cleanup_stale_temp_files()
            session_data = {
                "session_id": existing.get("session_id") if existing else f"session_{int(time.time())}",
                "created_at": existing.get("created_at") if existing else time.strftime("%Y-%m-%d %H:%M:%S"),
                "status": "in_progress",
                "total_count": len(existing_completed) + len(app_list),
                "completed_apps": existing_completed,
                "pending_app_ids": [a["id"] for a in app_list],
                "failed_app_ids": [],
                "current_app": None,
                "reboot_required": False,
            }
            SessionManager._write_file_atomic(session_data)
            return session_data

    @staticmethod
    def update_current_app(app_id: str, app_name: str):
        """Şu anda kurulmakta olan uygulamayı günceller."""
        with SessionManager._lock:
            session = SessionManager.get_current_session()
            if session:
                session["current_app"] = {"id": app_id, "name": app_name}
                SessionManager._write_file_atomic(session)

    @staticmethod
    def record_app_result(app_id: str, app_name: str, success: bool, verified: bool, message: str):
        """
        Bir uygulamanın durumunu kaydeder; başarısızları ayrıca failed listesine ekler.
        Daha önce başarısız olup bu sefer başarılı olanları failed listesinden çıkarır.
        completed_apps içinde mükerrer kayıt oluşmasını engeller.
        """
        with SessionManager._lock:
            session = SessionManager.get_current_session()
            if not session:
                return

            if "pending_app_ids" in session and app_id in session["pending_app_ids"]:
                session["pending_app_ids"].remove(app_id)

            session["current_app"] = None

            if not success:
                if "failed_app_ids" not in session:
                    session["failed_app_ids"] = []
                if app_id not in session["failed_app_ids"]:
                    session["failed_app_ids"].append(app_id)
            else:
                if "failed_app_ids" in session and app_id in session["failed_app_ids"]:
                    session["failed_app_ids"].remove(app_id)

            status_tag = "verified" if (success and verified) else ("completed_unverified" if success else "failed")
            new_entry = {
                "id": app_id,
                "name": app_name,
                "status": status_tag,
                "success": success,
                "verified": verified,
                "message": message,
                "timestamp": time.strftime("%H:%M:%S"),
            }

            if "completed_apps" not in session:
                session["completed_apps"] = []

            existing_index = next((i for i, item in enumerate(session["completed_apps"]) if item.get("id") == app_id), None)
            if existing_index is not None:
                session["completed_apps"][existing_index] = new_entry
            else:
                session["completed_apps"].append(new_entry)

            SessionManager._write_file_atomic(session)

    @staticmethod
    def mark_reboot_required(register_task=True) -> bool:
        """Oturumda sistem yeniden başlatması gerektiğini işaretler ve yalnızca aktif oturum varsa görev ekler."""
        has_active_session = False
        with SessionManager._lock:
            session = SessionManager.get_current_session()
            if session:
                session["reboot_required"] = True
                SessionManager._write_file_atomic(session)
                has_active_session = True

        # schtasks alt süreç çağrısı yalnızca aktif bir kurulum oturumu varsa oluşturulur
        if register_task and has_active_session:
            return SessionManager.register_resume_task()
        return True

    @staticmethod
    def _get_secure_bin_dir() -> str:
        """Yalnızca Administrators ve SYSTEM'in yazabildiği güvenli ikili klasörünü döner."""
        program_data = os.environ.get("ProgramData", r"C:\ProgramData")
        bin_dir = os.path.join(program_data, "FormatSonrasi", "bin")
        return ensure_secure_dir(bin_dir)

    @staticmethod
    def _build_resume_command() -> str:
        """Donmuş .exe komutunu korumalı dizinden doğru şekilde parametrelendirir."""
        if getattr(sys, "frozen", False):
            # Güvenlik: Yükseltilmiş zamanlanmış görevin kullanıcı tarafından yazılabilir bir dizindeki
            # (.Downloads vb.) ikiliyi çalıştırmasını önlemek için ikiliyi korumalı %ProgramData%\FormatSonrasi\bin
            # dizinine kopyalar ve görevi oradan başlatır.
            try:
                secure_bin_dir = SessionManager._get_secure_bin_dir()
                secure_exe = os.path.join(secure_bin_dir, "FormatSonrasiKurulum.exe")

                # Tekrarlı kopyalamayı önleme: Dosya zaten mevcut, boyutu ve mtime eşleşiyorsa,
                # ve kaynakta _internal varsa hedefte de eksiksiz mevcutsa baştan kopyalamayı atla.
                need_copy = True
                exe_dir = os.path.dirname(sys.executable)
                internal_dir = os.path.join(exe_dir, "_internal")
                target_internal = os.path.join(secure_bin_dir, "_internal")

                if os.path.isfile(secure_exe):
                    try:
                        src_stat = os.stat(sys.executable)
                        dst_stat = os.stat(secure_exe)
                        same_size = (src_stat.st_size == dst_stat.st_size)
                        same_time = abs(src_stat.st_mtime - dst_stat.st_mtime) < 2
                        internal_ok = True
                        if os.path.isdir(internal_dir):
                            if not os.path.isdir(target_internal) or not os.listdir(target_internal):
                                internal_ok = False
                        if same_size and same_time and internal_ok:
                            need_copy = False
                    except Exception:
                        need_copy = True

                if need_copy:
                    if os.path.isdir(internal_dir):
                        # --onedir modu: _internal bağımlılık klasörünü de güvenli konuma senkronize et
                        if os.path.exists(target_internal):
                            shutil.rmtree(target_internal, ignore_errors=True)
                        shutil.copytree(internal_dir, target_internal)
                    shutil.copy2(sys.executable, secure_exe)

                return f'"{secure_exe}" --resume'
            except Exception as e:
                # Güvenlik ilkesi: Asla kullanıcı yazılabilir yola düşme (Fallback kaldırıldı)
                sys.stderr.write(f"[GÜVENLİK] Güvenli konuma kopyalanamadı ({e}). Görev oluşturulmayacak.\n")
                return ""
        else:
            # Geliştirici modunda (donmamış Python) yetki yükseltme ve yol manipülasyonunu önlemek için
            # otomatik zamanlanmış görev oluşturulmaz.
            sys.stderr.write("[BİLGİ] Geliştirici modunda (donmamış Python) otomatik zamanlanmış görev oluşturulmaz.\n")
            return ""

    @staticmethod
    def register_resume_task() -> bool:
        """
        Sistem yeniden başladığında uygulamanın en yüksek yetkiyle otomatik kaldığı yerden açılmasını sağlar.
        RunOnce yönetici yetkisi (--uac-admin) isteyen uygulamaları Windows oturum açılışında sessizce
        atladığı için en güvenilir yöntem schtasks ile onlogon en yüksek yetkili görev oluşturmaktır.
        Etkileşimli oturum garantisi için /it ve kullanıcı kimliği (/ru %USERNAME%) eklenir.
        Kabuk ve ağ servislerinin hazır olması için 30 saniye gecikme (/delay 0000:30) uygulanır.
        """
        try:
            cmd = SessionManager._build_resume_command()
            if not cmd:
                sys.stderr.write("[BİLGİ] Güvenli resume komutu üretilmedi; otomatik görev kaydı atlandı.\n")
                return False

            if len(cmd) > 260:
                sys.stderr.write(f"[UYARI] Zamanlanmış görev komutu 260 karakter sınırını aşıyor ({len(cmd)} karakter): {cmd}\n")

            schtasks_bin = get_system32_path("schtasks.exe")
            create_cmd = [
                schtasks_bin,
                "/create",
                "/tn", "FormatSonrasiResume",
                "/tr", cmd,
                "/sc", "onlogon",
                "/rl", "highest",
                "/delay", "0000:30",
                "/it",
                "/f",
            ]
            current_user = os.environ.get("USERNAME")
            if current_user:
                create_cmd.extend(["/ru", current_user])

            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            res = subprocess.run(
                create_cmd,
                capture_output=True,
                text=True,
                creationflags=creationflags,
                timeout=10,
            )
            if res.returncode == 0:
                return True
            else:
                sys.stderr.write(f"[UYARI] Zamanlanmış görev oluşturulamadı (Kod {res.returncode}): {res.stderr}\n")
                return False
        except Exception as e:
            sys.stderr.write(f"[UYARI] Zamanlanmış görev kaydı yapılamadı: {e}\n")
            return False

    @staticmethod
    def remove_resume_task():
        """Kurulum bitince, iptal edilince veya --resume işlenince zamanlanmış görevi, RunOnce kaydını ve kopyalanan ikiliyi siler."""
        try:
            creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            schtasks_bin = get_system32_path("schtasks.exe")
            subprocess.run(
                [schtasks_bin, "/delete", "/tn", "FormatSonrasiResume", "/f"],
                capture_output=True,
                creationflags=creationflags,
                timeout=10,
            )
        except Exception:
            pass
        SessionManager.remove_runonce_entry()
        try:
            program_data = os.environ.get("ProgramData", r"C:\ProgramData")
            bin_dir = os.path.join(program_data, "FormatSonrasi", "bin")

            # Açık koruma: Eğer şu anda bu bin klasöründen çalışıyorsak (resume süreci),
            # çalışan uygulamanın kendi ikili veya _internal dosyalarını silme
            running_from_bin = os.path.dirname(os.path.abspath(sys.executable)).lower() == os.path.abspath(bin_dir).lower()
            if not running_from_bin and os.path.isdir(bin_dir):
                secure_exe = os.path.join(bin_dir, "FormatSonrasiKurulum.exe")
                if os.path.exists(secure_exe):
                    os.remove(secure_exe)
                secure_internal = os.path.join(bin_dir, "_internal")
                if os.path.exists(secure_internal):
                    shutil.rmtree(secure_internal, ignore_errors=True)
        except Exception:
            pass

    @staticmethod
    def remove_runonce_entry():
        """Eski veya geçici RunOnce kaydını temizler."""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\RunOnce",
                0,
                winreg.KEY_SET_VALUE,
            )
            winreg.DeleteValue(key, "FormatSonrasiResume")
            winreg.CloseKey(key)
        except Exception:
            pass

    @staticmethod
    def _archive_session(session: Dict[str, Any]):
        """Oturum durumunu JSON dosyası olarak history dizinine arşivler."""
        try:
            history_dir = os.path.join(SESSION_DIR, "history")
            os.makedirs(history_dir, exist_ok=True)
            sess_id = session.get("session_id", f"session_{int(time.time())}")
            history_path = os.path.join(history_dir, f"{sess_id}.json")
            with open(history_path, "w", encoding="utf-8") as f:
                json.dump(session, f, ensure_ascii=False, indent=2)
        except Exception as e:
            sys.stderr.write(f"[UYARI] Oturum geçmişe arşivlenemedi: {e}\n")

    @staticmethod
    def finish_session():
        """Oturumu başarıyla kapatır, geçmişe arşivler ve durum dosyasını temizler."""
        with SessionManager._lock:
            session = SessionManager.get_current_session()
            if session:
                session["status"] = "completed"
                session["completed_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                SessionManager._archive_session(session)

            try:
                if os.path.exists(SESSION_FILE):
                    os.remove(SESSION_FILE)
                if os.path.exists(BACKUP_SESSION_FILE):
                    os.remove(BACKUP_SESSION_FILE)
            except Exception as e:
                sys.stderr.write(f"[UYARI] Oturum dosyası temizlenemedi: {e}\n")

        # schtasks alt süreç çağrısı kilitlenmeleri önlemek için RLock kilidinin dışında yapılır
        SessionManager.remove_resume_task()

    @staticmethod
    def clear_session():
        """Oturum dosyasını sıfırlar, iptal olarak arşivler ve devam görevlerini temizler."""
        with SessionManager._lock:
            session = SessionManager.get_current_session()
            if session:
                session["status"] = "cancelled"
                session["cancelled_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
                SessionManager._archive_session(session)

            try:
                if os.path.exists(SESSION_FILE):
                    os.remove(SESSION_FILE)
                if os.path.exists(BACKUP_SESSION_FILE):
                    os.remove(BACKUP_SESSION_FILE)
            except Exception as e:
                sys.stderr.write(f"[UYARI] Oturum dosyası sıfırlanamadı: {e}\n")

        # schtasks alt süreç çağrısı kilitlenmeleri önlemek için RLock kilidinin dışında yapılır
        SessionManager.remove_resume_task()

    @staticmethod
    def get_current_session() -> Optional[Dict[str, Any]]:
        """Mevcut oturum dosyasını okur (Bozuksa .bak yedeğinden kurtarır). Katalog dışı sahte ID'leri eler."""
        with SessionManager._lock:
            data = SessionManager._try_read_json(SESSION_FILE)
            if data is None and os.path.exists(BACKUP_SESSION_FILE):
                data = SessionManager._try_read_json(BACKUP_SESSION_FILE)
            if isinstance(data, dict):
                # Güvenlik filtresi: Yalnızca bilinen katalog uygulama kimliklerine izin ver
                valid_ids = {a["id"] for a in apps_data.APPLICATIONS}
                if "pending_app_ids" in data and isinstance(data["pending_app_ids"], list):
                    data["pending_app_ids"] = [aid for aid in data["pending_app_ids"] if isinstance(aid, str) and aid in valid_ids]
                if "failed_app_ids" in data and isinstance(data["failed_app_ids"], list):
                    data["failed_app_ids"] = [aid for aid in data["failed_app_ids"] if isinstance(aid, str) and aid in valid_ids]
                cur = data.get("current_app")
                if isinstance(cur, dict):
                    if cur.get("id") not in valid_ids:
                        data["current_app"] = None
                elif isinstance(cur, str):
                    if cur not in valid_ids:
                        data["current_app"] = None
                elif cur is not None:
                    data["current_app"] = None
            return data

    @staticmethod
    def _try_read_json(path: str) -> Optional[Dict[str, Any]]:
        if not os.path.exists(path):
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Oturum dosyası bozuk veya okunamadı ({path}): {e}")
            try:
                corrupt_path = path + ".corrupt"
                shutil.copy2(path, corrupt_path)
            except Exception as copy_err:
                logger.debug(f"Bozuk oturum dosyası kopyalanamadı: {copy_err}")
            return None

    @staticmethod
    def get_interrupted_session() -> Optional[Dict[str, Any]]:
        """Yarım kalmış bir oturum olup olmadığını kontrol eder."""
        with SessionManager._lock:
            session = SessionManager.get_current_session()
            if session and session.get("status") == "in_progress":
                pending = session.get("pending_app_ids", [])
                failed = session.get("failed_app_ids", [])
                if pending or failed or session.get("current_app"):
                    return session
            return None

    @staticmethod
    def _write_file_atomic(data: Dict[str, Any]):
        """Yarış durumlarını önlemek için atomik dosya yazma ve doğrulanmış .bak yedeği uygular."""
        with SessionManager._lock:
            temp_fd = None
            temp_path = None
            try:
                if os.path.exists(SESSION_FILE):
                    # Bozuk dosyanın sağlam yedeği ezmesini önlemek için geçerliliği doğrula
                    if SessionManager._try_read_json(SESSION_FILE) is not None:
                        try:
                            shutil.copyfile(SESSION_FILE, BACKUP_SESSION_FILE)
                        except Exception:
                            pass

                temp_fd, temp_path = tempfile.mkstemp(prefix="sess_", suffix=".tmp", dir=SESSION_DIR)
                with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                    temp_fd = None
                    json.dump(data, f, ensure_ascii=False, indent=2)

                os.replace(temp_path, SESSION_FILE)
            except Exception as e:
                sys.stderr.write(f"[UYARI] Oturum durumu diske yazılamadı: {e}\n")
                if temp_fd is not None:
                    try:
                        os.close(temp_fd)
                    except Exception:
                        pass
                if temp_path and os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except Exception:
                        pass
