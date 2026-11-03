"""Extract text subtitle tracks (tx3g) from an MP4 file over HTTP range requests.

Only the moov index and subtitle sample bytes are downloaded.
"""
import struct
import urllib.parse

from resources.lib import mkv_subs

TEXT_HANDLERS = (b"text", b"sbtl")
TEXT_CODECS = (b"tx3g",)


class Cancelled(mkv_subs.Cancelled):
	pass


def is_mp4(url):
	path = urllib.parse.urlparse(url.split("|", 1)[0]).path.lower()
	return path.endswith((".mp4", ".m4v", ".mov"))


def _header(data, pos):
	size, kind = struct.unpack(">I4s", data[pos:pos + 8])
	header = 8
	if size == 1:
		size = struct.unpack(">Q", data[pos + 8:pos + 16])[0]
		header = 16
	return kind, size, header


def boxes(data, start=0, end=None):
	end = len(data) if end is None else end
	pos = start
	while pos + 8 <= end:
		kind, size, header = _header(data, pos)
		if size == 0:
			size = end - pos
		if size < header or pos + size > end:
			return
		yield kind, pos + header, pos + size
		pos += size


def _u32(data, pos):
	return struct.unpack(">I", data[pos:pos + 4])[0]


def parse_tracks(moov):
	tracks = []
	for kind, s, e in boxes(moov):
		if kind != b"trak":
			continue
		track = {"id": None, "handler": None, "codec": None, "timescale": 1000, "lang": "und"}
		_collect_trak(moov, s, e, track)
		if track["id"] is not None and "chunk_offsets" in track:
			tracks.append(track)
	return tracks


def _collect_trak(data, s, e, track):
	for kind, cs, ce in boxes(data, s, e):
		if kind == b"tkhd":
			track["id"] = _u32(data, cs + (20 if data[cs] == 1 else 12))
		elif kind == b"mdia":
			for k2, ms, me in boxes(data, cs, ce):
				if k2 == b"mdhd":
					off = 20 if data[ms] == 1 else 12
					track["timescale"] = _u32(data, ms + off)
					code = struct.unpack(">H", data[ms + off + 4:ms + off + 6])[0]
					track["lang"] = "".join(chr(((code >> sh) & 0x1F) + 0x60) for sh in (10, 5, 0))
				elif k2 == b"hdlr":
					track["handler"] = bytes(data[ms + 8:ms + 12])
				elif k2 == b"minf":
					for k3, ss, se2 in boxes(data, ms, me):
						if k3 == b"stbl":
							_collect_stbl(data, ss, se2, track)


def _collect_stbl(data, s, e, track):
	for kind, cs, ce in boxes(data, s, e):
		if kind == b"stsd":
			entry = data[cs + 8:ce]
			if len(entry) >= 8:
				track["codec"] = bytes(entry[4:8])
		elif kind == b"stsz":
			sample_size, count = _u32(data, cs + 4), _u32(data, cs + 8)
			if sample_size:
				track["sizes"] = [sample_size] * count
			else:
				track["sizes"] = list(struct.unpack(">%dI" % count, data[cs + 12:cs + 12 + 4 * count]))
		elif kind == b"stco":
			count = _u32(data, cs + 4)
			track["chunk_offsets"] = list(struct.unpack(">%dI" % count, data[cs + 8:cs + 8 + 4 * count]))
		elif kind == b"co64":
			count = _u32(data, cs + 4)
			track["chunk_offsets"] = list(struct.unpack(">%dQ" % count, data[cs + 8:cs + 8 + 8 * count]))
		elif kind == b"stsc":
			count = _u32(data, cs + 4)
			track["stsc"] = [struct.unpack(">III", data[cs + 8 + 12 * i:cs + 20 + 12 * i]) for i in range(count)]
		elif kind == b"stts":
			count = _u32(data, cs + 4)
			track["stts"] = [struct.unpack(">II", data[cs + 8 + 8 * i:cs + 16 + 8 * i]) for i in range(count)]


def sample_table(track):
	"""Return (offset, size, start_ticks, duration_ticks) for each sample in decode order."""
	sizes = track["sizes"]
	chunk_offsets = track["chunk_offsets"]
	stsc = track["stsc"]

	locations = []
	for idx, (first_chunk, per_chunk, _) in enumerate(stsc):
		last_chunk = stsc[idx + 1][0] - 1 if idx + 1 < len(stsc) else len(chunk_offsets)
		for chunk in range(first_chunk, last_chunk + 1):
			pos = chunk_offsets[chunk - 1]
			for _ in range(per_chunk):
				if len(locations) >= len(sizes):
					break
				locations.append((pos, sizes[len(locations)]))
				pos += sizes[len(locations) - 1]

	rows = []
	t = 0
	for count, delta in track["stts"]:
		for _ in range(count):
			if len(rows) >= len(locations):
				return rows
			rows.append((locations[len(rows)][0], locations[len(rows)][1], t, delta))
			t += delta
	return rows


def decode_sample(payload):
	"""tx3g sample: 2-byte big-endian length, UTF-8 text, then optional style boxes."""
	if len(payload) < 2:
		return ""
	length = struct.unpack(">H", payload[:2])[0]
	return bytes(payload[2:2 + length]).decode("utf-8", "replace")


class Mp4:
	def __init__(self, url, cancelled=lambda: False):
		self.file = mkv_subs.HttpFile(url)
		self.cancelled = cancelled
		self.tracks = parse_tracks(self._find_moov())
		if not self.tracks:
			raise RuntimeError("No tracks in MP4")

	def _find_moov(self):
		pos = 0
		while True:
			head = self.file.read(pos, 16)
			if len(head) < 8:
				break
			kind, size, header = _header(head, 0)
			if kind == b"moov":
				return self.file.read(pos + header, size - header)
			if size < header:
				break
			pos += size
		raise RuntimeError("Not an MP4 file")

	def text_tracks(self):
		return [t for t in self.tracks if t["handler"] in TEXT_HANDLERS or t["codec"] in TEXT_CODECS]

	def extract(self, track_id):
		track = next((t for t in self.tracks if t["id"] == track_id), None)
		if track is None:
			raise RuntimeError("Unknown MP4 track %s" % track_id)
		events = []
		for offset, size, start, duration in sample_table(track):
			if self.cancelled():
				raise Cancelled()
			text = decode_sample(self.file.read(offset, size)).strip()
			if not text:
				continue
			start_ms = int(start * 1000 / track["timescale"])
			dur_ms = max(1, int(duration * 1000 / track["timescale"]))
			events.append((start_ms, dur_ms, text))
		return events
