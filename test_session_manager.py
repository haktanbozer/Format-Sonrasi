# -*- coding: utf-8 -*-
"""
Format Sonrası Kurulum Sihirbazı - Oturum Yöneticisi Birim Testleri
Oturum yaşam döngüsü, bozuk dosya koruması ve yeniden başlatma işaretlerini test eder.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from session_manager import SessionManager


class TestSessionManager(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.session_file = os.path.join(self.temp_dir.name, "session_state.json")
        self.backup_session_file = os.path.join(self.temp_dir.name, "session_state.json.bak")

        self.patchers = [
            patch("session_manager.SESSION_FILE", self.session_file),
            patch("session_manager.BACKUP_SESSION_FILE", self.backup_session_file),
            patch("session_manager.SESSION_DIR", self.temp_dir.name),
        ]
        for p in self.patchers:
            p.start()

    def tearDown(self):
        for p in reversed(self.patchers):
            p.stop()
        self.temp_dir.cleanup()

    def test_session_lifecycle(self):
        """Oturum oluşturma, aktif uygulama güncelleme, sonuç kaydetme ve bitirme akışını doğrular."""
        apps = [
            {"id": "git", "name": "Git"},
            {"id": "vscode", "name": "Visual Studio Code"},
        ]

        # 1. Oturum oluştur
        session = SessionManager.create_session(apps)
        self.assertEqual(session["status"], "in_progress")
        self.assertEqual(session["pending_app_ids"], ["git", "vscode"])
        self.assertEqual(session["completed_apps"], [])
        self.assertFalse(session["reboot_required"])

        # 2. Aktif uygulamayı güncelle
        SessionManager.update_current_app("git", "Git")
        cur = SessionManager.get_current_session()
        self.assertEqual(cur["current_app"]["id"], "git")

        # 3. Uygulama sonucunu kaydet
        SessionManager.record_app_result("git", "Git", success=True, verified=True, message="Kuruldu")
        cur = SessionManager.get_current_session()
        completed_ids = [a["id"] for a in cur["completed_apps"]]
        self.assertIn("git", completed_ids)
        self.assertNotIn("git", cur["pending_app_ids"])
        self.assertIsNone(cur["current_app"])

        # 4. Oturumu tamamla
        SessionManager.finish_session()
        # Oturum dosyası temizlenmiş olmalı
        self.assertFalse(os.path.exists(self.session_file))

    def test_mark_reboot_required(self):
        """Yeniden başlatma bayrağının oturum verisine işlendiğini doğrular."""
        apps = [{"id": "git", "name": "Git"}]
        SessionManager.create_session(apps)

        with patch.object(SessionManager, "register_resume_task", return_value=True):
            SessionManager.mark_reboot_required(register_task=False)
            cur = SessionManager.get_current_session()
            self.assertTrue(cur["reboot_required"])

    def test_corrupted_json_backed_up_to_corrupt(self):
        """Bozuk oturum dosyasının okunurken .corrupt uzantısıyla yedeklendiğini doğrular."""
        test_file = os.path.join(self.temp_dir.name, "corrupt_session.json")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("{ invalid json content ...")

        res = SessionManager._try_read_json(test_file)
        self.assertIsNone(res)
        self.assertTrue(os.path.exists(test_file + ".corrupt"))


if __name__ == "__main__":
    unittest.main()
