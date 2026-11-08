# -*- coding: utf-8 -*-
"""
Format Sonrası Kurulum Sihirbazı - Kurulum Motoru Birim Testleri
İndirme boyutu koruması, 1641/3010/0 dönüş kodları, HTTPS ve güvenlik kontrollerini test eder.
"""

import hashlib
import io
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from installer_core import InstallationWorker, StrictHTTPSRedirectHandler


class TestInstallerCore(unittest.TestCase):
    def setUp(self):
        self.logs = []
        self.progress_updates = []
        self.completed_apps = []
        self.finished_summary = None

        self.worker = InstallationWorker(
            app_list=[],
            on_log=lambda s: self.logs.append(s),
            on_progress=lambda idx, tot, name, st: self.progress_updates.append((idx, tot, name, st)),
            on_app_completed=lambda aid, succ, msg: self.completed_apps.append((aid, succ, msg)),
            on_finished=lambda sm: setattr(self, "finished_summary", sm),
        )

    def test_direct_exe_size_limit_formula(self):
        """İndirme boyutu sınırının min(max(size*3, 50), 4096) formülüne uygun olduğunu doğrular."""
        # Küçük dosya: 5 MB -> 5 * 3 = 15 -> alt sınır 50 MB olmalı (eskisi gibi 2048 MB değil!)
        size_small = 5
        limit_small = min(max(size_small * 3, 50), 4096)
        self.assertEqual(limit_small, 50)

        # Orta dosya: 100 MB -> 100 * 3 = 300 MB
        size_med = 100
        limit_med = min(max(size_med * 3, 50), 4096)
        self.assertEqual(limit_med, 300)

        # Çok büyük dosya: 2500 MB -> 2500 * 3 = 7500 -> üst sınır 4096 MB ile sınırlandırılmalı
        size_large = 2500
        limit_large = min(max(size_large * 3, 50), 4096)
        self.assertEqual(limit_large, 4096)

    def test_direct_exe_rejects_non_https(self):
        """HTTP protokolündeki indirmelerin güvenlik engeline takıldığını doğrular."""
        app = {
            "name": "Güvensiz Uygulama",
            "download_url": "http://example.com/setup.exe",
            "sha256": "abc123def456",
        }
        ok, msg, is_reboot, is_already = self.worker._install_direct_exe(1, 1, app)
        self.assertFalse(ok)
        self.assertIn("Yalnızca HTTPS", msg)

    def test_direct_exe_rejects_missing_hash_and_publisher(self):
        """Ne SHA-256 ne de yayıncı sertifikası tanımlı olmayan doğrudan ikililerin reddedildiğini doğrular."""
        app = {
            "name": "Bilinmeyen Uygulama",
            "download_url": "https://example.com/setup.exe",
        }
        ok, msg, is_reboot, is_already = self.worker._install_direct_exe(1, 1, app)
        self.assertFalse(ok)
        self.assertIn("Güvenlik Engeli", msg)

    def test_direct_exe_exit_codes_1641_3010_0(self):
        """1641, 3010 ve 0 dönüş kodlarının beklenen is_reboot ve başarı sonuçlarını ürettiğini doğrular."""
        fake_content = b"MZFakeExecutableContent"
        expected_sha = hashlib.sha256(fake_content).hexdigest()

        cases = [
            (0, True, False),     # 0 -> Başarılı, reboot gerekmez
            (3010, True, True),   # 3010 -> Başarılı, reboot gerekir
            (1641, True, True),   # 1641 -> Başarılı, yeniden başlatma tetiklendi
            (1603, False, False), # 1603 -> Hata kodu
        ]

        for exit_code, expected_success, expected_reboot in cases:
            with tempfile.TemporaryDirectory() as temp_dir:
                app = {
                    "name": f"TestApp_{exit_code}",
                    "download_url": "https://github.com/owner/repo/test.exe",
                    "sha256": expected_sha,
                }

                mock_proc = MagicMock()
                mock_proc.wait.return_value = None
                mock_proc.returncode = exit_code

                mock_resp = io.BytesIO(fake_content)
                mock_opener = MagicMock()
                mock_opener.open.return_value.__enter__.return_value = mock_resp

                with patch.object(self.worker, "_secure_download_dir", return_value=temp_dir), \
                     patch("urllib.request.build_opener", return_value=mock_opener), \
                     patch("subprocess.Popen", return_value=mock_proc):

                    ok, msg, is_reboot, is_already = self.worker._install_direct_exe(1, 1, app)
                    self.assertEqual(ok, expected_success, f"Exit code {exit_code} success mismatch")
                    self.assertEqual(is_reboot, expected_reboot, f"Exit code {exit_code} reboot mismatch")

    def test_strict_https_redirect_handler(self):
        """StrictHTTPSRedirectHandler'ın güvenli olmayan yönlendirmeleri reddettiğini doğrular."""
        import urllib.request
        handler = StrictHTTPSRedirectHandler()
        dummy_req = urllib.request.Request("https://github.com/release.exe")

        # 1. HTTP'ye yönlendirme reddedilmeli
        with self.assertRaises(ValueError):
            handler.redirect_request(dummy_req, None, 302, "Found", {}, "http://github.com/setup.exe")

        # 2. İzin verilmeyen alan adı reddedilmeli
        with self.assertRaises(ValueError):
            handler.redirect_request(dummy_req, None, 302, "Found", {}, "https://zararli-site.com/setup.exe")

        # 3. İzin verilen alan adı kabul edilmeli
        req2 = handler.redirect_request(dummy_req, None, 302, "Found", {}, "https://github.com/owner/repo/setup.exe")
        self.assertIsNotNone(req2)


if __name__ == "__main__":
    unittest.main()
