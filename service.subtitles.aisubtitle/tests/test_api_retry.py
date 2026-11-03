import io
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from resources.lib import translator_file as translator, youtube_captions  # noqa: E402


class FakeResponse(io.BytesIO):
	def __enter__(self):
		return self

	def __exit__(self, *args):
		return False


class RetryTests(unittest.TestCase):
	def setUp(self):
		patcher = mock.patch("resources.lib.youtube_captions.time.sleep")
		self.sleep = patcher.start()
		self.addCleanup(patcher.stop)

	def test_get_retries_then_succeeds(self):
		calls = []

		def opener(req, timeout=15):
			calls.append(req)
			if len(calls) < 3:
				raise OSError("reset")
			return FakeResponse(b"ok")

		self.assertEqual(youtube_captions._get("https://yt/x", opener=opener), "ok")
		self.assertEqual(len(calls), 3)
		self.assertEqual(self.sleep.call_count, 2)

	def test_get_gives_up_after_retries(self):
		calls = []

		def opener(req, timeout=15):
			calls.append(req)
			raise OSError("down")

		with self.assertRaises(OSError):
			youtube_captions._get("https://yt/x", opener=opener, retries=2)
		self.assertEqual(len(calls), 3)

	def test_download_vtt_falls_back_to_second_candidate(self):
		urls = []

		def opener(req, timeout=30):
			urls.append(req.full_url)
			if "fmt=vtt" in req.full_url and urls.count(req.full_url) == 1 and len(urls) <= 5:
				raise OSError("first form refused")
			return FakeResponse(b"WEBVTT\n")

		text = youtube_captions.download_vtt({"url": "https://yt/t?lang=en"}, opener=opener)
		self.assertEqual(text, "WEBVTT\n")

	def test_translate_request_carries_auth_and_model(self):
		seen = []

		def opener(req, timeout):
			seen.append((req.full_url, req.get_header("Authorization"), req.data))
			return FakeResponse(b'{"choices": [{"message": {"content": "1\\nHi"}}]}')

		translator.translate_subtitle("1\n", "Portuguese", "https://api.x/v1/", "KEY", "model-a", opener=opener)
		url, auth, data = seen[0]
		self.assertEqual(url, "https://api.x/v1/chat/completions")
		self.assertEqual(auth, "Bearer KEY")
		self.assertIn(b'"model": "model-a"', data)
		self.assertIn(b"Portuguese", data)


if __name__ == "__main__":
	unittest.main()
