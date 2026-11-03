import json
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor

PROMPT = ("Translate to {language} the subtitle lines for the movie. Each line starts with an id like [12]. "
		  "Return every line with the same id prefix, translated, one per line, in the same order. "
		  "Keep <br> markers. No explanations, no code blocks.")
FILE_PROMPT = ("Translate to {language} the subtitle file for the movie. Return only the subtitle in the same "
			   "format, keeping numbering and timestamps unchanged. No explanations, no code blocks.")

_BLOCK_SPLIT = re.compile(r"\r?\n\s*\r?\n")
_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n?|\n?```\s*$")
_TIMING = re.compile(r"\d+:\d+:\d+[,.]\d+\s*-->\s*\d+:\d+:\d+[,.]\d+")
_LINE_ID = re.compile(r"^\s*\[(\d+)\]\s?(.*)$")


def clean_response(text):
	return _FENCE.sub("", text.strip()).strip()


def parse_srt(text):
	"""Return list of (timing, text) cues, or None if the text is not SRT."""
	cues = []
	for block in _BLOCK_SPLIT.split(text.strip()):
		lines = [l for l in block.splitlines() if l.strip() != ""]
		idx = next((i for i, l in enumerate(lines) if _TIMING.search(l)), None)
		if idx is None:
			continue
		cues.append((lines[idx].strip(), "\n".join(lines[idx + 1:])))
	return cues or None


def build_srt(cues):
	return "\n\n".join("%d\n%s\n%s" % (i + 1, t, txt) for i, (t, txt) in enumerate(cues)) + "\n"


def parse_headers(text):
	headers = {}
	for part in re.split(r"[;\n]", text or ""):
		if ":" in part:
			name, value = part.split(":", 1)
			if name.strip():
				headers[name.strip()] = value.strip()
	return headers


def call_api(api_url, api_key, model, system, content, timeout=300, opener=urllib.request.urlopen, extra_headers=None,
             on_request=None):
	url = api_url.rstrip("/")
	if not url.endswith("/chat/completions"):
		url += "/chat/completions"
	body = {
		"model": model,
		"temperature": 0,
		"messages": [
			{"role": "system", "content": system},
			{"role": "user", "content": content},
		],
	}
	headers = {"Content-Type": "application/json"}
	if api_key:
		headers["Authorization"] = "Bearer " + api_key
	headers.update(extra_headers or {})
	if on_request:
		on_request(url, headers, body)
	req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
	with opener(req, timeout=timeout) as resp:
		data = json.loads(resp.read().decode("utf-8"))
	return clean_response(data["choices"][0]["message"]["content"])


def _chunks(items, size):
	return [items[i:i + size] for i in range(0, len(items), size)]


def translate_subtitle(text, language, api_url, api_key, model, timeout=300, opener=urllib.request.urlopen,
					   progress=None, extra_headers=None, chunk_size=150, workers=4, on_request=None):
	cues = parse_srt(text)
	if cues:
		system = PROMPT.format(language=language)
		parts = _chunks(list(enumerate(cues)), chunk_size)

		def work(part):
			payload = "\n".join("[%d] %s" % (i, c[1].replace("\n", " <br> ")) for i, c in part)
			reply = call_api(api_url, api_key, model, system, payload, timeout, opener, extra_headers, on_request)
			result = {}
			for line in reply.splitlines():
				m = _LINE_ID.match(line)
				if m:
					result[int(m.group(1))] = re.sub(r"\s*<br>\s*", "\n", m.group(2).strip())
			return result
	else:
		system = FILE_PROMPT.format(language=language)
		blocks = [b.strip() for b in _BLOCK_SPLIT.split(text.strip()) if b.strip()]
		parts = ["\n\n".join(p) for p in _chunks(blocks, chunk_size)]

		def work(part):
			return call_api(api_url, api_key, model, system, part, timeout, opener, extra_headers, on_request)

	done = [0]

	def tracked(part):
		res = work(part)
		done[0] += 1
		if progress:
			progress(done[0], len(parts))
		return res

	if progress:
		progress(0, len(parts))
	with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
		results = list(pool.map(tracked, parts))

	if not cues:
		return "\n\n".join(results) + "\n"
	translated = {}
	for r in results:
		translated.update(r)
	return build_srt([(t, translated.get(i) or txt) for i, (t, txt) in enumerate(cues)])


def decode_bytes(raw):
	for enc in ("utf-8-sig", "cp1252", "latin-1"):
		try:
			return raw.decode(enc)
		except UnicodeDecodeError:
			continue
	return raw.decode("utf-8", "ignore")
