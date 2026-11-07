# -*- coding: utf-8 -*-
"""
Format Sonrası Kurulum Sihirbazı - Ana Başlatıcı
64-bit uyumlu tekil örnek (Named Mutex) koruması ve hata yakalama içerir.
"""

import ctypes
from ctypes import wintypes
import io
import os
import sys
import time
import traceback

# Windowed PyInstaller modunda sys.stdout ve sys.stderr None olabilir
if sys.stdout is None:
    sys.stdout = io.StringIO()
if sys.stderr is None:
    sys.stderr = io.StringIO()

# Mevcut dizini gerekiyorsa modül arama yoluna ekle (donmuş exe içinde gerekmez)
_script_dir = os.path.dirname(os.path.abspath(__file__))
if not getattr(sys, "frozen", False) and _script_dir not in sys.path:
    sys.path.insert(0, _script_dir)


def ensure_single_instance():
    """Aynı anda birden fazla uygulamanın açılmasını engeller (Named Mutex - Local kapsamı)."""
    if os.name != "nt":
        return None
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE

        # Local\ öneki oturumlar arası ve düşük yetkili DoS / mutex squatting riskini engeller
        mutex_name = "Local\\FormatSonrasiKurulum_SingleInstanceMutex"
        mutex = kernel32.CreateMutexW(None, True, mutex_name)
        last_error = ctypes.get_last_error()
        ERROR_ALREADY_EXISTS = 183

        if last_error == ERROR_ALREADY_EXISTS:
            try:
                import tkinter as tk
                import tkinter.messagebox as mb
                root = tk.Tk()
                root.withdraw()
                mb.showinfo("Uygulama Zaten Çalışıyor", "Format Sonrası Kurulum Sihirbazı zaten açık.")
                root.destroy()
            except Exception:
                pass
            sys.exit(0)
        return mutex
    except Exception as e:
        sys.stderr.write(f"[UYARI] Tekil örnek denetimi yapılamadı: {e}\n")
        return None


def main():
    t_start = time.perf_counter()
    _mutex = ensure_single_instance()
    try:
        from gui import MainWindow
        t_import = time.perf_counter()
        app = MainWindow()
        t_init = time.perf_counter()
        if "--perf" in sys.argv or os.environ.get("FSK_PERF"):
            perf_msg = f"[PERF] Import: {(t_import - t_start)*1000:.1f}ms | UI Init: {(t_init - t_import)*1000:.1f}ms | Toplam: {(t_init - t_start)*1000:.1f}ms\n"
            try:
                sys.stdout.write(perf_msg)
            except Exception:
                pass
            try:
                local_app_data = os.environ.get("LOCALAPPDATA", os.path.dirname(os.path.abspath(__file__)))
                perf_dir = os.path.join(local_app_data, "FormatSonrasi")
                os.makedirs(perf_dir, exist_ok=True)
                with open(os.path.join(perf_dir, "perf.log"), "a", encoding="utf-8") as pf:
                    pf.write(time.strftime("%Y-%m-%d %H:%M:%S ") + perf_msg)
            except Exception:
                pass
        app.mainloop()
    except Exception as e:
        err_msg = f"Uygulama başlatılırken kritik bir hata oluştu:\n{e}\n\n{traceback.format_exc()}"
        sys.stderr.write(err_msg + "\n")
        try:
            # Hata günlüğünü yerel AppData içine de kaydet
            log_dir = os.environ.get("LOCALAPPDATA", os.path.dirname(os.path.abspath(__file__)))
            crash_file = os.path.join(log_dir, "FormatSonrasi_Crash.log")
            with open(crash_file, "a", encoding="utf-8") as f:
                f.write(err_msg + "\n" + "=" * 50 + "\n")
        except Exception:
            pass

        try:
            import tkinter as tk
            import tkinter.messagebox as mb
            root = tk.Tk()
            root.withdraw()
            mb.showerror("Kritik Hata", f"Uygulama başlatılırken bir hata oluştu:\n{e}")
            root.destroy()
        except Exception:
            pass
        raise e
    finally:
        if _mutex and os.name == "nt":
            try:
                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.ReleaseMutex(_mutex)
                kernel32.CloseHandle(_mutex)
            except Exception:
                pass


if __name__ == "__main__":
    main()
