# -*- coding: utf-8 -*-
"""
Format Sonrası Kurulum Sihirbazı - Windows İnce Ayarları ve Geri Alma Birim Testleri
tweaks_backup.json bozuk dosya koruması, beyaz liste denetimi, telemetri ve geri yükleme noktasını test eder.
"""

import json
import os
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
import tweaks


class TestTweaks(unittest.TestCase):

    def test_load_backup_non_existent(self):
        """Var olmayan yedek dosyasının boş dict döndürdüğünü doğrular."""
        with tempfile.TemporaryDirectory() as td:
            fake_backup = os.path.join(td, "non_existent.json")
            with patch.object(tweaks, "BACKUP_FILE", fake_backup):
                res = tweaks._load_backup()
                self.assertEqual(res, {})

    def test_load_backup_valid_json(self):
        """Geçerli JSON yedek dosyasının başarıyla yüklendiğini doğrular."""
        with tempfile.TemporaryDirectory() as td:
            fake_backup = os.path.join(td, "tweaks_backup.json")
            data = {"classic_context_menu": {"existed": False}}
            with open(fake_backup, "w", encoding="utf-8") as f:
                json.dump(data, f)

            with patch.object(tweaks, "BACKUP_FILE", fake_backup):
                res = tweaks._load_backup()
                self.assertEqual(res, data)

    def test_load_backup_corrupted_json_creates_corrupt_file(self):
        """Bozuk JSON gördüğünde dosyanın .corrupt uzantısıyla kenara alındığını ve ezilmesinin önlendiğini doğrular."""
        with tempfile.TemporaryDirectory() as td:
            fake_backup = os.path.join(td, "tweaks_backup.json")
            # Bozuk / eksik JSON içeriği
            with open(fake_backup, "w", encoding="utf-8") as f:
                f.write('{"classic_context_menu": { "existed": ')

            with patch.object(tweaks, "BACKUP_FILE", fake_backup):
                res = tweaks._load_backup()
                # 1. Boş sözlük dönmeli
                self.assertEqual(res, {})
                # 2. .corrupt uzantılı dosya oluşturulmuş olmalı
                corrupt_file = fake_backup + ".corrupt"
                self.assertTrue(os.path.exists(corrupt_file), "Bozuk dosya .corrupt olarak taşınmadı!")
                with open(corrupt_file, "r", encoding="utf-8") as cf:
                    content = cf.read()
                self.assertIn("classic_context_menu", content)

    def test_telemetry_tweak_clarification_message(self):
        """Telemetri ayarının Home/Pro vs Enterprise sürümlerindeki farkı belirten açıklayıcı mesaj döndüğünü doğrular."""
        with patch.object(tweaks, "_safe_write_reg", return_value=True):
            ok, msg = tweaks.apply_disable_telemetry(enable=True)
            self.assertTrue(ok)
            self.assertIn("Enterprise", msg)
            self.assertIn("Home", msg)
            self.assertIn("Pro", msg)

    def test_revert_all_tweaks_rejects_unauthorized_path(self):
        """Beyaz listede yer almayan izinsiz kayıt defteri yollarının geri alma motoru tarafından reddedildiğini doğrular."""
        fake_malicious_backup = {
            "disable_telemetry": {
                r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run\TrojanUpdater": {
                    "root": "HKLM",
                    "key_path": r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
                    "value_name": "TrojanUpdater",
                    "existed": False,
                    "data": None,
                    "type": None,
                }
            }
        }
        with patch.object(tweaks, "_load_backup", return_value=fake_malicious_backup), \
             patch.object(tweaks, "_safe_delete_reg_value") as mock_delete, \
             patch.object(tweaks, "_save_backup"):
            results = tweaks.revert_all_tweaks()
            # Asla silme yapılmamalı
            self.assertEqual(mock_delete.call_count, 0)
            self.assertEqual(len(results), 1)
            tweak_id, success, msg = results[0]
            self.assertFalse(success)
            self.assertIn("reddedildi", msg.lower())

    def test_create_system_restore_point_success(self):
        """Sistem geri yükleme noktası oluşturma çağrısının başarı durumunu doğrular."""
        mock_res = MagicMock()
        mock_res.returncode = 0
        with patch("subprocess.run", return_value=mock_res):
            ok, msg = tweaks.create_system_restore_point("Test_Restore")
            self.assertTrue(ok)
            self.assertIn("başarıyla", msg)

    def test_create_system_restore_point_disabled_or_throttled(self):
        """Sistem koruması kapalıyken veya 24 saat kısıtı varken anlaşılır hata mesajı döndüğünü doğrular."""
        mock_res = MagicMock()
        mock_res.returncode = 1
        mock_res.stdout = "A new system restore point cannot be created because one was already created within 1440 minutes."
        mock_res.stderr = ""
        with patch("subprocess.run", return_value=mock_res):
            ok, msg = tweaks.create_system_restore_point("Test_Restore")
            self.assertFalse(ok)
            self.assertIn("24 saat", msg)


if __name__ == "__main__":
    unittest.main()
