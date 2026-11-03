import json
import re
import time
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
INNERTUBE_URL = "https://www.youtube.com/youtubei/v1/player?prettyPrint=false"
CLIENTS = (
	({"clientName": "VISIONOS", "clientVersion": "1.02", "deviceMake": "Apple", "deviceModel": "RealityDevice17,1",
	  "userAgent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_7_3) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15",
	  "osName": "visionOS", "osVersion": "26.5.23O471"}, "101"),
	({"clientName": "WEB", "clientVersion": "2.20240726.00.00"}, "1"),
)


def _get(url, data=None, headers=None, opener=urllib.request.urlopen, timeout=15, retries=2):
	hdrs = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
	hdrs.update(headers or {})
	last = None
	for attempt in range(retries + 1):
		try:
			req = urllib.request.Request(url, data=data, headers=hdrs)
			with opener(req, timeout=timeout) as resp:
				return resp.read().decode("utf-8", "ignore")
		except Exception as exc:
			last = exc
			if attempt >= retries:
				raise
			time.sleep(min(2.0, 0.5 * (attempt + 1)))
	raise last


def _tracks_from_player(player):
	renderer = (player.get("captions") or {}).get("playerCaptionsTracklistRenderer") or {}
	tracks = []
	for t in renderer.get("captionTracks") or []:
		name = t.get("name") or {}
		label = name.get("simpleText") or "".join(r.get("text", "") for r in name.get("runs", []))
		tracks.append({
			"lang": t.get("languageCode", ""),
			"name": label,
			"auto": t.get("kind") == "asr",
			"url": t.get("baseUrl", ""),
		})
	return [t for t in tracks if t["url"]]


def visitor_data(video_id, opener=urllib.request.urlopen):
	page = _get("https://www.youtube.com/watch?v=%s&hl=en" % video_id, opener=opener)
	match = re.search(r'"VISITOR_DATA":"([^"]+)"', page)
	return match.group(1) if match else ""


def caption_tracks(video_id, opener=urllib.request.urlopen, log=None):
	"""Caption tracks for a YouTube video, like yt-dlp's subtitle extraction."""
	try:
		visitor = visitor_data(video_id, opener)
	except Exception as exc:
		visitor = ""
		if log:
			log("Visitor data failed: %r" % exc)
	for client, client_id in CLIENTS:
		context = dict(client, hl="en")
		headers = {
			"Content-Type": "application/json",
			"Origin": "https://www.youtube.com",
			"X-YouTube-Client-Name": client_id,
			"X-YouTube-Client-Version": client["clientVersion"],
		}
		if visitor:
			context["visitorData"] = visitor
			headers["X-Goog-Visitor-Id"] = visitor
		body = json.dumps({"context": {"client": context}, "videoId": video_id,
						   "contentCheckOk": True, "racyCheckOk": True}).encode("utf-8")
		if client.get("userAgent"):
			headers["User-Agent"] = client["userAgent"]
		try:
			player = json.loads(_get(INNERTUBE_URL, body, headers, opener))
			tracks = _tracks_from_player(player)
			if log:
				log("InnerTube %s: %s, %d caption tracks" % (
					client["clientName"], (player.get("playabilityStatus") or {}).get("status"), len(tracks)))
			if tracks:
				return tracks
		except Exception as exc:
			if log:
				log("InnerTube %s failed: %r" % (client["clientName"], exc))
	return []


def pick_track(tracks, preferred_codes=()):
	def rank(t):
		base = t["lang"].split("-")[0].lower()
		return (0 if base in preferred_codes or t["lang"].lower() in preferred_codes else 1,
				1 if t["auto"] else 0,
				0 if base == "en" else 1)
	return sorted(tracks, key=rank)[0] if tracks else None


def download_vtt(track, opener=urllib.request.urlopen):
	url = track["url"]
	parts = urllib.parse.urlsplit(url)
	query = [(k, v) for k, v in urllib.parse.parse_qsl(parts.query) if k != "fmt"] + [("fmt", "vtt")]
	candidates = [
		urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query))),
		url + ("&fmt=vtt" if "?" in url else "?fmt=vtt"),
	]
	last = None
	for candidate in candidates:
		try:
			text = _get(candidate, opener=opener, timeout=30, retries=4)
			if text.strip():
				return text
		except Exception as exc:
			last = exc
	if last:
		raise last
	return ""
