import io
import os
import sys
import unittest
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from resources.lib import errors, mkv_subs, translator_file as translator, youtube_captions  # noqa: E402


class FakeResponse(io.BytesIO):
	def __enter__(self):
		return self

	def __exit__(self, *args):
		return False


def http_error(code, body=b""):
	return urllib.error.HTTPError("http://x", code, "err", {}, io.BytesIO(body))


class YoutubeParserTests(unittest.TestCase):
	def test_tracks_from_player_skips_tracks_without_url(self):
		player = {"captions": {"playerCaptionsTracklistRenderer": {"captionTracks": [
			{"baseUrl": "https://yt/a", "languageCode": "pt", "name": {"simpleText": "Portuguese"}},
			{"languageCode": "fr", "name": {"runs": [{"text": "French"}]}},
		]}}}
		tracks = youtube_captions._tracks_from_player(player)
		self.assertEqual(len(tracks), 1)
		self.assertEqual(tracks[0]["lang"], "pt")
		self.assertEqual(tracks[0]["name"], "Portuguese")
		self.assertFalse(tracks[0]["auto"])

	def test_asr_kind_marks_auto(self):
		player = {"captions": {"playerCaptionsTracklistRenderer": {"captionTracks": [
			{"baseUrl": "https://yt/a", "languageCode": "en", "kind": "asr", "name": {"simpleText": "English"}},
		]}}}
		self.assertTrue(youtube_captions._tracks_from_player(player)[0]["auto"])

	def test_pick_track_prefers_manual_then_english(self):
		tracks = [
			{"lang": "pt", "auto": True, "url": "u1", "name": "pt auto"},
			{"lang": "en", "auto": False, "url": "u2", "name": "en manual"},
			{"lang": "pt", "auto": False, "url": "u3", "name": "pt manual"},
		]
		self.assertEqual(youtube_captions.pick_track(tracks, ("pt",))["name"], "pt manual")
		self.assertEqual(youtube_captions.pick_track(tracks, ("de",))["name"], "en manual")

	def test_pick_track_empty(self):
		self.assertIsNone(youtube_captions.pick_track([]))

	def test_caption_tracks_returns_empty_when_innertube_fails(self):
		def opener(req, timeout=30):
			raise OSError("offline")

		self.assertEqual(youtube_captions.caption_tracks("abc", opener=opener), [])


class MatroskaHelperTests(unittest.TestCase):
	def test_is_matroska_extensions(self):
		self.assertTrue(mkv_subs.is_matroska("http://h/movie.MKV"))
		self.assertTrue(mkv_subs.is_matroska("smb://h/a.webm|User-Agent=x"))
		self.assertFalse(mkv_subs.is_matroska("/media/movie.mp4"))

	def test_split_kodi_url_headers(self):
		base, headers = mkv_subs.split_kodi_url("http://h/a.mkv|Cookie=abc&Referer=http%3A%2F%2Fr")
		self.assertEqual(base, "http://h/a.mkv")
		self.assertEqual(headers["Cookie"], "abc")
		self.assertEqual(headers["Referer"], "http://r")
		self.assertIn("User-Agent", headers)

	def test_read_vint_and_header(self):
		self.assertEqual(mkv_subs.read_vint(bytes([0x81]), 0), (1, 1))
		self.assertEqual(mkv_subs.read_vint(bytes([0x40, 0x02]), 0), (2, 2))
		eid, size, hl = mkv_subs.read_header(bytes([0x1A, 0x45, 0xDF, 0xA3, 0x84, 0x42, 0x86, 0x81, 0x01]), 0)
		self.assertEqual((eid, size, hl), (0x1A45DFA3, 4, 5))

	def test_children_walks_elements(self):
		data = bytes([0x83, 0x81, 0x07, 0xA3, 0x82, 0x00, 0x01])
		self.assertEqual([(eid, payload) for eid, payload in mkv_subs.children(data)],
						 [(0x83, b"\x07"), (0xA3, b"\x00\x01")])

	def test_uint_and_text(self):
		self.assertEqual(mkv_subs.uint(bytes([0x01, 0x00])), 256)
		self.assertEqual(mkv_subs.text(b"eng\x00junk"), "eng")

	def test_track_decode_header_strip_and_zlib(self):
		import zlib
		track = mkv_subs.Track(1, "S_TEXT/UTF8", "eng", "", False, [(3, b"HDR")])
		self.assertEqual(track.decode(b"body"), b"HDRbody")
		zipped = zlib.compress(b"hello")
		track = mkv_subs.Track(1, "S_TEXT/UTF8", "eng", "", False, [(0, None)])
		self.assertEqual(track.decode(zipped), b"hello")


class ApiTests(unittest.TestCase):
	def test_check_connection_success_sends_bearer(self):
		seen = []

		def opener(req, timeout):
			seen.append(req)
			return FakeResponse(b'{"data": []}')

		self.assertTrue(translator.check_connection("https://api.x/v1/", "KEY", opener=opener))
		self.assertEqual(seen[0].full_url, "https://api.x/v1/models")
		self.assertEqual(seen[0].get_header("Authorization"), "Bearer KEY")

	def test_check_connection_http_error_raises(self):
		def opener(req, timeout):
			raise http_error(401, b"bad key")

		with self.assertRaises(RuntimeError) as ctx:
			translator.check_connection("https://api.x/v1", "nope", opener=opener)
		self.assertIn("HTTP 401", str(ctx.exception))
		self.assertIn("API key", errors.describe(ctx.exception))

	def test_translate_http_401_maps_to_api_key_message(self):
		def opener(req, timeout):
			raise http_error(401, b"unauthorized")

		with self.assertRaises(RuntimeError) as ctx:
			translator.translate_subtitle("1\n", "French", "https://api.x/v1", "k", "m", opener=opener)
		self.assertIn("API key", errors.describe(ctx.exception))

	def test_translate_http_429_maps_to_rate_limit(self):
		def opener(req, timeout):
			raise http_error(429, b"slow down")

		with self.assertRaises(RuntimeError) as ctx:
			translator.translate_subtitle("1\n", "French", "https://api.x/v1", "k", "m", opener=opener)
		self.assertIn("Rate limit", errors.describe(ctx.exception))

	def test_translate_timeout_maps_to_timeout_message(self):
		def opener(req, timeout):
			raise TimeoutError("read timed out")

		with self.assertRaises(TimeoutError) as ctx:
			translator.translate_subtitle("1\n", "French", "https://api.x/v1", "k", "m", opener=opener)
		self.assertIn("timed out", errors.describe(ctx.exception))

	def test_translate_strips_code_fences_and_keeps_trailing_newline(self):
		def opener(req, timeout):
			body = '{"choices": [{"message": {"content": "```srt\\n1\\nOla\\n```"}}]}'
			return FakeResponse(body.encode())

		out = translator.translate_subtitle("1\n", "Portuguese", "https://api.x/v1", "k", "m", opener=opener)
		self.assertEqual(out, "1\nOla\n")


if __name__ == "__main__":
	unittest.main()
