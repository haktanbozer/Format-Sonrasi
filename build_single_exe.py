# -*- coding: utf-8 -*-
"""
Format Sonrası Kurulum Sihirbazı - Bağımsız Klasör (--onedir) ve Dağıtım Paketi Derleyici
Tek otoriter derleme betiği. --uac-admin ile açılışta doğrudan yönetici yetkisi ister.
Dağıtım bütünlüğü için SHA256SUMS.txt ve FormatSonrasiKurulum-v1.0.zip paketlerini üretir.
"""

import hashlib
import os
import subprocess
import sys
import shutil
import zipfile
from version import VERSION_DISPLAY


def _sha256_of_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _generate_sha256sums(target_dir: str, out_file: str):
    """Hedef klasördeki tüm dosyaların SHA-256 özetlerini SHA256SUMS.txt dosyasına yazar."""
    records = []
    base_dir = os.path.abspath(target_dir)
    for root, _, files in os.walk(base_dir):
        for fname in sorted(files):
            if fname in ("SHA256SUMS.txt", "FormatSonrasiKurulum.exe.sha256"):
                continue
            full_p = os.path.join(root, fname)
            rel_p = os.path.relpath(full_p, base_dir).replace("\\", "/")
            try:
                sha = _sha256_of_file(full_p)
                records.append(f"{sha}  {rel_p}")
            except Exception as e:
                raise RuntimeError(f"Dosya SHA-256 özeti hesaplanamadı ({full_p}): {e}") from e

    with open(out_file, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(records) + "\n")


def _create_release_zip(source_dir: str, zip_path: str):
    """FormatSonrasiKurulum klasörünü dağıtıma hazır ZIP arşivine paketler."""
    base_dir = os.path.abspath(source_dir)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, _, files in os.walk(base_dir):
            for fname in sorted(files):
                full_p = os.path.join(root, fname)
                arc_p = os.path.join("FormatSonrasiKurulum", os.path.relpath(full_p, base_dir))
                zf.write(full_p, arc_p)


def build():
    print("=" * 60)
    print("  Format Sonrası Kurulum Sihirbazı - Profesyonel EXE Derleme")
    print("=" * 60)

    for folder in ["build", "dist"]:
        if os.path.exists(folder):
            try:
                shutil.rmtree(folder)
            except Exception:
                pass

    cmd = [
        "pyinstaller",
        "--noconfirm",
        "--onedir",         # Hızlı bağımsız klasör dağıtımı (%TEMP% açma gecikmesi olmadan anında açılır)
        "--windowed",       # Konsol penceresini gizle
        "--uac-admin",      # Windows UAC yönetici yetkisi bildirimi zorunlu
        "--noupx",          # Antivirüs yanlış alarmlarını önlemek için UPX sıkıştırmasını kapat
        "--name", "FormatSonrasiKurulum",
        "--collect-all", "customtkinter",
        "main.py",
    ]

    print("PyInstaller derlemesi çalışıyor, lütfen bekleyin...")
    ret = subprocess.run(cmd)

    if ret.returncode == 0:
        dist_bundle = os.path.abspath("dist/FormatSonrasiKurulum")
        target_bundle = os.path.abspath("FormatSonrasiKurulum")
        copied = False
        try:
            if os.path.exists(target_bundle):
                shutil.rmtree(target_bundle)
            shutil.copytree(dist_bundle, target_bundle)
            copied = True
        except Exception as e:
            print(f"\n[UYARI] Ana dizine kopyalanamadı: {e}")

        final_bundle = target_bundle if copied else dist_bundle
        final_exe = os.path.join(final_bundle, "FormatSonrasiKurulum.exe")

        # 1. Klasör içi ve kök SHA256SUMS.txt
        sums_file = os.path.join(final_bundle, "SHA256SUMS.txt")
        _generate_sha256sums(final_bundle, sums_file)
        try:
            shutil.copy2(sums_file, "SHA256SUMS.txt")
        except Exception:
            pass

        # 2. Dağıtım ZIP Arşivi ve ZIP SHA-256 Özeti
        zip_pkg_name = f"FormatSonrasiKurulum-{VERSION_DISPLAY}.zip"
        zip_file = os.path.abspath(zip_pkg_name)
        _create_release_zip(final_bundle, zip_file)
        zip_sha = _sha256_of_file(zip_file)
        zip_sha_file = zip_file + ".sha256"
        with open(zip_sha_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"{zip_sha}  {zip_pkg_name}\n")

        # 3. Exe SHA-256 Özeti
        exe_sha = _sha256_of_file(final_exe)
        exe_sha_file = os.path.join(final_bundle, "FormatSonrasiKurulum.exe.sha256")
        with open(exe_sha_file, "w", encoding="utf-8", newline="\n") as f:
            f.write(f"{exe_sha}  FormatSonrasiKurulum.exe\n")
        try:
            shutil.copy2(exe_sha_file, "FormatSonrasiKurulum.exe.sha256")
        except Exception:
            pass

        # Derleme sonrası geçici klasör ve dosyaları temizle
        for folder in ["build", "dist"]:
            if os.path.exists(folder):
                try:
                    shutil.rmtree(folder)
                except Exception:
                    pass
        spec_file = "FormatSonrasiKurulum.spec"
        if os.path.isfile(spec_file):
            try:
                os.remove(spec_file)
            except Exception:
                pass

        print("\n" + "=" * 60)
        print("[OK] DERLEME VE PAKETLEME BAŞARILI!")
        print(f"Hedef Klasör   : {final_bundle}")
        print(f"Hedef EXE      : {final_exe} (SHA-256: {exe_sha})")
        print(f"Dağıtım ZIP    : {zip_file}")
        print(f"ZIP SHA-256    : {zip_sha}")
        print(f"Tüm Dosya Özeti: {sums_file}")
        print("=" * 60)
    else:
        print("\n[HATA] Derleme başarısız oldu!")
        sys.exit(ret.returncode)


if __name__ == "__main__":
    build()
