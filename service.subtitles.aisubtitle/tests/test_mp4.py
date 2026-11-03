import http.server
import os
import struct
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from resources.lib import mp4_extract  # noqa: E402
from test_mkv_fixture import RangeHandler  # noqa: E402


def box(kind, payload):
	return struct.pack(">I4s", 8 + len(payload), kind) + payload


def full_box(kind, payload, version=0):
	return box(kind, bytes([version, 0, 0, 0]) + payload)


def tkhd(track_id):
	return full_box(b"tkhd", b"\0" * 8 + struct.pack(">I", track_id) + b"\0" * 68)


def mdhd(timescale, lang="eng"):
	packed = 0
	for ch in lang:
		packed = (packed << 5) | (ord(ch) - 0x60)
	return full_box(b"mdhd", b"\0" * 8 + struct.pack(">I", timescale) + struct.pack(">HH", packed, 0))


def hdlr(handler):
	return full_box(b"hdlr", b"\0" * 4 + handler + b"\0" * 13)


def stsd(codec):
	entry = struct.pack(">I", 8 + 6 + 2) + codec + b"\0" * 8
	return full_box(b"stsd", struct.pack(">I", 1) + entry)


def stbl(codec, sizes, offset, durations):
	stsz = full_box(b"stsz", struct.pack(">II", 0, len(sizes)) + b"".join(struct.pack(">I", s) for s in sizes))
	stsc = full_box(b"stsc", struct.pack(">I", 1) + struct.pack(">III", 1, len(sizes), 1))
	stco = full_box(b"stco", struct.pack(">II", 1, offset))
	stts = full_box(b"stts", struct.pack(">I", len(durations)) + b"".join(struct.pack(">II", 1, d) for d in durations))
	return box(b"stbl", stsd(codec) + stts + stsc + stsz + stco)


def trak(track_id, handler, codec, sizes, offset, durations, timescale=1000, lang="eng"):
	return box(b"trak", tkhd(track_id) + box(b"mdia", mdhd(timescale, lang) + hdlr(handler)
			+ box(b"minf", stbl(codec, sizes, offset, durations))))


def tx3g(text):
	raw = text.encode("utf-8")
	return struct.pack(">H", len(raw)) + raw


def build_mp4():
	ftyp = box(b"ftyp", b"isom\0\0\2\0isomiso2mp41")
	video_samples = [b"\x00" * 64, b"\x00" * 64]
	sub_samples = [tx3g("Hello"), tx3g(""), tx3g("World")]

	def moov_for(mdat_data):
		video_at = mdat_data
		sub_at = mdat_data + sum(len(s) for s in video_samples)
		return box(b"moov",
				   trak(1, b"vide", b"avc1", [len(s) for s in video_samples], video_at, [1000, 1000])
				   + trak(2, b"text", b"tx3g", [len(s) for s in sub_samples], sub_at, [1000, 1000, 1000]))

	mdat_data = len(ftyp) + len(moov_for(0)) + 8
	moov = moov_for(mdat_data)
	return ftyp + moov + box(b"mdat", b"".join(video_samples) + b"".join(sub_samples))


class Mp4FixtureTests(unittest.TestCase):
	def setUp(self):
		self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
		self.server.data = build_mp4()
		threading.Thread(target=self.server.serve_forever, daemon=True).start()
		self.url = "http://127.0.0.1:%d/movie.mp4" % self.server.server_address[1]

	def tearDown(self):
		self.server.shutdown()
		self.server.server_close()

	def test_reads_text_tracks_only(self):
		mp4 = mp4_extract.Mp4(self.url)
		self.assertEqual([t["id"] for t in mp4.text_tracks()], [2])

	def test_extract_text_track_skips_empty_samples(self):
		events = mp4_extract.Mp4(self.url).extract(2)
		self.assertEqual([e[2] for e in events], ["Hello", "World"])
		self.assertEqual(events[0][:2], (0, 1000))
		self.assertEqual(events[1][:2], (2000, 1000))

	def test_parses_track_language(self):
		self.assertEqual(mp4_extract.Mp4(self.url).text_tracks()[0]["lang"], "eng")

	def test_extract_unknown_track_raises(self):
		with self.assertRaises(RuntimeError):
			mp4_extract.Mp4(self.url).extract(9)

	def test_extract_cancelled_raises(self):
		with self.assertRaises(mp4_extract.Cancelled):
			mp4_extract.Mp4(self.url, cancelled=lambda: True).extract(2)

	def test_not_mp4_rejected(self):
		self.server.data = b"\x00" * 64
		with self.assertRaises(Exception):
			mp4_extract.Mp4(self.url)

	def test_is_mp4(self):
		self.assertTrue(mp4_extract.is_mp4("http://x/movie.mp4|Range=1"))
		self.assertFalse(mp4_extract.is_mp4("http://x/movie.mkv"))


if __name__ == "__main__":
	unittest.main()
