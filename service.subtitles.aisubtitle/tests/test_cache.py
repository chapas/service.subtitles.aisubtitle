import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from resources.lib import cache  # noqa: E402


def read_text(path):
	with open(path, encoding="utf-8") as f:
		return f.read()


def write_text(path, text):
	with open(path, "w", encoding="utf-8") as f:
		f.write(text)


class CacheTests(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.TemporaryDirectory()
		self.folder = os.path.join(self.tmp.name, "aisubtitle")

	def tearDown(self):
		self.tmp.cleanup()

	def test_miss_returns_none(self):
		self.assertIsNone(cache.get(self.folder, "youtube:abc|en", "Portuguese", read_text))

	def test_put_then_get_round_trip(self):
		cache.put(self.folder, "youtube:abc|en", "Portuguese", "1\n", write_text)
		self.assertEqual(cache.get(self.folder, "youtube:abc|en", "Portuguese", read_text), "1\n")

	def test_key_separates_language_and_source(self):
		cache.put(self.folder, "youtube:abc|en", "Portuguese", "pt", write_text)
		self.assertIsNone(cache.get(self.folder, "youtube:abc|en", "French", read_text))
		self.assertIsNone(cache.get(self.folder, "youtube:xyz|en", "Portuguese", read_text))

	def test_key_is_stable_and_short(self):
		self.assertEqual(cache.cache_key("a", "b"), cache.cache_key("a", "b"))
		self.assertEqual(len(cache.cache_key("a", "b")), 20)


if __name__ == "__main__":
	unittest.main()
