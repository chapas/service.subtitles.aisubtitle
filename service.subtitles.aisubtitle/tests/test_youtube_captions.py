import io
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resources.lib import youtube_captions  # noqa: E402


class FakeResponse(io.BytesIO):
	def __enter__(self):
		return self

	def __exit__(self, *args):
		return False


class YoutubeCaptionsTest(unittest.TestCase):
	def test_caption_tracks_uses_visitor_data(self):
		seen = []

		def opener(req, timeout=30):
			seen.append(req)
			if "watch?v=" in req.full_url:
				return FakeResponse(b'... "VISITOR_DATA":"VISIT123" ...')
			player = {"playabilityStatus": {"status": "OK"}, "captions": {"playerCaptionsTracklistRenderer": {
				"captionTracks": [
					{"baseUrl": "https://yt/timedtext?lang=en&kind=asr", "languageCode": "en", "kind": "asr",
					 "name": {"simpleText": "English (auto-generated)"}},
					{"baseUrl": "https://yt/timedtext?lang=en", "languageCode": "en", "name": {"simpleText": "English"}},
				]}}}
			return FakeResponse(json.dumps(player).encode())

		tracks = youtube_captions.caption_tracks("abc", opener=opener)
		body = json.loads(seen[1].data.decode())
		self.assertEqual(body["context"]["client"]["visitorData"], "VISIT123")
		self.assertEqual(body["context"]["client"]["clientName"], "VISIONOS")
		self.assertEqual(seen[1].get_header("X-goog-visitor-id"), "VISIT123")
		self.assertEqual(youtube_captions.pick_track(tracks, ("en",))["name"], "English")

	def test_download_vtt_forces_vtt_format(self):
		urls = []

		def opener(req, timeout=30):
			urls.append(req.full_url)
			return FakeResponse(b"WEBVTT\n")

		youtube_captions.download_vtt({"url": "https://yt/timedtext?lang=en&fmt=srv3"}, opener=opener)
		self.assertIn("fmt=vtt", urls[0])
		self.assertNotIn("srv3", urls[0])


if __name__ == "__main__":
	unittest.main()
