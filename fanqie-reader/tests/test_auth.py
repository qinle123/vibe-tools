import unittest
import tempfile
import shutil
from pathlib import Path

from fanqie_reader.auth import AuthManager

class TestAuthManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.auth = AuthManager(base_dir=Path(self.test_dir))

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_initial_state(self):
        self.assertFalse(self.auth.is_logged_in())
        self.assertEqual(self.auth.get_display_name(), "未登录")
        self.assertEqual(self.auth.get_cookie_header(), "")

    def test_set_cookie_and_persistence(self):
        cookie_sample = "sessionid=test_session_12345; sid_tt=abc888; uid_tt=user_999"
        self.auth.set_cookie_str(cookie_sample)

        self.assertTrue(self.auth.is_logged_in())
        self.assertIn("sessionid=test_session_12345", self.auth.get_cookie_header())
        self.assertIn("sid_tt=abc888", self.auth.get_cookie_header())

        # 新实例加载，验证本地持久化
        auth2 = AuthManager(base_dir=Path(self.test_dir))
        self.assertTrue(auth2.is_logged_in())
        self.assertEqual(auth2.cookies.get("sessionid"), "test_session_12345")

    def test_logout(self):
        self.auth.set_cookie_str("sessionid=xyz123")
        self.assertTrue(self.auth.is_logged_in())

        self.auth.logout()
        self.assertFalse(self.auth.is_logged_in())
        self.assertFalse((Path(self.test_dir) / "auth.json").exists())

        auth2 = AuthManager(base_dir=Path(self.test_dir))
        self.assertFalse(auth2.is_logged_in())

if __name__ == "__main__":
    unittest.main()
