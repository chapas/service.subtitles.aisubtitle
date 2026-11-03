import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resources.lib import stream_subs  # noqa: E402


class StreamSubsTest(unittest.TestCase):
	def test_vtt(self):
		srt = stream_subs.to_srt("WEBVTT\n\n00:00:01.000 --> 00:00:02.500 align:start\n<c>Hello</c> there\n")
		self.assertEqual(srt, "1\n00:00:01,000 --> 00:00:02,500\nHello there\n")

	def test_vtt_rolling_captions(self):
		srt = stream_subs.to_srt("WEBVTT\n\n00:00:01.000 --> 00:00:01.010 align:start\nSony has spent\n\n"
								 "00:00:01.010 --> 00:00:03.000 align:start\nSony has spent\nto turn Blu-ray\n\n"
								 "00:00:03.000 --> 00:00:03.010 align:start\nto turn Blu-ray\n")
		self.assertEqual(srt, "1\n00:00:01,000 --> 00:00:01,010\nSony has spent\n\n"
							  "2\n00:00:01,010 --> 00:00:03,000\nto turn Blu-ray\n")

	def test_ttml(self):
		srt = stream_subs.to_srt('<tt xmlns="http://www.w3.org/ns/ttml"><body><div>'
								 '<p begin="1.5s" end="3s">Hi<br/>you</p></div></body></tt>')
		self.assertEqual(srt, "1\n00:00:01,500 --> 00:00:03,000\nHi\nyou\n")

	def test_mpd(self):
		mpd = ('<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period>'
			   '<AdaptationSet contentType="text" mimeType="text/vtt" lang="en"><Representation id="1">'
			   '<BaseURL>http://x/a?b=1&amp;c=2</BaseURL></Representation></AdaptationSet></Period></MPD>')
		self.assertEqual(stream_subs.mpd_text_tracks(mpd), [("en", "http://x/a?b=1&c=2", "text/vtt")])


if __name__ == "__main__":
	unittest.main()
