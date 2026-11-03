import urllib.error
import http.client
import json
import re
import socket
import ssl
import threading
import urllib.parse
import urllib.request


class Cancelled(Exception):
	pass

FILE_PROMPT = ("You are a professional subtitle translator. You receive one complete SRT subtitle file "
			   "(SubRip format used by Kodi) from a video. Each cue is: a sequence number line, a timing line "
			   "'HH:MM:SS,mmm --> HH:MM:SS,mmm', one or more dialogue lines, then a blank line.\n"
			   "Task: translate only the dialogue lines to {language}.\n"
			   "Rules:\n"
			   "- Copy every sequence number and timing line exactly; never merge, split, drop or reorder cues.\n"
			   "- Keep the same number of dialogue lines per cue, and keep tags like <i>, {{\\an8}}, '- ' and '[music]' markers.\n"
			   "- Translate naturally and concisely for reading on screen; do not explain or comment.\n"
			   "- Output only the translated SRT file, starting with '1', with no code fences or extra text.")
_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n?|\n?```\s*$")


def clean_response(text):
	return _FENCE.sub("", text.strip()).strip()


def parse_headers(text):
	headers = {}
	for part in re.split(r"[;\n]", text or ""):
		if ":" in part:
			name, value = part.split(":", 1)
			if name.strip():
				headers[name.strip()] = value.strip()
	return headers


def extract_content(data):
	msg = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "")
	if isinstance(msg, str):
		return msg
	if isinstance(msg, list):
		parts = []
		for item in msg:
			if isinstance(item, dict) and item.get("type") in ("text", "output_text") and item.get("text"):
				parts.append(item["text"])
		return "\n".join(parts)
	return str(msg)


def post_cancellable(url, data, headers, timeout, cancelled, poll=0.25):
	"""POST on a worker thread; closes the socket as soon as cancelled() returns True."""
	parts = urllib.parse.urlparse(url)
	if parts.scheme == "https":
		conn = http.client.HTTPSConnection(parts.netloc, timeout=timeout, context=ssl.create_default_context())
	else:
		conn = http.client.HTTPConnection(parts.netloc, timeout=timeout)
	result = {}

	def work():
		try:
			conn.request("POST", parts.path + ("?" + parts.query if parts.query else ""), body=data, headers=headers)
			resp = conn.getresponse()
			result["status"] = resp.status
			result["raw"] = resp.read().decode("utf-8", "ignore")
		except Exception as exc:
			result["error"] = exc

	worker = threading.Thread(target=work, daemon=True)
	worker.start()
	while worker.is_alive():
		worker.join(poll)
		if worker.is_alive() and cancelled():
			sock = conn.sock
			if sock is not None:
				try:
					sock.shutdown(socket.SHUT_RDWR)
				except OSError:
					pass
			conn.close()
			raise Cancelled("Translation cancelled")
	conn.close()
	if "error" in result:
		raise result["error"]
	return result["status"], result["raw"]


def prompt_language(language):
	if language == "Portuguese":
		return "European Portuguese (Portugal)"
	return language


def call_api(api_url, api_key, model, language, subtitle_text, source_name, timeout=300,
			 opener=urllib.request.urlopen, extra_headers=None, on_request=None, on_response=None, cancelled=None):
	url = api_url.rstrip("/")
	if not url.endswith("/chat/completions"):
		url += "/chat/completions"
	body = {
		"model": model,
		"temperature": 0,
		"messages": [
			{"role": "system", "content": FILE_PROMPT.format(language=prompt_language(language))},
			{
				"role": "user",
				"content": [
					{"type": "text", "text": "SRT file '%s' to translate to %s:" % (source_name or "subtitle.srt", language)},
					{"type": "text", "text": subtitle_text},
				],
			},
		],
	}
	headers = {"Content-Type": "application/json"}
	if api_key:
		headers["Authorization"] = "Bearer " + api_key
	headers.update(extra_headers or {})
	if on_request:
		on_request(url, headers, body)
	if cancelled is not None:
		status, raw = post_cancellable(url, json.dumps(body).encode("utf-8"), headers, timeout, cancelled)
		if on_response:
			on_response(status, raw)
		if status != 200:
			raise RuntimeError("HTTP %s: %s" % (status, raw[:300]))
		return clean_response(extract_content(json.loads(raw)))
	req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
	try:
		with opener(req, timeout=timeout) as resp:
			raw = resp.read().decode("utf-8")
		if on_response:
			on_response(200, raw)
		data = json.loads(raw)
	except urllib.error.HTTPError as exc:
		err = exc.read().decode("utf-8", "ignore")
		if on_response:
			on_response(exc.code, err)
		raise RuntimeError("HTTP %s: %s" % (exc.code, err[:300]))
	return clean_response(extract_content(data))


def translate_subtitle(text, language, api_url, api_key, model, timeout=300, opener=urllib.request.urlopen,
					   progress=None, extra_headers=None, on_request=None, source_name="subtitle.srt", on_response=None,
					   cancelled=None):
					   if progress:
						   progress(0, 1)
					   out = call_api(api_url, api_key, model, language, text, source_name, timeout, opener, extra_headers,
									  on_request, on_response, cancelled)
					   if progress:
						   progress(1, 1)
					   return out.rstrip("\n") + "\n"


def check_connection(api_url, api_key, timeout=15, opener=urllib.request.urlopen):
	url = api_url.rstrip("/") + "/models"
	headers = {}
	if api_key:
		headers["Authorization"] = "Bearer " + api_key
	req = urllib.request.Request(url, headers=headers, method="GET")
	try:
		with opener(req, timeout=timeout) as resp:
			resp.read()
	except urllib.error.HTTPError as exc:
		raise RuntimeError("HTTP %s: %s" % (exc.code, exc.read().decode("utf-8", "ignore")[:300]))
	return True


def decode_bytes(raw):
	for enc in ("utf-8-sig", "cp1252", "latin-1"):
		try:
			return raw.decode(enc)
		except UnicodeDecodeError:
			continue
	return raw.decode("utf-8", "ignore")
