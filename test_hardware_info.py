# -*- coding: utf-8 -*-
"""
Format Sonrası Kurulum Sihirbazı - Donanım Bilgisi Birim Testleri
parse_hardware fonksiyonunu sanal makineler, yer tutucu seriler, çift GPU ve bozuk verilerle test eder.
Python standart kütüphanesi unittest ile çalışır (pytest gerektirmez).
"""

import unittest
import re
import os
import sys
import shutil
import time
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apps_data
from hardware_info import (
    parse_hardware,
    is_valid_serial,
    mask_serial_number,
    determine_chassis_type,
)
from manufacturer_support import (
    resolve_support_info,
    is_url_safe,
)


class TestHardwareInfo(unittest.TestCase):

    def test_virtual_machine_detection_hyperv(self):
        """Hyper-V sanal makine tespiti (Microsoft Corporation / Virtual Machine)."""
        raw = {
            "cs": {"Manufacturer": "Microsoft Corporation", "Model": "Virtual Machine"},
            "bios": {"SerialNumber": "7829-1234-5678-9012-3456-7890-12"},
        }
        parsed = parse_hardware(raw)
        self.assertTrue(parsed["is_vm"])
        self.assertEqual(parsed["vm_name"], "Hyper-V")
        self.assertIn("Sanal Makine (Hyper-V)", parsed["chassis"])

    def test_virtual_machine_detection_vmware(self):
        """VMware ortam tespiti."""
        raw = {
            "cs": {"Manufacturer": "VMware, Inc.", "Model": "VMware Virtual Platform"},
            "bios": {"SerialNumber": "VMware-42 12 34 56"},
        }
        parsed = parse_hardware(raw)
        self.assertTrue(parsed["is_vm"])
        self.assertEqual(parsed["vm_name"], "VMware")

    def test_virtual_machine_detection_virtualbox(self):
        """VirtualBox ortam tespiti."""
        raw = {
            "cs": {"Manufacturer": "innotek GmbH", "Model": "VirtualBox"},
            "bios": {"SerialNumber": "0"},
        }
        parsed = parse_hardware(raw)
        self.assertTrue(parsed["is_vm"])
        self.assertEqual(parsed["vm_name"], "VirtualBox")

    def test_virtual_machine_detection_qemu(self):
        """QEMU / KVM ortam tespiti."""
        raw = {
            "cs": {"Manufacturer": "QEMU", "Model": "Standard PC (i440FX + PIIX, 1996)"},
        }
        parsed = parse_hardware(raw)
        self.assertTrue(parsed["is_vm"])
        self.assertEqual(parsed["vm_name"], "QEMU / KVM")

    def test_placeholder_serials_all_rejected(self):
        """Tüm bilinen sahte ve yer tutucu serilerin elendiğini doğrular."""
        placeholders = [
            "To Be Filled By O.E.M.",
            "to be filled by oem",
            "Default string",
            "System Serial Number",
            "Chassis Serial Number",
            "None",
            "0",
            "123456789",
            "Not Applicable",
            "N/A",
            "Empty",
            "Unknown",
            "00000000",
            "XXXXXXXX",
            "  ",
            "",
            None,
        ]
        for p in placeholders:
            self.assertFalse(is_valid_serial(p), f"Yer tutucu seri geçerli kabul edildi: {p}")

    def test_serial_fallback_to_baseboard(self):
        """BIOS serisi yer tutucu olduğunda anakart serisine güvenli düşüşü doğrular."""
        raw = {
            "cs": {"Manufacturer": "Gigabyte Technology Co., Ltd.", "Model": "B650 GAMING X AX"},
            "bios": {"SerialNumber": "Default string"},
            "prod": {"IdentifyingNumber": "To Be Filled By O.E.M."},
            "bb": {"SerialNumber": "SN2345890123"},
        }
        parsed = parse_hardware(raw)
        self.assertTrue(parsed["has_valid_serial"])
        self.assertEqual(parsed["serial_number"], "SN2345890123")
        self.assertEqual(parsed["masked_serial"], "SN23********")

    def test_serial_all_missing_returns_explanatory_text(self):
        """Hiçbir serinin bulunamadığı durumda açıklayıcı metin döndüğünü doğrular."""
        raw = {
            "cs": {"Manufacturer": "Custom Build", "Model": "Z790 PC"},
            "bios": {"SerialNumber": "To Be Filled By O.E.M."},
            "prod": {"IdentifyingNumber": "None"},
            "bb": {"SerialNumber": "Default string"},
        }
        parsed = parse_hardware(raw)
        self.assertFalse(parsed["has_valid_serial"])
        self.assertEqual(parsed["serial_number"], "")
        self.assertEqual(parsed["display_serial"], "Okunamadı (üretici seri numarası girmemiş)")
        self.assertEqual(parsed["masked_serial"], "Okunamadı (üretici seri numarası girmemiş)")

    def test_mask_serial_number_lengths(self):
        """Farklı uzunluktaki seri numaralarının maskeleme mantığını doğrular."""
        self.assertEqual(mask_serial_number(""), "Bilinmiyor")
        self.assertEqual(mask_serial_number("A"), "****")
        self.assertEqual(mask_serial_number("ABCD"), "****")
        self.assertEqual(mask_serial_number("ABCDE"), "ABCD*")
        self.assertEqual(mask_serial_number("5CD33495LR"), "5CD3******")
        self.assertEqual(mask_serial_number("Okunamadı (üretici seri numarası girmemiş)"), "Okunamadı (üretici seri numarası girmemiş)")

    def test_dual_gpu_and_missing_driver_warning(self):
        """Çift GPU (Intel + NVIDIA) ve Microsoft Temel Görüntü Bağdaştırıcısı durumunu doğrular."""
        raw = {
            "gpu": [
                {"Name": "Intel(R) UHD Graphics 770", "DriverVersion": "31.0.101.4500"},
                {"Name": "Microsoft Basic Display Adapter", "DriverVersion": "10.0.22621.1"},
            ]
        }
        parsed = parse_hardware(raw)
        self.assertEqual(len(parsed["gpus"]), 2)
        self.assertTrue(parsed["has_missing_gpu_driver"])
        self.assertFalse(parsed["gpus"][0]["is_basic"])
        self.assertTrue(parsed["gpus"][1]["is_basic"])
        self.assertIn("[UYARI]", parsed["gpus"][1]["warning"])
        self.assertIn("Microsoft Temel Görüntü Bağdaştırıcısı", parsed["gpus"][1]["warning"])
        # Emojisiz kurumsal tasarım kuralı
        self.assertNotIn("⚠️", parsed["gpus"][1]["warning"])

    def test_disk_types_and_sizes(self):
        """Disk tiplerinin (NVMe SSD, SATA SSD, HDD, USB) ve boyutlarının doğrulanması."""
        raw = {
            "disk": [
                {"FriendlyName": "Samsung 980 PRO 1TB", "BusType": "NVMe", "MediaType": "SSD", "Size": 1000204886016},
                {"FriendlyName": "Crucial MX500", "BusType": "SATA", "MediaType": "SSD", "Size": 500107862016},
                {"FriendlyName": "Seagate Barracuda", "BusType": "SATA", "MediaType": "HDD", "Size": 2000398934016},
                {"FriendlyName": "SanDisk Ultra USB", "BusType": "USB", "MediaType": "Unspecified", "Size": 32000000000},
            ]
        }
        parsed = parse_hardware(raw)
        disks = parsed["disks"]
        self.assertEqual(len(disks), 4)
        self.assertEqual(disks[0]["type"], "NVMe SSD")
        self.assertIn("TB", disks[0]["size_dec"])
        self.assertEqual(disks[1]["type"], "SSD")
        self.assertEqual(disks[2]["type"], "HDD")
        self.assertEqual(disks[3]["type"], "Harici (USB)")

    def test_empty_or_corrupt_data_does_not_crash(self):
        """Tamamen boş, None veya eksik anahtarlı ham verilerin çökmeden varsayılan değerleri ürettiğini doğrular."""
        self.assertEqual(parse_hardware({})["manufacturer"], "Bilinmiyor")
        self.assertEqual(parse_hardware(None)["model"], "Bilinmiyor")
        self.assertEqual(parse_hardware({"cpu": None, "gpu": None, "ram": None, "disk": None})["cpu"], "Bilinmiyor")

    def test_single_item_as_dict_instead_of_list(self):
        """PowerShell'in tek elemanlı dizileri tek nesne olarak döndürdüğü durumun ele alınması."""
        raw = {
            "cpu": {"Name": "AMD Ryzen 7 7800X3D", "NumberOfCores": 8, "NumberOfLogicalProcessors": 16},
            "gpu": {"Name": "NVIDIA GeForce RTX 4080", "DriverVersion": "551.86"},
            "ram": {"Capacity": 34359738368, "Speed": 6000, "SMBIOSMemoryType": 34},
            "disk": {"FriendlyName": "WD_BLACK SN850X 2TB", "BusType": "NVMe", "Size": 2000000000000},
        }
        parsed = parse_hardware(raw)
        self.assertIn("Ryzen 7 7800X3D", parsed["cpu"])
        self.assertEqual(len(parsed["gpus"]), 1)
        self.assertEqual(parsed["gpus"][0]["name"], "NVIDIA GeForce RTX 4080")
        self.assertEqual(len(parsed["disks"]), 1)
        self.assertEqual(parsed["disks"][0]["type"], "NVMe SSD")

    def test_manufacturer_support_dell_valid_service_tag(self):
        """Dell geçerli servis etiketinde doğrudan URL üretildiğini doğrular."""
        res = resolve_support_info("Dell Inc.", "Latitude 5420", serial_number="7ABC123")
        self.assertEqual(res["brand"], "Dell")
        self.assertTrue(res["can_open"])
        self.assertIn("servicetag/7ABC123/overview", res["url"])
        self.assertEqual(res["clipboard_text"], "7ABC123")
        self.assertIn("Windows Pano Geçmişi", res["status_message"])

    def test_manufacturer_support_dell_invalid_service_tag(self):
        """Dell geçersiz etiket veya yer tutucuda ana portala düştüğünü doğrular."""
        res = resolve_support_info("Dell Inc.", "OptiPlex 7090", serial_number="INVALID_TAG_TOO_LONG")
        self.assertEqual(res["brand"], "Dell")
        self.assertEqual(res["url"], "https://www.dell.com/support/home/tr-tr")

    def test_manufacturer_support_lenovo_and_hp(self):
        """Lenovo ve HP markalarının doğru portala yönlendiğini doğrular."""
        lenovo = resolve_support_info("Lenovo", "ThinkPad T14 Gen 3", serial_number="PF3XXXX")
        self.assertEqual(lenovo["brand"], "Lenovo")
        self.assertEqual(lenovo["url"], "https://pcsupport.lenovo.com/tr/tr")

        hp = resolve_support_info("HP", "HP EliteBook 840 G8", serial_number="5CD12345")
        self.assertEqual(hp["brand"], "HP")
        self.assertEqual(hp["url"], "https://support.hp.com/tr-tr/drivers")

    def test_manufacturer_support_turkish_brands(self):
        """Monster ve Casper/Excalibur tespiti ve portal doğrulaması."""
        monster = resolve_support_info("MONSTER", "ABRA A5 V17.2", serial_number="123")
        self.assertEqual(monster["brand"], "Monster Notebook")
        self.assertIn("monsternotebook.com.tr", monster["url"])

        casper = resolve_support_info("Casper Bilgisayar Sistemleri A.S.", "Excalibur G900", serial_number="456")
        self.assertEqual(casper["brand"], "Casper / Excalibur")
        self.assertIn("casper.com.tr", casper["url"])

    def test_manufacturer_support_virtual_machine_no_url(self):
        """Sanal makinelerde sürücü URL'si sunulmadığını doğrular."""
        vm = resolve_support_info("Microsoft Corporation", "Virtual Machine", is_vm=True)
        self.assertFalse(vm["can_open"])
        self.assertIsNone(vm["url"])
        self.assertIn("Sanal makine ortamında", vm["status_message"])

    def test_manufacturer_support_unknown_brand_fallback_to_google(self):
        """Tanınmayan marka veya toplama anakartlarda Google arama yedeğine düşüş."""
        custom = resolve_support_info("Colorful", "CVN B760M", serial_number="")
        self.assertTrue(custom["is_fallback"])
        self.assertIn("google.com/search?q=", custom["url"])
        self.assertTrue(custom["can_open"])

    def test_url_safety_validation(self):
        """Yalnızca izin verilen HTTPS alan adlarının güvenli kabul edildiğini doğrular."""
        self.assertTrue(is_url_safe("https://www.dell.com/support/home/tr-tr"))
        self.assertTrue(is_url_safe("https://support.hp.com/tr-tr/drivers"))
        self.assertTrue(is_url_safe("https://www.google.com/search?q=test"))
        # Güvensiz URL'ler
        self.assertFalse(is_url_safe("http://www.dell.com/support"))  # HTTP yasak
        self.assertFalse(is_url_safe("https://malicious-site.com/driver"))  # İzin listesinde yok
        self.assertFalse(is_url_safe("javascript:alert(1)"))
        self.assertFalse(is_url_safe(""))
        self.assertFalse(is_url_safe(None))
        # Enjeksiyon ve biçimlendirme saldırıları
        self.assertFalse(is_url_safe("https://dell.com\\evil.com"))
        self.assertFalse(is_url_safe("https://dell.com@evil.com"))
        self.assertFalse(is_url_safe("https://dell.com /test"))

    def test_usb_disk_priority_over_ssd(self):
        """Harici USB SSD veya USB disklerin SSD yerine USB olarak önceliklendirildiğini doğrular."""
        raw = {
            "disk": [
                {"FriendlyName": "Samsung Portable SSD T7", "BusType": "USB", "MediaType": "SSD", "Size": 1000000000000},
                {"FriendlyName": "Numeric BusType USB Drive", "BusType": "7", "MediaType": "4", "Size": 500000000000},
                {"FriendlyName": "Internal NVMe Drive", "BusType": "17", "MediaType": "4", "Size": 1000000000000},
            ]
        }
        parsed = parse_hardware(raw)
        disks = parsed["disks"]
        self.assertEqual(disks[0]["type"], "Harici (USB)")
        self.assertEqual(disks[1]["type"], "Harici (USB)")
        self.assertEqual(disks[2]["type"], "NVMe SSD")

    def test_chassis_type_extended_codes_and_battery(self):
        """Kasa tipi SMBIOS kodları (12, 35, 36) ve pil varlığı etkisini doğrular."""
        # Kod 12 (Docking Station): pille laptop, pilsiz masaüstü
        self.assertEqual(determine_chassis_type([12], False, "", has_battery=True), "Dizüstü Bilgisayar (Laptop)")
        self.assertEqual(determine_chassis_type([12], False, "", has_battery=False), "Masaüstü Bilgisayar (Desktop)")
        # Kod 35 (Mini PC) ve 36 (Stick PC): masaüstü
        self.assertEqual(determine_chassis_type([35], False, ""), "Masaüstü Bilgisayar (Desktop)")
        self.assertEqual(determine_chassis_type([36], False, ""), "Masaüstü Bilgisayar (Desktop)")
        # Bilinmeyen kod ama pil var -> Laptop
        self.assertEqual(determine_chassis_type([99], False, "", has_battery=True), "Dizüstü Bilgisayar (Laptop)")

    def test_ram_installed_vs_usable_display(self):
        """Fiziksel takılı RAM ile Windows kullanılabilir RAM farkının doğru gösterildiğini doğrular."""
        raw = {
            "cs": {"TotalPhysicalMemory": 16321044480},  # ~15.2 GB kullanılabilir
            "ram": [
                {"Capacity": 8589934592, "Speed": 3200, "SMBIOSMemoryType": 26},  # 8 GB DDR4
                {"Capacity": 8589934592, "Speed": 3200, "SMBIOSMemoryType": 26},  # 8 GB DDR4
            ]
        }
        parsed = parse_hardware(raw)
        self.assertIn("16 GB", parsed["ram_total"])
        self.assertIn("Kullanılabilir: 15.2 GB", parsed["ram_total"])
        self.assertIn("2 Modül: 8 GB DDR4 3200 MHz, 8 GB DDR4 3200 MHz", parsed["ram_detail"])

    def test_masked_serial_in_clipboard_text(self):
        """Panoya kopyalanan özet metinde seri numarasının açık değil, maskeli olduğunu doğrular."""
        raw = {
            "cs": {"Manufacturer": "ASUS", "Model": "ROG Zephyrus G14"},
            "bios": {"SerialNumber": "SN1234567890"},
        }
        parsed = parse_hardware(raw)
        self.assertEqual(parsed["masked_serial"], "SN12********")
        self.assertIn("Seri Numarasi: SN12********", parsed["clipboard_text"])
        self.assertNotIn("SN1234567890", parsed["clipboard_text"])

    def test_virtual_gpu_filtering(self):
        """Sanal ekran bağdaştırıcılarının (Parsec, DisplayLink vb.) gerçek GPU sürücüsü eksik uyarısı vermediğini doğrular."""
        raw = {
            "gpu": [
                {"Name": "Parsec Virtual Display Adapter", "DriverVersion": "0.45.0.0"},
                {"Name": "DisplayLink USB Device", "DriverVersion": "10.2.3.0"},
                {"Name": "NVIDIA GeForce RTX 4070", "DriverVersion": "551.86"},
            ]
        }
        parsed = parse_hardware(raw)
        self.assertFalse(parsed["has_missing_gpu_driver"])
        self.assertTrue(parsed["gpus"][0]["is_virtual"])
        self.assertTrue(parsed["gpus"][1]["is_virtual"])
        self.assertFalse(parsed["gpus"][2]["is_virtual"])

    def test_brand_word_boundary_and_collision_prevention(self):
        """Kısa marka kısaltmalarının (HP, MSI) başka kelimeler içinde sahte eşleşme yapmadığını doğrular."""
        # 'Insyde' içinde 'hp' geçmez
        insyde = resolve_support_info("Insyde Software Corp.", "InsydeH2O BIOS", serial_number="")
        self.assertNotEqual(insyde["brand"], "HP")
        # 'Shop PC' içinde 'hp' geçmez
        shop = resolve_support_info("Shop Tech", "Workstation 1", serial_number="")
        self.assertNotEqual(shop["brand"], "HP")
        # Gerçek HP
        hp = resolve_support_info("HP", "Victus 16", serial_number="")
        self.assertEqual(hp["brand"], "HP")
        # Asus TUF model ismi üzerinden eşleşme
        tuf = resolve_support_info("System manufacturer", "TUF Gaming A15", serial_number="")
        self.assertEqual(tuf["brand"], "Asus")

    def test_unknown_and_placeholder_suppression(self):
        """Üretici ve model bilgisi tamamen yer tutucu olduğunda dış bağlantı üretilmediğini doğrular."""
        res = resolve_support_info("System manufacturer", "System Product Name", serial_number="")
        self.assertFalse(res["can_open"])
        self.assertIsNone(res["url"])
        self.assertEqual(res["status_message"], "Model bilgisi okunamadı.")
        self.assertEqual(res["brand"], "Bilinmiyor")

    def test_catalog_integrity(self):
        """Uygulama sıklet (weight) kademeleri ve Store kimlik kaynak alanını doğrular."""
        tier = lambda mb: 1 if mb < 15 else 2 if mb <= 150 else 3 if mb <= 600 else 4
        for a in apps_data.APPLICATIONS:
            self.assertEqual(a["weight"], tier(a["size_mb"]), f"{a['id']} weight tutarsız (boyut: {a['size_mb']}MB, weight: {a['weight']})")
            if re.fullmatch(r"[0-9A-Z]{12}", a["winget_id"]):
                self.assertEqual(a.get("source"), "msstore", f"{a['id']} MS Store source alanı eksik")

    def test_hyperv_vm_not_shadowed_by_surface(self):
        """Hyper-V sanal makinenin Microsoft Corporation üreticisi yüzünden Surface olarak algılanmadığını doğrular."""
        raw = {
            "cs": {"Manufacturer": "Microsoft Corporation", "Model": "Virtual Machine"},
            "bios": {"SerialNumber": "0000-0000-0000-0000"},
        }
        parsed = parse_hardware(raw)
        self.assertTrue(parsed["is_vm"])
        self.assertEqual(parsed["vm_name"], "Hyper-V")
        support = resolve_support_info(
            manufacturer=parsed["manufacturer"],
            model=parsed["model"],
            serial_number=parsed["serial_number"],
            is_vm=parsed["is_vm"]
        )
        self.assertEqual(support["brand"], "Sanal Makine")
        self.assertFalse(support["can_open"])

    def test_surface_and_new_manufacturers_resolution(self):
        """Surface (yalnızca Surface modellerinde), Samsung, Huawei ve LG üretici çözümlemesini doğrular."""
        # Gerçek Surface
        surf = resolve_support_info("Microsoft Corporation", "Surface Pro 9", serial_number="", is_vm=False)
        self.assertEqual(surf["brand"], "Microsoft Surface")
        self.assertTrue(surf["can_open"])
        self.assertIn("surface", surf["url"])

        # Surface olmayan Microsoft donanımı Surface ile eşleşmemeli
        non_surf = resolve_support_info("Microsoft Corporation", "Virtual Machine", serial_number="", is_vm=False)
        self.assertNotEqual(non_surf["brand"], "Microsoft Surface")

        # Samsung
        samsung = resolve_support_info("Samsung Electronics", "Galaxy Book 3 Pro", serial_number="", is_vm=False)
        self.assertEqual(samsung["brand"], "Samsung")

        # Huawei
        huawei = resolve_support_info("Huawei", "MateBook D16", serial_number="", is_vm=False)
        self.assertEqual(huawei["brand"], "Huawei")

        # LG
        lg = resolve_support_info("LG Electronics", "LG Gram 17", serial_number="", is_vm=False)
        self.assertEqual(lg["brand"], "LG Electronics")

    def test_special_install_types_are_consistent(self):
        """Özel kurulum türlerinin (direct_exe, filezilla_clean, dism_feature) şema ve alan tutarlılığını doğrular."""
        for a in apps_data.APPLICATIONS:
            wid, t = a["winget_id"], a.get("install_type", "winget")
            if wid.startswith("direct."):
                self.assertEqual(t, "direct_exe", a["id"])
                self.assertTrue(a.get("download_url", "").startswith("https://"), a["id"])
                self.assertTrue(a.get("sha256") or a.get("publisher"), a["id"])
            elif wid.startswith("custom."):
                self.assertEqual(t, "filezilla_clean", a["id"])
            elif wid.startswith("dism."):
                self.assertEqual(t, "dism_feature", a["id"])
                self.assertTrue(a.get("feature_name"), a["id"])
            else:
                self.assertEqual(t, "winget", a["id"])

    def test_required_verify_rules_present(self):
        """Kritik 17 uygulamanın kurulum sonrası doğrulama (verify) kurallarının eksiksiz olduğunu denetler."""
        required = {
            "git", "python", "nodejs_lts", "dbeaver", "golang", "android_studio",
            "brave", "firefox", "opera", "opera_gx", "vivaldi", "whatsapp",
            "vs_community_2019", "vs_community_2017", "filezilla",
            "dotnet_framework_35", "rustdesk"
        }
        by_id = {a["id"]: a for a in apps_data.APPLICATIONS}
        for i in required:
            self.assertIn("verify", by_id[i], f"{i} verify kuralı eksik")

    def test_pinned_versions_match_urls(self):
        """Sabitlenmiş sürüm (pinned_version) tanımlı uygulamalarda sürümün indirme bağlantısı ile uyumunu doğrular."""
        for a in apps_data.APPLICATIONS:
            if "pinned_version" in a and "download_url" in a:
                self.assertIn(
                    a["pinned_version"],
                    a["download_url"],
                    f"{a['id']} pinned_version ({a['pinned_version']}) download_url içinde bulunamadı"
                )

    def test_baslat_bat_launcher_exit_codes(self):
        """baslat.bat dosyasının py -3 için hem 9009 hem 103 kodlarını yakalayıp yedeğe yönlendirdiğini doğrular."""
        bat = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baslat.bat")
        with open(bat, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        self.assertIn('if "%APP_EXIT%"=="9009" goto :try_other_py', content)
        self.assertIn('if "%APP_EXIT%"=="103" goto :try_other_py', content)

    def test_tweaks_rollback_security_whitelist(self):
        """tweaks.py geri alma beyaz listesinin yetki yükseltme ve sahte kayıtları engellediğini doğrular."""
        import winreg
        from tweaks import _entry_allowed, _location_allowed, _ALLOWED_REVERT

        # 1. Meşru telemetri ayarı onaylanmalı
        ok = _entry_allowed(
            "disable_telemetry", "HKLM",
            r"software\policies\microsoft\windows\datacollection",
            "allowtelemetry", winreg.REG_DWORD, 0
        )
        self.assertTrue(ok)

        # 2. Sahte / saldırgan kayıt defteri konumu hem konum hem girdi kontrolünde reddedilmeli
        evil_loc = _location_allowed(
            "disable_telemetry", "HKLM",
            r"software\microsoft\windows\currentversion\run",
            "SecurityUpdater"
        )
        self.assertFalse(evil_loc)

        evil_entry = _entry_allowed(
            "disable_telemetry", "HKLM",
            r"software\microsoft\windows\currentversion\run",
            "SecurityUpdater", winreg.REG_SZ, "malware.exe"
        )
        self.assertFalse(evil_entry)

        # 3. Tip uyumsuzluğu (DWORD yerine metin) reddedilmeli
        bad_type = _entry_allowed(
            "disable_telemetry", "HKLM",
            r"software\policies\microsoft\windows\datacollection",
            "allowtelemetry", winreg.REG_DWORD, "not_an_int"
        )
        self.assertFalse(bad_type)

        # 4. Tüm meşru 12 kayıt defteri üçlüsü (10 ayar) beyaz listede tanımlı ve onaylı olmalı
        total_entries = sum(len(entries) for entries in _ALLOWED_REVERT.values())
        self.assertEqual(total_entries, 12, f"Beklenen 12 meşru kayıt defteri girdisi, bulunan: {total_entries}")
        for tweak_id, triples in _ALLOWED_REVERT.items():
            for root_name, key_path, val_name in triples:
                self.assertTrue(
                    _location_allowed(tweak_id, root_name, key_path, val_name),
                    f"{tweak_id} -> {root_name}\\{key_path}\\{val_name} doğrulanamadı"
                )

    def test_tweaks_rollback_rejects_unauthorized_delete_and_write(self):
        """revert_all_tweaks fonksiyonunun izinsiz silme ve yazma durumunda işlemi reddedip False raporladığını doğrular."""
        import tweaks
        from unittest.mock import patch

        # Sahte saldırgan yedeği: meşru olmayan HKLM Run anahtarını silmeye çalışan bir kayıt
        fake_malicious_backup = {
            "disable_telemetry": {
                r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run\SecurityUpdater": {
                    "root": "HKLM",
                    "key_path": r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                    "value_name": "SecurityUpdater",
                    "existed": False,
                    "data": None,
                    "type": None,
                }
            }
        }

        deleted_values = []
        def fake_delete(root, key, val):
            deleted_values.append((key, val))

        with patch.object(tweaks, "_load_backup", return_value=fake_malicious_backup), \
             patch.object(tweaks, "_safe_delete_reg_value", side_effect=fake_delete), \
             patch.object(tweaks, "_save_backup") as mock_save:
            results = tweaks.revert_all_tweaks()
            # Silme çağrısı asla yapılmamalı
            self.assertEqual(len(deleted_values), 0, "İzinsiz kayıt defteri silme çağrısı yapıldı!")
            # Rapor False dönmeli
            self.assertEqual(len(results), 1)
            tweak_id, success, msg = results[0]
            self.assertEqual(tweak_id, "disable_telemetry")
            self.assertFalse(success, "İzinsiz silme başarılı raporlanmamalı!")
            self.assertIn("reddedildi", msg.lower())

    def test_safe_owners_and_secure_dir_helpers(self):
        """system_checks modülündeki SAFE_OWNERS ve ensure_secure_dir yardımcısını doğrular."""
        from system_checks import SAFE_OWNERS, ensure_secure_dir
        self.assertIn("S-1-5-32-544", SAFE_OWNERS)  # Administrators
        self.assertIn("S-1-5-18", SAFE_OWNERS)      # SYSTEM

    def test_winget_source_whitelist(self):
        """installer_core._install_winget metodunun bilinmeyen kaynakları reddettiğini doğrular."""
        from installer_core import InstallationWorker
        worker = InstallationWorker([], lambda s: None, lambda a, b, c, d: None, lambda a, b, c: None, lambda d: None)
        ok, msg, _, _ = worker._install_winget(1, 1, {"name": "Test", "winget_id": "test.id", "source": "evil_source"})
        self.assertFalse(ok)
        self.assertIn("Güvenlik Engeli", msg)

    def test_strict_https_redirect_handler(self):
        """StrictHTTPSRedirectHandler'ın HTTP downgrade ve izinsiz alan adlarını engellediğini doğrular."""
        import urllib.request
        from installer_core import StrictHTTPSRedirectHandler

        handler = StrictHTTPSRedirectHandler()
        dummy_req = urllib.request.Request("https://github.com/release.exe")

        # 1. HTTP downgrade engellenmeli
        with self.assertRaises(ValueError):
            handler.redirect_request(dummy_req, None, 302, "Found", {}, "http://github.com/release.exe")

        # 2. Beyaz listede olmayan alan adı engellenmeli
        with self.assertRaises(ValueError):
            handler.redirect_request(dummy_req, None, 302, "Found", {}, "https://evil-site.com/malware.exe")

        # 3. İzin verilen alan adı onaylanmalı
        req = handler.redirect_request(dummy_req, None, 302, "Found", {}, "https://objects.githubusercontent.com/file.exe")
        self.assertIsNotNone(req)
        self.assertEqual(req.get_full_url(), "https://objects.githubusercontent.com/file.exe")

    def test_installer_requires_hash_or_publisher(self):
        """Doğrudan indirilen programların ne sha256 ne de publisher bilgisi yoksa reddedildiğini doğrular."""
        from installer_core import InstallationWorker
        worker = InstallationWorker([], lambda s: None, lambda a, b, c, d: None, lambda a, b, c: None, lambda d: None)
        app = {
            "name": "GuvenliksizUygulama",
            "install_type": "custom_installer",
            "download_url": "https://github.com/example/installer.exe",
            # sha256 ve publisher yok
        }
        ok, msg, _, _ = worker._install_direct_exe(1, 1, app)
        self.assertFalse(ok)
        self.assertIn("Güvenlik Engeli", msg)

    def test_system32_paths_exist(self):
        """get_system32_path fonksiyonunun geçerli sistem yollarını döndürdüğünü doğrular."""
        from system_checks import get_system32_path
        cmd_path = get_system32_path("cmd.exe")
        self.assertTrue(os.path.isabs(cmd_path))
        self.assertTrue(os.path.exists(cmd_path))

        ps_path = get_system32_path("powershell.exe")
        self.assertTrue(os.path.isabs(ps_path))
        self.assertTrue(os.path.exists(ps_path))

    def test_session_manager_dev_mode_no_resume_task(self):
        """Geliştirici modunda (derlenmemiş) resume görevinin güvensiz yollarla kurulmadığını doğrular."""
        from session_manager import SessionManager
        cmd = SessionManager._build_resume_command()
        self.assertEqual(cmd, "")
        # register_resume_task False dönmeli
        ok = SessionManager.register_resume_task()
        self.assertFalse(ok)

    def test_session_manager_sanitizes_app_ids(self):
        """Oturum JSON dosyasındaki tanımsız veya zararlı kimliklerin filtrelendiğini doğrular."""
        import tempfile
        import json
        import session_manager
        from session_manager import SessionManager

        # 1. Zararlı dict current_app ve sahte id'ler
        fake_session = {
            "status": "in_progress",
            "pending_app_ids": ["chrome", "malicious_injected_id_xyz"],
            "failed_app_ids": ["notepadplusplus", "fake_unknown_id"],
            "current_app": {"id": "malicious_current_id", "name": "Fake"},
        }

        with tempfile.TemporaryDirectory() as td:
            session_file = os.path.join(td, "session_state.json")
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(fake_session, f)

            with patch.object(session_manager, "SESSION_FILE", session_file), \
                 patch.object(session_manager, "BACKUP_SESSION_FILE", session_file + ".bak"):
                loaded = SessionManager.get_current_session()
                self.assertIsNotNone(loaded)
                self.assertIn("chrome", loaded["pending_app_ids"])
                self.assertNotIn("malicious_injected_id_xyz", loaded["pending_app_ids"])
                self.assertIn("notepadplusplus", loaded["failed_app_ids"])
                self.assertNotIn("fake_unknown_id", loaded["failed_app_ids"])
                # Zararlı dict current_app None olmalı (TypeError fırlatmamalı)
                self.assertIsNone(loaded["current_app"])

                # 2. Meşru dict current_app korunmalı
                fake_session["current_app"] = {"id": "chrome", "name": "Google Chrome"}
                with open(session_file, "w", encoding="utf-8") as f:
                    json.dump(fake_session, f)
                loaded2 = SessionManager.get_current_session()
                self.assertIsNotNone(loaded2)
                self.assertEqual(loaded2["current_app"], {"id": "chrome", "name": "Google Chrome"})

                # 3. update_current_app ve record_app_result döngüsü hatasız çalışmalı
                SessionManager.update_current_app("chrome", "Google Chrome")
                loaded3 = SessionManager.get_current_session()
                self.assertEqual(loaded3["current_app"], {"id": "chrome", "name": "Google Chrome"})
                SessionManager.record_app_result("chrome", "Google Chrome", True, True, "OK")
                loaded4 = SessionManager.get_current_session()
                self.assertIsNone(loaded4["current_app"])

    def test_uac_tweak_removed_for_security(self):
        """Güvenli masaüstü karartmasını kapatan UAC ayarının güvenlik gereği kaldırıldığını doğrular."""
        from tweaks import TWEAKS, _ALLOWED_REVERT, TWEAK_ACTIONS
        uac_tweak = next((tw for tw in TWEAKS if tw["id"] == "optimize_uac"), None)
        self.assertIsNone(uac_tweak, "optimize_uac güvenlik gereği TWEAKS içinde yer almamalıdır.")
        self.assertNotIn("optimize_uac", TWEAK_ACTIONS)
        self.assertNotIn("optimize_uac", _ALLOWED_REVERT)

    def test_main_mutex_is_local(self):
        """main.py içindeki mutex'in DoS squatting önlemek için Local\\ kapsamında olduğunu doğrular."""
        main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
        with open(main_py, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn('mutex_name = "Local\\', content)
        self.assertNotIn('mutex_name = "Global\\', content)

    def test_performance_check_internet_parallel(self):
        """check_internet_connection fonksiyonunun soket durumlarını doğru ayrıştırdığını doğrular."""
        import socket
        from unittest.mock import MagicMock
        from system_checks import check_internet_connection

        def fake_create_conn(addr, timeout=None):
            host, port = addr
            if host == "cdn.winget.microsoft.com":
                mock_sock = MagicMock()
                mock_sock.__enter__.return_value = mock_sock
                return mock_sock
            raise socket.timeout("timed out")

        with patch("socket.create_connection", side_effect=fake_create_conn):
            res = check_internet_connection()
            self.assertTrue(res["status"])
            self.assertIn("cdn.winget.microsoft.com", res["detail"])
            self.assertIn("Erişilemeyen:", res["detail"])

    def test_rows_ready_idempotency_guard(self):
        """_on_rows_ready metodunun çift çalıştırılmaya karşı korumalı (idempotent) olduğunu doğrular."""
        from unittest.mock import MagicMock
        from gui import MainWindow

        mock_self = MagicMock()
        mock_self._rows_ready_done = False
        mock_self.after = MagicMock()

        # İlk çağrı
        MainWindow._on_rows_ready(mock_self)
        self.assertTrue(mock_self._rows_ready_done)
        self.assertEqual(mock_self.apply_profile.call_count, 1)

        # İkinci çağrı (engellenmeli)
        MainWindow._on_rows_ready(mock_self)
        self.assertEqual(mock_self.apply_profile.call_count, 1)

    def test_main_handles_none_stdio(self):
        """main.py'nin windowed exe modunda None olan stdout/stderr'i güvenli sarmaladığını doğrular."""
        main_py = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
        with open(main_py, "r", encoding="utf-8") as f:
            code = f.read()
        self.assertIn("if sys.stdout is None:", code)
        self.assertIn("if sys.stderr is None:", code)
        self.assertIn("io.StringIO()", code)

    def test_performance_targeted_winget_check(self):
        """check_single_winget_installed fonksiyonunun hedeflenmiş sorgu yaptığını doğrular."""
        from verifier import check_single_winget_installed
        # Var olmayan sahte ID False dönmeli ve çökmemeli
        res = check_single_winget_installed("NonExistent.App.Id.12345")
        self.assertFalse(res)

    def test_performance_lru_caches(self):
        """get_winget_path ve get_system32_path fonksiyonlarının lru_cache içerdiğini doğrular."""
        from system_checks import get_winget_path, get_system32_path
        self.assertTrue(hasattr(get_winget_path, "cache_info"))
        self.assertTrue(hasattr(get_system32_path, "cache_info"))

    def test_gui_dispatch_ui_queue(self):
        """MainWindow dispatch_ui kuyruğunun görevleri güvenle ana iş parçacığında tükettiğini doğrular."""
        from unittest.mock import MagicMock
        import queue
        from gui import MainWindow

        mock_win = MagicMock()
        mock_win._ui_q = queue.SimpleQueue()
        mock_win.after = MagicMock()

        executed = []
        def task(arg):
            executed.append(arg)

        # Worker thread kuyruğa görev atar
        MainWindow.dispatch_ui(mock_win, task, "test_arg")
        self.assertFalse(mock_win._ui_q.empty())

        # Ana iş parçacığı kuyruğu tüketir
        MainWindow._poll_ui_queue(mock_win)
        self.assertTrue(mock_win._ui_q.empty())
        self.assertEqual(executed, ["test_arg"])

    def test_session_manager_onedir_resume_support(self):
        """SessionManager._build_resume_command metodunun --onedir modunda _internal klasörünü de kopyaladığını doğrular."""
        import tempfile
        from session_manager import SessionManager

        with tempfile.TemporaryDirectory() as fake_src, tempfile.TemporaryDirectory() as fake_secure:
            # Fake onedir structure
            fake_exe = os.path.join(fake_src, "FormatSonrasiKurulum.exe")
            with open(fake_exe, "w") as f:
                f.write("exe")
            fake_internal = os.path.join(fake_src, "_internal")
            os.makedirs(fake_internal, exist_ok=True)
            with open(os.path.join(fake_internal, "dummy.dll"), "w") as f:
                f.write("dll")

            with patch("sys.frozen", True, create=True), \
                 patch("sys.executable", fake_exe), \
                 patch.object(SessionManager, "_get_secure_bin_dir", return_value=fake_secure):
                cmd = SessionManager._build_resume_command()
                self.assertIn("--resume", cmd)
                self.assertTrue(os.path.isfile(os.path.join(fake_secure, "FormatSonrasiKurulum.exe")))
                self.assertTrue(os.path.isdir(os.path.join(fake_secure, "_internal")))
                self.assertTrue(os.path.isfile(os.path.join(fake_secure, "_internal", "dummy.dll")))

                # Madde 3: Tekrarlı kopyalamayı atlama kontrolü
                # _internal içine yeni işaret dosyası koyalım; tekrar çağrıldığında bu dosya ezilmemeli
                canary = os.path.join(fake_secure, "_internal", "canary.txt")
                with open(canary, "w") as f:
                    f.write("canary")
                cmd2 = SessionManager._build_resume_command()
                self.assertIn("--resume", cmd2)
                self.assertTrue(os.path.isfile(canary), "Tekrarlı kopyalama atlanmadı, canary silindi!")

                # Pürüz 1 Kontrolü: Hedef _internal silinmiş veya boş ise (yarım kopyalama senaryosu)
                # exe boyutu ve mtime eşleşse dahi kopyalama yeniden tetiklenmeli
                shutil.rmtree(os.path.join(fake_secure, "_internal"))
                cmd3 = SessionManager._build_resume_command()
                self.assertIn("--resume", cmd3)
                self.assertTrue(os.path.isfile(os.path.join(fake_secure, "_internal", "dummy.dll")),
                                "Hedef _internal eksikken baştan kopyalama tetiklenmedi!")
                self.assertFalse(os.path.isfile(canary), "Canary silinmemiş; temiz kopyalama yapılmadı!")

                # Pürüz 1 Kontrolü: Kaynak exe mtime değişirse (yeni sürüm aynı boyutta)
                # kopyalama yeniden tetiklenmeli
                with open(canary, "w") as f:
                    f.write("canary2")
                # Kaynak exe'nin zaman damgasını ileri alalım
                future_mtime = time.time() + 100
                os.utime(fake_exe, (future_mtime, future_mtime))
                cmd4 = SessionManager._build_resume_command()
                self.assertIn("--resume", cmd4)
                self.assertFalse(os.path.isfile(canary), "mtime değiştiğinde kopyalama yenilenmedi!")

    def test_session_manager_remove_resume_task_safe_guard(self):
        """remove_resume_task metodunun çalışan dizini silmeye çalışmadığını doğrular."""
        import tempfile
        from session_manager import SessionManager

        with tempfile.TemporaryDirectory() as fake_secure_root:
            bin_dir = os.path.join(fake_secure_root, "FormatSonrasi", "bin")
            os.makedirs(bin_dir, exist_ok=True)
            fake_exe = os.path.join(bin_dir, "FormatSonrasiKurulum.exe")
            with open(fake_exe, "w") as f:
                f.write("exe")
            fake_internal = os.path.join(bin_dir, "_internal")
            os.makedirs(fake_internal, exist_ok=True)
            with open(os.path.join(fake_internal, "lib.dll"), "w") as f:
                f.write("dll")

            # 1. running_from_bin = True iken (resume süreci çalışırken) silinmemeli
            with patch.dict(os.environ, {"ProgramData": fake_secure_root}), \
                 patch("sys.executable", fake_exe):
                SessionManager.remove_resume_task()
                self.assertTrue(os.path.isfile(fake_exe), "Çalışan exe silinmeye çalışıldı!")
                self.assertTrue(os.path.isdir(fake_internal), "Çalışan _internal silinmeye çalışıldı!")

            # 2. running_from_bin = False iken (dışarıdan temizlik) silinmeli
            other_exe = os.path.join(fake_secure_root, "other", "app.exe")
            os.makedirs(os.path.dirname(other_exe), exist_ok=True)
            with open(other_exe, "w") as f:
                f.write("other")
            with patch.dict(os.environ, {"ProgramData": fake_secure_root}), \
                 patch("sys.executable", other_exe):
                SessionManager.remove_resume_task()
                self.assertFalse(os.path.exists(fake_exe), "Bin exe temizlenmedi!")
                self.assertFalse(os.path.exists(fake_internal), "Bin _internal temizlenmedi!")

    def test_build_single_exe_sha256sums_lf_and_strict_error(self):
        """build_single_exe._generate_sha256sums'un LF satır sonu kullandığını ve hata yutmadığını doğrular."""
        import tempfile
        from build_single_exe import _generate_sha256sums

        with tempfile.TemporaryDirectory() as temp_dir:
            test_file = os.path.join(temp_dir, "test.txt")
            with open(test_file, "wb") as f:
                f.write(b"hello world")

            out_sums = os.path.join(temp_dir, "SHA256SUMS.txt")
            _generate_sha256sums(temp_dir, out_sums)

            # LF satır sonu doğrulaması (CR (\r) olmamalı)
            with open(out_sums, "rb") as f:
                raw_bytes = f.read()
            self.assertNotIn(b"\r\n", raw_bytes, "SHA256SUMS.txt CRLF içeriyor, salt LF olmalı!")
            self.assertIn(b"\n", raw_bytes)

            # Hata yutmama doğrulaması: Okunamayan dosyada RuntimeError fırlatmalı
            with patch("build_single_exe._sha256_of_file", side_effect=PermissionError("Erişim engellendi")):
                with self.assertRaises(RuntimeError):
                    _generate_sha256sums(temp_dir, out_sums)


if __name__ == "__main__":
    unittest.main()
