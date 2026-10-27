import unittest

from ghost import sanitize_text, safe_url, sanitize_path


class GhostSecurityTests(unittest.TestCase):
    def test_sanitize_text_removes_control_characters(self):
        dirty = "  Hello\x00world\n  "
        cleaned = sanitize_text(dirty)
        self.assertEqual(cleaned, "Helloworld")

    def test_safe_url_rejects_unknown_domains(self):
        self.assertIsNone(safe_url("https://malicious.example/evil"))

    def test_safe_url_allows_known_domains(self):
        url = safe_url("https://www.youtube.com/watch?v=123")
        self.assertEqual(url, "https://www.youtube.com/watch?v=123")

    def test_sanitize_path_rejects_path_traversal(self):
        self.assertIsNone(sanitize_path("../../etc/passwd"))


if __name__ == "__main__":
    unittest.main()
