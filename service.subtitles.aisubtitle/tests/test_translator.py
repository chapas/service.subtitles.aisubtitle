import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from resources.lib import translator_file as translator  # noqa: E402

SRT = "1\n00:00:01,000 --> 00:00:02,000\nHello\n\n2\n00:00:03,000 --> 00:00:04,000\nWorld\n"


class FakeResp(io.BytesIO):
	def __enter__(self):
		return self

	def __exit__(self, *a):
		return False


class TranslatorTests(unittest.TestCase):
	def test_sends_file_attachment_payload(self):
		calls = []

		def opener(req, timeout):
			body = json.loads(req.data)
			calls.append((req, body))
			return FakeResp(json.dumps({"choices": [{"message": {"content": "1\n00:00:01,000 --> 00:00:02,000\nOlá\n"}}]}).encode())

		out = translator.translate_subtitle(
			SRT, "Portuguese", "http://x/v1/", "k", "m",
			opener=opener, extra_headers={"x-tier": "flex"}, source_name="movie.en.srt")

		self.assertEqual(len(calls), 1)
		req, body = calls[0]
		self.assertEqual(req.full_url, "http://x/v1/chat/completions")
		self.assertEqual(req.get_header("Authorization"), "Bearer k")
		self.assertEqual(req.get_header("X-tier"), "flex")
		self.assertIn("Portuguese", body["messages"][0]["content"])
		content = body["messages"][1]["content"]
		self.assertEqual(content[0]["text"], "SRT file 'movie.en.srt' to translate to Portuguese:")
		self.assertEqual(content[1], {"type": "text", "text": SRT})
		self.assertIn("Olá", out)

	def test_parse_headers(self):
		self.assertEqual(translator.parse_headers("a: 1; b : two"), {"a": "1", "b": "two"})

	def test_decode_bytes(self):
		self.assertEqual(translator.decode_bytes("ñ".encode("cp1252")), "ñ")


if __name__ == "__main__":
	unittest.main()
