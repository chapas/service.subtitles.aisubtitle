import html
import re
import xml.etree.ElementTree as ET


def _local(tag):
	return tag.rsplit("}", 1)[-1]


def mpd_text_tracks(mpd_xml):
	"""Return [(lang, url, mime)] for subtitle AdaptationSets in a DASH manifest."""
	root = ET.fromstring(mpd_xml)
	tracks = []
	for aset in root.iter():
		if _local(aset.tag) != "AdaptationSet":
			continue
		mime = aset.get("mimeType", "")
		if aset.get("contentType") != "text" and not mime.startswith(("text/", "application/ttml")):
			continue
		lang = aset.get("lang", "")
		for rep in aset:
			if _local(rep.tag) != "Representation":
				continue
			rmime = rep.get("mimeType", mime)
			for child in rep.iter():
				if _local(child.tag) == "BaseURL" and child.text:
					tracks.append((lang, html.unescape(child.text.strip()), rmime))
	return tracks


def _srt_time(sec):
	ms = int(round(sec * 1000))
	return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def _vtt_time(value):
	parts = value.replace(",", ".").split(":")
	sec = 0.0
	for p in parts:
		sec = sec * 60 + float(p)
	return sec


def vtt_to_srt(text):
	out = []
	prev_lines = []
	for block in re.split(r"\r?\n\r?\n", text):
		lines = block.strip().splitlines()
		for i, line in enumerate(lines):
			if "-->" in line:
				start, end = [p.strip().split(" ")[0] for p in line.split("-->")]
				body = [re.sub(r"<[^>]+>", "", l) for l in lines[i + 1:]]
				body = [l for l in body if l.strip()]
				if body and body[:len(prev_lines)] == prev_lines:
					body = body[len(prev_lines):]
				if body:
					prev_lines = body
					out.append("%d\n%s --> %s\n%s\n" % (len(out) + 1, _srt_time(_vtt_time(start)),
												 _srt_time(_vtt_time(end)), "\n".join(body)))
				break
	return "\n".join(out)


def _ttml_time(value):
	value = value.strip()
	if value.endswith("ms"):
		return float(value[:-2]) / 1000
	if value.endswith("s"):
		return float(value[:-1])
	return _vtt_time(value)


def ttml_to_srt(text):
	root = ET.fromstring(text)
	out = []
	for p in root.iter():
		if _local(p.tag) != "p" or p.get("begin") is None:
			continue
		start = _ttml_time(p.get("begin"))
		end = _ttml_time(p.get("end")) if p.get("end") else start + _ttml_time(p.get("dur", "2s"))
		parts = []
		for node in p.iter():
			if _local(node.tag) == "br":
				parts.append("\n")
			if node.text and node is p or (node.text and _local(node.tag) == "span"):
				parts.append(node.text)
			if node is not p and node.tail:
				parts.append(node.tail)
		body = "".join(parts).strip()
		if body:
			out.append("%d\n%s --> %s\n%s\n" % (len(out) + 1, _srt_time(start), _srt_time(end), body))
	return "\n".join(out)


def to_srt(text):
	stripped = text.lstrip("\ufeff \r\n")
	if stripped.startswith("WEBVTT"):
		return vtt_to_srt(stripped)
	if stripped.startswith("<"):
		return ttml_to_srt(stripped)
	return text
