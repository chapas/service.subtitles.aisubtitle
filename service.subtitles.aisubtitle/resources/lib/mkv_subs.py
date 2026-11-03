"""Extract text subtitle tracks from a Matroska/WebM file over HTTP range requests.

Only the bytes that hold subtitles are downloaded when the file has a Cues index
pointing at the subtitle blocks (mkvmerge does this by default). Otherwise the
file is streamed once and only subtitle blocks are kept.
"""
import http.client
import re
import ssl
import struct
import threading
import urllib.parse
import zlib
from concurrent.futures import ThreadPoolExecutor

SEGMENT = 0x18538067
SEEK_HEAD, SEEK, SEEK_ID, SEEK_POS = 0x114D9B74, 0x4DBB, 0x53AB, 0x53AC
INFO, TIMECODE_SCALE = 0x1549A966, 0x2AD7B1
TRACKS, TRACK_ENTRY, TRACK_NUMBER, TRACK_TYPE, CODEC_ID = 0x1654AE6B, 0xAE, 0xD7, 0x83, 0x86
LANGUAGE, LANGUAGE_IETF, NAME, FLAG_FORCED = 0x22B59C, 0x22B59D, 0x536E, 0x55AA
CONTENT_ENCODINGS, CONTENT_ENCODING, CONTENT_COMPRESSION = 0x6D80, 0x6240, 0x5034
COMP_ALGO, COMP_SETTINGS = 0x4254, 0x4255
CUES, CUE_POINT, CUE_TIME, CUE_TRACK_POS = 0x1C53BB6B, 0xBB, 0xB3, 0xB7
CUE_TRACK, CUE_CLUSTER_POS, CUE_REL_POS, CUE_DURATION = 0xF7, 0xF1, 0xF0, 0xB2
CLUSTER, TIMECODE, SIMPLE_BLOCK, BLOCK_GROUP, BLOCK, BLOCK_DURATION = 0x1F43B675, 0xE7, 0xA3, 0xA0, 0xA1, 0x9B

TEXT_CODECS = ("S_TEXT/UTF8", "S_TEXT/ASCII", "S_TEXT/ASS", "S_TEXT/SSA", "S_TEXT/WEBVTT", "S_ASS", "S_SSA")
UNKNOWN = -1


class Cancelled(Exception):
	pass


def is_matroska(url):
	path = urllib.parse.urlparse(url.split("|", 1)[0]).path.lower()
	return path.endswith((".mkv", ".mk3d", ".webm"))


def split_kodi_url(url):
	"""Kodi appends request headers after '|' as a query string."""
	base, _, extra = url.partition("|")
	headers = {k: v for k, v in urllib.parse.parse_qsl(extra)} if extra else {}
	headers.setdefault("User-Agent", "Mozilla/5.0")
	return base, headers


def read_vint(data, pos, keep_marker=False):
	first = data[pos]
	length = 1
	mask = 0x80
	while length <= 8 and not first & mask:
		mask >>= 1
		length += 1
	if length > 8:
		raise ValueError("Bad EBML vint at %d" % pos)
	value = first if keep_marker else first & (mask - 1)
	for b in data[pos + 1:pos + length]:
		value = (value << 8) | b
	if not keep_marker and value == (1 << (7 * length)) - 1:
		value = UNKNOWN
	return value, length


def read_header(data, pos):
	"""Return (element id, data size, header length)."""
	eid, a = read_vint(data, pos, keep_marker=True)
	size, b = read_vint(data, pos + a)
	return eid, size, a + b


def children(data):
	pos = 0
	while pos < len(data):
		try:
			eid, size, hl = read_header(data, pos)
		except (IndexError, ValueError):
			return
		if size == UNKNOWN:
			size = len(data) - pos - hl
		yield eid, data[pos + hl:pos + hl + size]
		pos += hl + size


def uint(data):
	value = 0
	for b in data:
		value = (value << 8) | b
	return value


def text(data):
	return data.split(b"\0", 1)[0].decode("utf-8", "replace")


class HttpFile:
	"""Random access reads with one keep-alive connection per thread."""

	def __init__(self, url, timeout=20):
		self.url, self.headers = split_kodi_url(url)
		self.timeout = timeout
		self.local = threading.local()

	def _connection(self, parts):
		key = (parts.scheme, parts.netloc)
		conn = getattr(self.local, "conn", None)
		if conn is None or getattr(self.local, "key", None) != key:
			if parts.scheme == "https":
				conn = http.client.HTTPSConnection(parts.netloc, timeout=self.timeout, context=ssl.create_default_context())
			else:
				conn = http.client.HTTPConnection(parts.netloc, timeout=self.timeout)
			self.local.conn, self.local.key = conn, key
		return conn

	def _get(self, extra, stream=False):
		url = self.url
		for attempt in range(6):
			parts = urllib.parse.urlparse(url)
			conn = self._connection(parts)
			path = parts.path + ("?" + parts.query if parts.query else "")
			try:
				conn.request("GET", path, headers=dict(self.headers, **extra))
				resp = conn.getresponse()
			except (http.client.HTTPException, OSError):
				conn.close()
				self.local.conn = None
				if attempt >= 2:
					raise
				continue
			if resp.status in (301, 302, 303, 307, 308):
				resp.read()
				url = urllib.parse.urljoin(url, resp.getheader("Location"))
				self.url = url
				continue
			if resp.status not in (200, 206):
				resp.read()
				raise RuntimeError("HTTP %d reading video" % resp.status)
			if not stream and resp.status == 200 and "Range" in extra:
				resp.close()
				self.local.conn = None
				raise RuntimeError("Server does not support range requests")
			return resp
		raise RuntimeError("Too many redirects")

	def read(self, offset, length):
		resp = self._get({"Range": "bytes=%d-%d" % (offset, offset + length - 1)})
		return resp.read()

	def stream(self, offset):
		return self._get({"Range": "bytes=%d-" % offset}, stream=True)


class Track:
	def __init__(self, number, codec, language, name, forced, encodings):
		self.number = number
		self.codec = codec
		self.language = language
		self.name = name
		self.forced = forced
		self.encodings = encodings

	def decode(self, payload):
		for algo, settings in self.encodings:
			if algo == 3:
				payload = settings + payload
			elif algo == 0:
				payload = zlib.decompress(payload)
		return payload


class Matroska:
	def __init__(self, url, log=None):
		self.file = HttpFile(url)
		self.log = log or (lambda msg: None)
		self.scale = 1000000
		self.tracks = []
		self.cues_pos = None
		self.segment_start = 0
		self.first_cluster = None
		self._open()

	def _open(self):
		head = self.file.read(0, 64 * 1024)
		pos = 0
		eid, size, hl = read_header(head, pos)
		pos += hl + size
		eid, size, hl = read_header(head, pos)
		if eid != SEGMENT:
			raise RuntimeError("Not a Matroska file")
		self.segment_start = pos + hl
		positions = {}
		pos = self.segment_start
		# Walk the top level elements found in the first chunk.
		while pos + 12 <= len(head):
			eid, size, hl = read_header(head, pos)
			if eid == CLUSTER:
				self.first_cluster = pos
				break
			positions.setdefault(eid, pos)
			if eid == SEEK_HEAD:
				for seek_id, seek_pos in self._seek_entries(self._element(head, pos)):
					positions.setdefault(seek_id, self.segment_start + seek_pos)
			if size == UNKNOWN:
				break
			pos += hl + size
		if INFO in positions:
			for cid, data in children(self._element(head, positions[INFO])):
				if cid == TIMECODE_SCALE:
					self.scale = uint(data)
		if TRACKS not in positions:
			raise RuntimeError("No Tracks element")
		self.tracks = self._parse_tracks(self._element(head, positions[TRACKS]))
		self.cues_pos = positions.get(CUES)

	def _element(self, head, pos):
		"""Return the payload of the element at pos, reading more if needed."""
		if pos + 16 <= len(head):
			eid, size, hl = read_header(head, pos)
			if pos + hl + size <= len(head):
				return head[pos + hl:pos + hl + size]
		chunk = self.file.read(pos, 16)
		eid, size, hl = read_header(chunk, 0)
		return self.file.read(pos + hl, size)

	@staticmethod
	def _seek_entries(data):
		for eid, seek in children(data):
			if eid != SEEK:
				continue
			seek_id = seek_pos = None
			for cid, value in children(seek):
				if cid == SEEK_ID:
					seek_id = uint(value)
				elif cid == SEEK_POS:
					seek_pos = uint(value)
			if seek_id is not None and seek_pos is not None:
				yield seek_id, seek_pos

	@staticmethod
	def _parse_tracks(data):
		tracks = []
		for eid, entry in children(data):
			if eid != TRACK_ENTRY:
				continue
			info = {"lang": "eng", "name": "", "forced": False, "enc": [], "type": 0, "codec": "", "number": 0}
			for cid, value in children(entry):
				if cid == TRACK_NUMBER:
					info["number"] = uint(value)
				elif cid == TRACK_TYPE:
					info["type"] = uint(value)
				elif cid == CODEC_ID:
					info["codec"] = text(value)
				elif cid == LANGUAGE:
					info["lang"] = text(value)
				elif cid == LANGUAGE_IETF:
					info["ietf"] = text(value)
				elif cid == NAME:
					info["name"] = text(value)
				elif cid == FLAG_FORCED:
					info["forced"] = bool(uint(value))
				elif cid == CONTENT_ENCODINGS:
					for _, enc in children(value):
						for eid2, comp in children(enc):
							if eid2 != CONTENT_COMPRESSION:
								continue
							algo, settings = 0, b""
							for cid2, v2 in children(comp):
								if cid2 == COMP_ALGO:
									algo = uint(v2)
								elif cid2 == COMP_SETTINGS:
									settings = v2
							info["enc"].append((algo, settings))
			if info["type"] == 17 and info["codec"] in TEXT_CODECS:
				lang = info.get("ietf") or info["lang"]
				tracks.append(Track(info["number"], info["codec"], lang, info["name"], info["forced"], info["enc"]))
		return tracks

	def track(self, number):
		return next((t for t in self.tracks if t.number == number), None)

	def extract(self, number, cancelled=None):
		self.cancelled = cancelled or (lambda: False)
		track = self.track(number)
		if not track:
			raise RuntimeError("Subtitle track %d not found" % number)
		events = self._extract_with_cues(track) if self.cues_pos else None
		if not events:
			self.log("No usable cues for track %d, scanning the whole file" % number)
			events = self._extract_by_scan(track)
		return to_srt(events, track.codec)

	def _extract_with_cues(self, track):
		points = []
		for eid, point in children(self._element(b"", self.cues_pos)):
			if eid != CUE_POINT:
				continue
			time = None
			for cid, value in children(point):
				if cid == CUE_TIME:
					time = uint(value)
				elif cid == CUE_TRACK_POS:
					fields = {k: uint(v) for k, v in children(value)}
					if fields.get(CUE_TRACK) == track.number and CUE_CLUSTER_POS in fields:
						points.append((time, fields.get(CUE_CLUSTER_POS), fields.get(CUE_REL_POS), fields.get(CUE_DURATION)))
		if not points or any(p[2] is None for p in points):
			return None
		self.log("Reading %d subtitle blocks for track %d using the cues index" % (len(points), track.number))
		cluster_headers = {}
		lock = threading.Lock()

		def cluster_data_start(cluster_pos):
			with lock:
				if cluster_pos in cluster_headers:
					return cluster_headers[cluster_pos]
			absolute = self.segment_start + cluster_pos
			_, _, hl = read_header(self.file.read(absolute, 16), 0)
			with lock:
				cluster_headers[cluster_pos] = absolute + hl
			return absolute + hl

		def fetch(point):
			if self.cancelled():
				raise Cancelled()
			time, cluster_pos, rel, cue_duration = point
			absolute = self.segment_start + cluster_pos
			# The cluster header is 5-12 bytes; read past it and the block in one request.
			chunk = self.file.read(absolute + rel, 4096 + 12)
			for hl_cluster in range(5, 13):
				pos = hl_cluster
				if pos >= len(chunk) or chunk[pos] not in (BLOCK_GROUP, SIMPLE_BLOCK):
					continue
				try:
					eid, size, hl = read_header(chunk, pos)
					if eid not in (BLOCK_GROUP, SIMPLE_BLOCK) or size <= 0 or size > 1024 * 1024:
						continue
					if pos + hl + size > len(chunk):
						chunk = chunk[:pos] + self.file.read(absolute + rel + pos, hl + size)
					payload = chunk[pos + hl:pos + hl + size]
					if eid == BLOCK_GROUP:
						event = self._block_group(track, payload, time, cue_duration)
					else:
						event = self._block(track, payload, time, cue_duration)
				except (IndexError, ValueError, struct.error, zlib.error):
					continue
				if event:
					return event
			start = cluster_data_start(cluster_pos) + rel
			chunk = self.file.read(start, 4096)
			eid, size, hl = read_header(chunk, 0)
			if hl + size > len(chunk):
				chunk = self.file.read(start, hl + size)
			payload = chunk[hl:hl + size]
			if eid == BLOCK_GROUP:
				return self._block_group(track, payload, time, cue_duration)
			if eid == SIMPLE_BLOCK:
				return self._block(track, payload, time, cue_duration)
			return None

		with ThreadPoolExecutor(max_workers=32) as pool:
			results = list(pool.map(fetch, points))
		return [r for r in results if r]

	def _block(self, track, payload, absolute_time=None, duration=None, cluster_time=0):
		number, n = read_vint(payload, 0)
		if number != track.number:
			return None
		relative = struct.unpack(">h", payload[n:n + 2])[0]
		time = absolute_time if absolute_time is not None else cluster_time + relative
		data = track.decode(bytes(payload[n + 3:]))
		return [self._ms(time), self._ms(duration) if duration else None, data]

	def _block_group(self, track, payload, absolute_time=None, duration=None, cluster_time=0):
		block = None
		for cid, value in children(payload):
			if cid == BLOCK:
				block = value
			elif cid == BLOCK_DURATION:
				duration = uint(value)
		if block is None:
			return None
		return self._block(track, block, absolute_time, duration, cluster_time)

	def _ms(self, ticks):
		return int(ticks * self.scale / 1000000)

	def _extract_by_scan(self, track):
		start = self.first_cluster or self.segment_start
		resp = self.file.stream(start)
		reader = StreamReader(resp)
		events = []
		cluster_time = 0
		try:
			while True:
				if self.cancelled():
					raise Cancelled()
				head = reader.peek(12)
				if len(head) < 2:
					break
				eid, size, hl = read_header(head, 0)
				reader.skip(hl)
				if eid in (SEGMENT, CLUSTER):
					continue
				if size == UNKNOWN:
					break
				if eid == TIMECODE:
					cluster_time = uint(reader.read(size))
				elif eid == SIMPLE_BLOCK:
					number, _ = read_vint(reader.peek(8), 0)
					if number == track.number:
						event = self._block(track, reader.read(size), cluster_time=cluster_time)
						if event:
							events.append(event)
					else:
						reader.skip(size)
				elif eid == BLOCK_GROUP and size < 4 * 1024 * 1024:
					event = self._block_group(track, reader.read(size), cluster_time=cluster_time)
					if event:
						events.append(event)
				else:
					reader.skip(size)
		finally:
			resp.close()
		return events


class StreamReader:
	def __init__(self, resp):
		self.resp = resp
		self.buffer = b""

	def _fill(self, n):
		while len(self.buffer) < n:
			chunk = self.resp.read(max(n - len(self.buffer), 256 * 1024))
			if not chunk:
				break
			self.buffer += chunk

	def peek(self, n):
		self._fill(n)
		return self.buffer[:n]

	def read(self, n):
		self._fill(n)
		data, self.buffer = self.buffer[:n], self.buffer[n:]
		return data

	def skip(self, n):
		if n <= len(self.buffer):
			self.buffer = self.buffer[n:]
			return
		n -= len(self.buffer)
		self.buffer = b""
		while n > 0:
			chunk = self.resp.read(min(n, 1024 * 1024))
			if not chunk:
				break
			n -= len(chunk)


def _clean(codec, data):
	value = data.decode("utf-8", "replace").strip("\0").strip()
	if codec in ("S_TEXT/ASS", "S_TEXT/SSA", "S_ASS", "S_SSA"):
		value = value.split(",", 8)[-1]
		value = re.sub(r"\{[^}]*\}", "", value).replace("\\N", "\n").replace("\\n", "\n").replace("\\h", " ")
	elif codec == "S_TEXT/WEBVTT":
		value = re.sub(r"<[^>]+>", "", value)
	return value.strip()


def _srt_time(ms):
	ms = max(0, int(ms))
	return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def to_srt(events, codec):
	events = sorted(events, key=lambda e: e[0])
	out = []
	for i, (start, duration, data) in enumerate(events):
		body = _clean(codec, data)
		if not body:
			continue
		if not duration:
			following = events[i + 1][0] if i + 1 < len(events) else start + 3000
			duration = max(500, min(following - start, 5000))
		out.append("%d\n%s --> %s\n%s\n" % (len(out) + 1, _srt_time(start), _srt_time(start + duration), body))
	return "\n".join(out)
