# -*- coding: utf-8 -*-
"""
Format Sonrası Kurulum Sihirbazı - Donanım ve Sistem Bilgisi Motoru
PowerShell Get-CimInstance çağrısıyla sistem, BIOS, CPU, GPU, RAM ve diskleri toplar.
Sanal makine tespiti, sahte/yer tutucu seri numarası elemesi ve veri maskeleme içerir.
"""

import json
import re
import subprocess
from typing import Dict, Any, List, Tuple, Optional

import os
import sys
from system_checks import get_system32_path

# Üreticilerin seri numarası girmediğinde kullandığı bilinen yer tutucular
PLACEHOLDER_SERIALS = {
    "to be filled by o.e.m.",
    "to be filled by oem",
    "default string",
    "system serial number",
    "chassis serial number",
    "none",
    "0",
    "123456789",
    "1234567",
    "not applicable",
    "n/a",
    "na",
    "empty",
    "unknown",
    "type2 - board serial number",
    "all",
    "serial number",
    "base board serial number",
    "system product name",
}

PS_HARDWARE_SCRIPT = """& {
  $ErrorActionPreference = 'SilentlyContinue'
  [Console]::OutputEncoding = [Text.Encoding]::UTF8
  $cs   = Get-CimInstance Win32_ComputerSystem  | Select-Object Manufacturer,Model,SystemSKUNumber,TotalPhysicalMemory
  $bios = Get-CimInstance Win32_BIOS            | Select-Object SerialNumber,SMBIOSBIOSVersion
  $prod = Get-CimInstance Win32_ComputerSystemProduct | Select-Object IdentifyingNumber
  $bb   = Get-CimInstance Win32_BaseBoard       | Select-Object SerialNumber,Manufacturer,Product
  $enc  = Get-CimInstance Win32_SystemEnclosure | Select-Object ChassisTypes
  $hasBat = [bool](@(Get-CimInstance Win32_Battery).Count -gt 0)
  $cpu  = @(Get-CimInstance Win32_Processor      | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors)
  $gpu  = @(Get-CimInstance Win32_VideoController| Select-Object Name,DriverVersion,PNPDeviceID)
  $ram  = @(Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity,Speed,SMBIOSMemoryType,Manufacturer)
  $disk = @(Get-PhysicalDisk                     | Select-Object FriendlyName,@{n='MediaType';e={"$($_.MediaType)"}},@{n='BusType';e={"$($_.BusType)"}},Size)
  if (-not $disk) {
    $disk = @(Get-CimInstance Win32_DiskDrive   | Select-Object Model,Size,@{n='MediaType';e={"$($_.MediaType)"}},@{n='BusType';e={"$($_.InterfaceType)"}})
  }
  $os   = Get-CimInstance Win32_OperatingSystem | Select-Object Caption,BuildNumber
  [pscustomobject]@{
    cs     = $cs
    bios   = $bios
    prod   = $prod
    bb     = $bb
    enc    = $enc
    hasBat = $hasBat
    cpu    = $cpu
    gpu    = $gpu
    ram    = $ram
    disk   = $disk
    os     = $os
  } | ConvertTo-Json -Depth 4 -Compress
}"""


def collect_hardware_raw(timeout_sec: int = 25) -> Dict[str, Any]:
    """
    PowerShell CIM oturumu üzerinden tek seferde ham donanım sözlüğünü çeker.
    Hata veya zaman aşımında boş sözlük döner; asla istisna fırlatmaz.
    """
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    ps_bin = get_system32_path("powershell.exe")
    try:
        r = subprocess.run(
            [ps_bin, "-NoProfile", "-NonInteractive", "-Command", PS_HARDWARE_SCRIPT],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_sec,
            creationflags=creationflags,
        )
        if r.returncode == 0 and r.stdout.strip():
            return json.loads(r.stdout.strip())
    except Exception:
        pass
    return {}


def is_valid_serial(serial: Optional[str]) -> bool:
    """Seri numarasının yer tutucu (placeholder) veya geçersiz olup olmadığını denetler."""
    if not serial or not isinstance(serial, str):
        return False
    s_clean = serial.strip().lower()
    if not s_clean or len(s_clean) < 2:
        return False
    if s_clean in PLACEHOLDER_SERIALS:
        return False
    # Tüm karakterleri aynı olan dizgileri (örn. 00000000 veya XXXXXXXX) filtrele
    if len(set(s_clean)) == 1:
        return False
    return True


def mask_serial_number(serial: str) -> str:
    """Kullanıcı arayüzünde seri numarasını varsayılan olarak maskeler."""
    if not serial or not isinstance(serial, str):
        return "Bilinmiyor"
    s = serial.strip()
    if s.startswith("Okunamadı") or s == "Bilinmiyor":
        return s
    if len(s) <= 4:
        return "****"
    return s[:4] + "*" * (len(s) - 4)


def detect_virtual_machine(manufacturer: str, model: str) -> Tuple[bool, str]:
    """
    Üretici ve model dizesinden sanal makine ortamını tespit eder.
    HypervisorPresent yerine model/üretici imzalarını kontrol eder (VBS/WSL açık fiziksel cihazları korur).
    """
    mfg = (manufacturer or "").lower()
    mdl = (model or "").lower()

    if "microsoft corporation" in mfg and ("virtual machine" in mdl or "hyper-v" in mdl):
        return True, "Hyper-V"
    if "vmware" in mfg or "vmware" in mdl:
        return True, "VMware"
    if "innotek" in mfg or "virtualbox" in mdl:
        return True, "VirtualBox"
    if "qemu" in mfg or "red hat" in mfg or "standard pc" in mdl or "kvm" in mdl:
        return True, "QEMU / KVM"
    if "parallels" in mfg or "parallels" in mdl:
        return True, "Parallels Desktop"
    if "xen" in mfg or "xen" in mdl:
        return True, "Xen"

    return False, ""


VIRTUAL_GPU_PATTERNS = (
    "parsec",
    "virtual display",
    "remote display",
    "displaylink",
    "indirect display",
    "spacedesk",
    "citrix",
    "rdpdd",
    "vda",
)


def determine_chassis_type(
    chassis_types: Any,
    is_vm: bool,
    vm_name: str,
    has_battery: bool = False,
) -> str:
    """Kasa tipini (Dizüstü, Masaüstü, Sanal vb.) belirler."""
    if is_vm:
        return f"Sanal Makine ({vm_name})" if vm_name else "Sanal Makine"

    types = chassis_types if isinstance(chassis_types, list) else [chassis_types]
    portable_codes = {8, 9, 10, 11, 14, 30, 31, 32}  # 12 (Docking Station) çıkarıldı
    desktop_codes = {3, 4, 5, 6, 7, 15, 16, 24, 35, 36}  # 35: Mini PC, 36: Stick PC eklendi
    aio_codes = {13}
    server_codes = {17, 23, 28}

    matched_type = None
    for code in types:
        try:
            c_int = int(code)
            if c_int in portable_codes:
                matched_type = "Dizüstü Bilgisayar (Laptop)"
                break
            elif c_int in desktop_codes:
                matched_type = "Masaüstü Bilgisayar (Desktop)"
                break
            elif c_int in aio_codes:
                matched_type = "Hepsi-Bir-Arada (All-in-One)"
                break
            elif c_int in server_codes:
                matched_type = "Sunucu (Server)"
                break
            elif c_int == 12:  # Docking Station
                matched_type = "Dizüstü Bilgisayar (Laptop)" if has_battery else "Masaüstü Bilgisayar (Desktop)"
                break
        except (ValueError, TypeError):
            continue

    if matched_type:
        return matched_type

    # Kasa kodu bulunamadıysa veya belirsizse pil varlığını kontrol et
    if has_battery:
        return "Dizüstü Bilgisayar (Laptop)"

    return "Standart Sistem"


def format_bytes_to_human(size_bytes: int) -> Tuple[str, str]:
    """Bayt değerini hem ondalık (GB/TB - üretici kutu boyutu) hem ikili (GiB - Windows dosya boyutu) döndürür."""
    if not size_bytes or size_bytes <= 0:
        return "0 GB", "0 GiB"
    gb_dec = size_bytes / (1000 ** 3)
    gib_bin = size_bytes / (1024 ** 3)

    if gb_dec >= 1000:
        tb_dec = gb_dec / 1000
        dec_str = f"{tb_dec:.1f} TB" if tb_dec < 10 else f"{round(tb_dec)} TB"
    else:
        dec_str = f"{round(gb_dec)} GB"

    bin_str = f"{gib_bin:.1f} GiB"
    return dec_str, bin_str


def parse_hardware(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ham PowerShell çıktısını temiz, doğrulanmış ve arayüze hazır sözlük yapısına dönüştürür.
    Eksik alanlar veya None değerler karşısında çökmeye karşı tam dayanıklıdır.
    """
    if not isinstance(raw, dict):
        raw = {}

    cs = raw.get("cs") or {}
    bios = raw.get("bios") or {}
    prod = raw.get("prod") or {}
    bb = raw.get("bb") or {}
    enc = raw.get("enc") or {}
    os_info = raw.get("os") or {}

    manufacturer = (cs.get("Manufacturer") or "Bilinmiyor").strip()
    model = (cs.get("Model") or "Bilinmiyor").strip()
    sku = (cs.get("SystemSKUNumber") or "").strip()

    # 1. Sanal Makine Tespiti
    is_vm, vm_name = detect_virtual_machine(manufacturer, model)

    # 2. Seri Numarası ve Yedek Kaynaklar
    candidate_serials = [
        bios.get("SerialNumber"),
        prod.get("IdentifyingNumber"),
        bb.get("SerialNumber"),
    ]
    actual_serial = ""
    for s in candidate_serials:
        if is_valid_serial(s):
            actual_serial = str(s).strip()
            break

    if actual_serial:
        display_serial = actual_serial
        masked_serial = mask_serial_number(actual_serial)
        has_valid_serial = True
    else:
        display_serial = "Okunamadı (üretici seri numarası girmemiş)"
        masked_serial = display_serial
        has_valid_serial = False

    # 3. Kasa Tipi ve BIOS
    chassis_types = enc.get("ChassisTypes")
    has_battery = bool(raw.get("hasBat"))
    chassis = determine_chassis_type(chassis_types, is_vm, vm_name, has_battery=has_battery)
    bios_version = (bios.get("SMBIOSBIOSVersion") or "Bilinmiyor").strip()

    # 4. İşlemci (CPU)
    cpu_raw = raw.get("cpu") or []
    cpu_list = cpu_raw if isinstance(cpu_raw, list) else [cpu_raw]
    cpus = []
    for c in cpu_list:
        if isinstance(c, dict):
            c_name = re.sub(r"\s+", " ", (c.get("Name") or "").strip())
            cores = c.get("NumberOfCores")
            threads = c.get("NumberOfLogicalProcessors")
            if c_name:
                detail = f"{c_name}"
                if cores and threads:
                    detail += f" ({cores} Çekirdek, {threads} İş Parçacığı)"
                cpus.append(detail)
    cpu_display = cpus[0] if cpus else "Bilinmiyor"

    # 5. Ekran Kartları (GPU) ve Sürücü Eksikliği Tespiti
    gpu_raw = raw.get("gpu") or []
    gpu_list = gpu_raw if isinstance(gpu_raw, list) else [gpu_raw]
    gpus = []
    has_missing_gpu_driver = False

    for g in gpu_list:
        if isinstance(g, dict):
            g_name = (g.get("Name") or "").strip()
            drv = (g.get("DriverVersion") or "").strip()
            if g_name:
                g_lower = g_name.lower()
                is_virtual = any(vp in g_lower for vp in VIRTUAL_GPU_PATTERNS)
                if is_virtual:
                    gpus.append({
                        "name": g_name,
                        "driver": drv or "Bilinmiyor",
                        "is_basic": False,
                        "is_virtual": True,
                        "warning": "",
                    })
                    continue

                is_basic = any(b in g_lower for b in ["basic display", "temel görüntü", "vga uyumlu"])
                if is_basic:
                    has_missing_gpu_driver = True
                    gpus.append({
                        "name": g_name,
                        "driver": drv or "Yok",
                        "is_basic": True,
                        "is_virtual": False,
                        "warning": "[UYARI] Sürücü eksik (Microsoft Temel Görüntü Bağdaştırıcısı devrede)",
                    })
                else:
                    gpus.append({
                        "name": g_name,
                        "driver": drv or "Bilinmiyor",
                        "is_basic": False,
                        "is_virtual": False,
                        "warning": "",
                    })

    # 6. Bellek (RAM)
    total_ram_bytes = cs.get("TotalPhysicalMemory") or 0
    ram_raw = raw.get("ram") or []
    ram_list = ram_raw if isinstance(ram_raw, list) else [ram_raw]
    ram_modules = []
    installed_ram_bytes = 0

    for m in ram_list:
        if isinstance(m, dict):
            cap = m.get("Capacity") or 0
            if isinstance(cap, (int, float)) and cap > 0:
                installed_ram_bytes += int(cap)
            speed = m.get("Speed") or 0
            m_type = m.get("SMBIOSMemoryType") or 0
            type_name = "DDR4" if m_type == 26 else ("DDR5" if m_type == 34 else ("DDR3" if m_type == 24 else "RAM"))
            if cap > 0:
                mod_gb = f"{round(cap / (1024 ** 3))} GB"
                speed_str = f"{speed} MHz" if speed else ""
                ram_modules.append(f"{mod_gb} {type_name} {speed_str}".strip())

    usable_gb_str = f"{round(total_ram_bytes / (1024 ** 3), 1)} GB" if isinstance(total_ram_bytes, (int, float)) and total_ram_bytes > 0 else ""
    if installed_ram_bytes > 0:
        installed_gb = round(installed_ram_bytes / (1024 ** 3))
        if usable_gb_str and usable_gb_str != f"{installed_gb} GB" and usable_gb_str != f"{float(installed_gb):.1f} GB":
            total_ram_gb = f"{installed_gb} GB (Kullanılabilir: {usable_gb_str})"
        else:
            total_ram_gb = f"{installed_gb} GB"
    elif usable_gb_str:
        total_ram_gb = usable_gb_str
    else:
        total_ram_gb = "Bilinmiyor"

    ram_detail = f"{total_ram_gb} ({len(ram_modules)} Modül: {', '.join(ram_modules)})" if ram_modules else total_ram_gb

    # 7. Depolama (Diskler)
    disk_raw = raw.get("disk") or []
    disk_list = disk_raw if isinstance(disk_raw, list) else [disk_raw]
    disks = []

    for d in disk_list:
        if isinstance(d, dict):
            name = (d.get("FriendlyName") or d.get("Model") or "Bilinmeyen Disk").strip()
            size_bytes = d.get("Size") or 0
            dec_size, bin_size = format_bytes_to_human(size_bytes)
            bus_type = str(d.get("BusType") or d.get("InterfaceType") or "").lower().strip()
            media_type = str(d.get("MediaType") or "").lower().strip()
            name_lower = name.lower()

            # 1. USB Önceliği (Harici sürücüler ve USB flash bellekler)
            # BusType 7 = USB
            if bus_type in ("usb", "7") or "usb" in bus_type or "usb" in name_lower:
                d_type = "Harici (USB)"
            elif bus_type in ("nvme", "17") or "nvme" in bus_type or "nvme" in name_lower:
                d_type = "NVMe SSD"
            elif media_type in ("ssd", "4") or "ssd" in media_type or "ssd" in name_lower:
                d_type = "SSD"
            elif media_type in ("hdd", "3") or "hdd" in media_type or "fixed hard disk" in media_type:
                d_type = "HDD"
            else:
                d_type = "Bilinmiyor"

            disks.append({
                "name": name,
                "type": d_type,
                "size_dec": dec_size,
                "size_bin": bin_size,
            })

    # 8. İşletim Sistemi
    os_caption = (os_info.get("Caption") or "Windows").strip()
    os_build = (os_info.get("BuildNumber") or "").strip()
    os_display = f"{os_caption} (Derleme {os_build})" if os_build else os_caption

    # 9. Panoya Kopyalama Metni Oluşturma
    lines = [
        "--- SISTEM VE DONANIM BILGISI ---",
        f"Uretici: {manufacturer}",
        f"Model: {model}",
    ]
    if sku:
        lines.append(f"SKU / Urun No: {sku}")
    lines.extend([
        f"Seri Numarasi: {masked_serial}",
        f"Kasa Tipi: {chassis}",
        f"BIOS Surumu: {bios_version}",
        f"Isletim Sistemi: {os_display}",
        f"Islemci: {cpu_display}",
    ])
    for idx, g in enumerate(gpus, 1):
        warn_txt = f" {g['warning']}" if g.get("warning") else ""
        virt_txt = " [Sanal Bagdastirici]" if g.get("is_virtual") else ""
        lines.append(f"Ekran Karti {idx}: {g['name']}{virt_txt} (Surucu: {g['driver']}){warn_txt}")
    lines.append(f"Bellek (RAM): {ram_detail}")
    for idx, d in enumerate(disks, 1):
        lines.append(f"Disk {idx}: {d['name']} [{d['type']}] ({d['size_dec']} / {d['size_bin']})")
    lines.append("---------------------------------")
    clipboard_text = "\n".join(lines)

    return {
        "manufacturer": manufacturer,
        "model": model,
        "sku": sku,
        "serial_number": actual_serial,
        "display_serial": display_serial,
        "masked_serial": masked_serial,
        "has_valid_serial": has_valid_serial,
        "is_vm": is_vm,
        "vm_name": vm_name,
        "chassis": chassis,
        "bios_version": bios_version,
        "os_display": os_display,
        "cpu": cpu_display,
        "gpus": gpus,
        "has_missing_gpu_driver": has_missing_gpu_driver,
        "ram_total": total_ram_gb,
        "ram_detail": ram_detail,
        "disks": disks,
        "clipboard_text": clipboard_text,
    }


def get_system_hardware_info(timeout_sec: int = 25) -> Dict[str, Any]:
    """Sistemin donanım bilgilerini toplar ve ayrıştırılmış olarak döner."""
    raw = collect_hardware_raw(timeout_sec=timeout_sec)
    return parse_hardware(raw)
