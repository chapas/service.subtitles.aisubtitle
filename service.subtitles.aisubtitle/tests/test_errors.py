import os
import socket
import sys
import unittest
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from resources.lib import errors  # noqa: E402


class ErrorMessageTests(unittest.TestCase):
	def test_auth_status_mentions_api_key(self):
		self.assertIn("API key", errors.describe(RuntimeError("HTTP 401: nope")))
		self.assertIn("API key", errors.describe(RuntimeError("HTTP 403: nope")))

	def test_not_found_mentions_url_and_model(self):
		self.assertIn("model", errors.describe(RuntimeError("HTTP 404: missing")))

	def test_rate_limit(self):
		self.assertIn("Rate limit", errors.describe(RuntimeError("HTTP 429: slow down")))

	def test_server_error(self):
		self.assertIn("HTTP 503", errors.describe(RuntimeError("HTTP 503: down")))

	def test_timeout(self):
		self.assertIn("timed out", errors.describe(socket.timeout("timed out")))
		self.assertIn("timed out", errors.describe(TimeoutError()))

	def test_network(self):
		self.assertIn("Network error", errors.describe(urllib.error.URLError("refused")))

	def test_bad_json(self):
		self.assertIn("Unexpected response", errors.describe(ValueError("bad json")))

	def test_fallback_uses_message_or_class(self):
		self.assertEqual(errors.describe(RuntimeError("custom")), "custom")
		self.assertEqual(errors.describe(KeyError()), "KeyError")


if __name__ == "__main__":
	unittest.main()
