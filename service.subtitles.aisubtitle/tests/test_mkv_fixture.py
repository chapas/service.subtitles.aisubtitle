import http.server
import os
import re
import struct
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from resources.lib import mkv_subs  # noqa: E402


def size(n):
	return b"\x01" + n.to_bytes(7, "big")


def elem(eid, payload):
	return eid + size(len(payload)) + payload


def uint_elem(eid, value, width=1):
	return elem(eid, value.to_bytes(width, "big"))


def block(track, rel, text):
	return elem(b"\xA3", bytes([0x80 | track]) + struct.pack(">h", rel) + b"\x80" + text)


def track_entry(number, kind, codec, lang):
	return elem(b"\xAE", uint_elem(b"\xD7", number) + uint_elem(b"\x83", kind)
				+ elem(b"\x86", codec) + elem(b"\x22\xB5\x9C", lang))


def build_mkv():
	header = elem(b"\x1A\x45\xDF\xA3", elem(b"\x42\x82", b"matroska"))
	info = elem(b"\x15\x49\xA9\x66", uint_elem(b"\x2A\xD7\xB1", 1000000, 4))
	tracks = elem(b"\x16\x54\xAE\x6B",
				  track_entry(1, 2, b"A_OPUS", b"eng")
				  + track_entry(2, 17, b"S_TEXT/UTF8", b"eng")
				  + track_entry(3, 17, b"S_TEXT/UTF8", b"por"))
	cluster = elem(b"\x1F\x43\xB6\x75",
				   uint_elem(b"\xE7", 1000, 2)
				   + block(1, 0, b"audio-bytes")
				   + block(2, 0, b"Hello")
				   + block(2, 2000, b"World")
				   + block(3, 500, b"Ola"))
	segment = elem(b"\x18\x53\x80\x67", info + tracks + cluster)
	return header + segment


class RangeHandler(http.server.BaseHTTPRequestHandler):
	def do_GET(self):
		data = self.server.data
		start, end, status = 0, len(data) - 1, 200
		rng = self.headers.get("Range")
		if rng:
			m = re.match(r"bytes=(\d+)-(\d*)", rng)
			start = int(m.group(1))
			end = min(int(m.group(2)) if m.group(2) else len(data) - 1, len(data) - 1)
			status = 206
		body = data[start:end + 1]
		self.send_response(status)
		self.send_header("Content-Length", str(len(body)))
		if status == 206:
			self.send_header("Content-Range", "bytes %d-%d/%d" % (start, end, len(data)))
		self.end_headers()
		self.wfile.write(body)

	def log_message(self, *args):
		pass


class MatroskaFixtureTests(unittest.TestCase):
	def setUp(self):
		self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
		self.server.data = build_mkv()
		threading.Thread(target=self.server.serve_forever, daemon=True).start()
		self.url = "http://127.0.0.1:%d/movie.mkv" % self.server.server_address[1]

	def tearDown(self):
		self.server.shutdown()
		self.server.server_close()

	def test_reads_text_tracks_only(self):
		mkv = mkv_subs.Matroska(self.url)
		self.assertEqual([t.number for t in mkv.tracks], [2, 3])
		self.assertEqual([t.language for t in mkv.tracks], ["eng", "por"])
		self.assertEqual(mkv.track(2).codec, "S_TEXT/UTF8")

	def test_extract_english_track_to_srt(self):
		srt = mkv_subs.Matroska(self.url).extract(2)
		self.assertEqual(srt,
						 "1\n00:00:01,000 --> 00:00:03,000\nHello\n\n"
						 "2\n00:00:03,000 --> 00:00:06,000\nWorld\n")

	def test_extract_second_track_only_has_its_cues(self):
		srt = mkv_subs.Matroska(self.url).extract(3)
		self.assertIn("Ola", srt)
		self.assertNotIn("Hello", srt)
		self.assertNotIn("audio-bytes", srt)

	def test_extract_unknown_track_raises(self):
		with self.assertRaises(RuntimeError):
			mkv_subs.Matroska(self.url).extract(9)

	def test_extract_cancelled_raises(self):
		with self.assertRaises(mkv_subs.Cancelled):
			mkv_subs.Matroska(self.url).extract(2, cancelled=lambda: True)

	def test_not_matroska_rejected(self):
		self.server.data = b"\x00" * 64
		with self.assertRaises(Exception):
			mkv_subs.Matroska(self.url)


if __name__ == "__main__":
	unittest.main()
