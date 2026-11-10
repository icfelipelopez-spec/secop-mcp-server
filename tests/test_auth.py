import unittest

from auth import api_key_autorizada


class ApiKeyAuthorizationTests(unittest.TestCase):
    def test_accepts_matching_bearer_key(self):
        self.assertTrue(api_key_autorizada("Bearer abc123", "abc123"))

    def test_bearer_scheme_is_case_insensitive(self):
        self.assertTrue(api_key_autorizada("bearer abc123", "abc123"))

    def test_rejects_wrong_key(self):
        self.assertFalse(api_key_autorizada("Bearer wrong", "abc123"))

    def test_rejects_missing_header(self):
        self.assertFalse(api_key_autorizada(None, "abc123"))

    def test_rejects_wrong_scheme(self):
        self.assertFalse(api_key_autorizada("Basic abc123", "abc123"))

    def test_rejects_empty_configured_key(self):
        self.assertFalse(api_key_autorizada("Bearer abc123", ""))

    def test_rejects_empty_supplied_key(self):
        self.assertFalse(api_key_autorizada("Bearer   ", "abc123"))


if __name__ == "__main__":
    unittest.main()
