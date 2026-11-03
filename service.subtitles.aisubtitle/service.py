import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from resources.lib import translator_file as translator
from resources.lib import stream_subs
from resources.lib import youtube_captions
from resources.lib import mkv_subs
from resources.lib import mp4_extract
from resources.lib import cache
from resources.lib import errors

ADDON = xbmcaddon.Addon()
ADDON_NAME = ADDON.getAddonInfo("name")
HANDLE = int(sys.argv[1]) if len(sys.argv) > 2 else -1
PARAMS = dict(urllib.parse.parse_qsl(sys.argv[2].lstrip("?"))) if len(sys.argv) > 2 else {}
TEMP_DIR = os.path.join(xbmcvfs.translatePath(ADDON.getAddonInfo("profile")), "temp") + os.sep
SUB_EXTS = (".srt", ".sub", ".ssa", ".ass", ".vtt", ".smi")
NON_BROWSABLE = ("http://", "https://", "plugin://", "pvr://", "rtmp", "rtsp://", "udp://", "upnp://")


def log(msg, level=xbmc.LOGINFO):
	if level == xbmc.LOGDEBUG and not ADDON.getSettingBool("debug_logging"):
		return
	xbmc.log("[%s] %s" % (ADDON_NAME, msg), level)


def notify(msg, icon=xbmcgui.NOTIFICATION_INFO):
	xbmcgui.Dialog().notification(ADDON_NAME, msg, icon, 5000)


def target_language():
	return ADDON.getSetting("target_language") or "English"


def custom_subtitle_folder():
	query = {"jsonrpc": "2.0", "method": "Settings.GetSettingValue",
			 "params": {"setting": "subtitles.custompath"}, "id": 1}
	try:
		res = json.loads(xbmc.executeJSONRPC(json.dumps(query)))
		return res.get("result", {}).get("value") or ""
	except Exception:
		return ""


def list_dir_subs(folder, base):
	found = []
	if not folder or not base or folder.lower().startswith(NON_BROWSABLE):
		return found
	try:
		_, files = xbmcvfs.listdir(folder)
	except Exception:
		return found
	for name in files:
		lower = name.lower()
		temp_sub = base.lower() == "tempsubtitle" and lower.startswith("tempsubtitle.")
		if (temp_sub or lower.endswith(SUB_EXTS)) and lower.startswith(base.lower()):
			found.append(os.path.join(folder, name) if "://" not in folder else folder.rstrip("/") + "/" + name)
	return found


def current_subtitle_meta(player):
	current = (player.getSubtitles() or "").lower()
	iso1 = (xbmc.convertLanguage(current, xbmc.ISO_639_1) or "").lower()
	iso2 = (xbmc.convertLanguage(current, xbmc.ISO_639_2) or "").lower()
	query = {
		"jsonrpc": "2.0",
		"method": "Player.GetProperties",
		"params": {"playerid": 1, "properties": ["currentsubtitle"]},
		"id": 1,
	}
	name = ""
	try:
		res = json.loads(xbmc.executeJSONRPC(json.dumps(query)))
		name = (res.get("result", {}).get("currentsubtitle", {}) or {}).get("name", "")
	except Exception:
		pass
	return {
		"current": current,
		"codes": {c for c in (current, iso1, iso2) if c},
		"name": (name or "").lower(),
	}


def find_source_subtitles():
	"""Return subtitle files available for the playing video, current one first."""
	player = xbmc.Player()
	if not player.isPlayingVideo():
		return []
	video = player.getPlayingFile()
	if "://" in video:
		folder = video.rsplit("/", 1)[0] + "/"
		base = os.path.splitext(video.rsplit("/", 1)[-1])[0]
	else:
		folder = os.path.dirname(video)
		base = os.path.splitext(os.path.basename(video))[0]
	subs = list_dir_subs(folder, base) + list_dir_subs(custom_subtitle_folder(), base)
	for sub_dir in ("Subs", "subs", "Subtitles", "subtitles"):
		subs += list_dir_subs(folder.rstrip("/\\") + "/" + sub_dir + "/", base)

	subs += [s for s in list_dir_subs("special://temp/", "TempSubtitle") if not is_stale(s, player)]
	try:
		subs += addon_cache_subs(video, player)
	except Exception as exc:
		log("Add-on cache lookup failed: %r" % exc, xbmc.LOGWARNING)

	meta = current_subtitle_meta(player)
	subs = [s for s in subs if "aisubtitle" not in s.lower()]
	stream = youtube_sources(video, meta) or stream_sources(video, meta)
	if stream:
		return stream
	if not subs:
		return embedded_sources(video, meta)

	def rank(path):
		lower = path.lower()
		code_match = any((".%s." % c) in lower for c in meta["codes"])
		name_hint = any(t and t in lower for t in meta["name"].replace("(", " ").replace(")", " ").split())
		is_temp = "tempsubtitle." in lower
		return (0 if code_match else 1, 0 if name_hint else 1, 0 if is_temp else 1, lower)

	subs = list(dict.fromkeys(subs))
	subs.sort(key=rank)
	return subs


def pick_source(subs):
	if len(subs) == 1:
		return subs[0]
	labels = [source_name_label(s) for s in subs]
	default = next((i for i, s in enumerate(subs) if source_code(source_label(s)) == "en"), 0)
	choice = xbmcgui.Dialog().select(ADDON.getLocalizedString(32019), labels, preselect=default)
	return subs[choice] if choice >= 0 else None


def source_name_label(src):
	code = source_code(source_label(src))
	name = (xbmc.convertLanguage(code, xbmc.ENGLISH_NAME) if code else "") or "Subtitle"
	return "%s (%s)" % (name, source_label(src))


def search():
	language = target_language()
	iso = xbmc.convertLanguage(language, xbmc.ISO_639_1) or "en"
	try:
		subs = find_source_subtitles()
	except Exception as exc:
		log("Search failed: %r" % exc, xbmc.LOGERROR)
		subs = []
	if not subs:
		log("No subtitle available for the playing video, skipping")
		return
	log("Source candidates: %s" % json.dumps(subs, ensure_ascii=False), xbmc.LOGDEBUG)
	src = pick_source(subs)
	if src is None:
		log("Source selection cancelled")
		return
	log("Selected source: %s" % src, xbmc.LOGDEBUG)
	add_translate_item(src, language, iso)


def add_translate_item(src, language, iso):
	code = source_code(source_label(src))
	source_name = (xbmc.convertLanguage(code, xbmc.ENGLISH_NAME) if code else "") or "Subtitle"
	item = xbmcgui.ListItem(label=language, label2="AI: %s -> %s" % (source_name, language))
	item.setArt({"thumb": iso, "icon": "5"})
	item.setProperty("sync", "true")
	item.setProperty("hearing_imp", "false")
	url = "plugin://%s/?%s" % (ADDON.getAddonInfo("id"),
							   urllib.parse.urlencode({"action": "download", "src": src}))
	xbmcplugin.addDirectoryItem(HANDLE, url, item, isFolder=False)


def debug_folder():
	folder = ADDON.getSetting("debug_folder").strip()
	return folder.rstrip("/\\") + "/" if folder else ""


def read_file(path):
	if not xbmcvfs.exists(path):
		return "(missing: %s)" % path
	f = xbmcvfs.File(path, "rb")
	try:
		return translator.decode_bytes(bytes(f.readBytes()))
	finally:
		f.close()


def is_stale(path, player):
	"""True when the file was written before the current playback started."""
	try:
		started = time.time() - player.getTime() - 60
		stale = xbmcvfs.Stat(path).st_mtime() < started
	except Exception:
		return True
	if stale:
		log("Ignoring stale subtitle from a previous video: %s" % path)
	return stale


def playing_addon_id(video):
	for path in (video, xbmc.getInfoLabel("Player.FilenameAndPath"), xbmc.getInfoLabel("Container.PluginName")):
		match = re.match(r"(?:plugin://)?([a-z0-9_.\-]+\.[a-z0-9_.\-]+)", path or "", re.I)
		if match and (path.startswith("plugin://") or "://" not in path):
			return match.group(1)
	return ""


def tokens(text):
	return [t for t in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(t) > 2]


def walk_subs(folder, depth=2):
	found = []
	try:
		dirs, files = xbmcvfs.listdir(folder)
	except Exception:
		return found
	found += [folder + name for name in files if name.lower().endswith(SUB_EXTS)]
	if depth > 0:
		for d in dirs:
			found += walk_subs(folder + d + "/", depth - 1)
	return found


def addon_cache_subs(video, player):
	"""Subtitles other add-ons saved locally for the video playing right now."""
	addon_id = playing_addon_id(video)
	vid = youtube_video_id(video) if "youtu" in (video + xbmc.getInfoLabel("Player.FilenameAndPath")).lower() else ""
	title = tokens(xbmc.getInfoLabel("VideoPlayer.Title"))
	own, shared = [], ["special://temp/"]
	if addon_id:
		own = ["special://profile/addon_data/%s/" % addon_id, "special://temp/%s/" % addon_id,
			   "special://home/temp/%s/" % addon_id]
	result = []
	for folder in own + shared:
		for path in walk_subs(folder, 2 if folder in own else 1):
			name = path.lower().rsplit("/", 1)[-1]
			if "aisubtitle" in path.lower() or name.startswith("tempsubtitle"):
				continue
			matches_video = (vid and vid.lower() in name) or (title and sum(t in name for t in title) >= max(1, len(title) // 2))
			if folder not in own and not matches_video:
				continue
			if is_stale(path, player):
				continue
			log("Using add-on cached subtitle: %s" % path)
			result.append(path)
	return result


def youtube_video_id(video):
	candidates = [video, xbmc.getInfoLabel("Player.FilenameAndPath"), xbmc.getInfoLabel("Player.Filename")]
	if not any("youtube" in (c or "").lower() or "youtu.be" in (c or "").lower() for c in candidates):
		return ""
	log("Playing: %s" % " | ".join(c for c in candidates if c))
	for text in candidates:
		for pattern in (r"video_id=([\w-]{11})", r"plugin\.video\.youtube/([\w-]{11})\.mpd",
						r"[?&]v=([\w-]{11})", r"youtu\.be/([\w-]{11})"):
			match = re.search(pattern, text or "")
			if match:
				return match.group(1)
	return ""


def youtube_sources(video, meta):
	"""YouTube caption tracks fetched like yt-dlp does, current language first."""
	video_id = youtube_video_id(video)
	log("YouTube video id: %s" % (video_id or "(none)"))
	if not video_id:
		return []
	tracks = youtube_captions.caption_tracks(video_id, log=log)
	manual = {t["lang"] for t in tracks if not t["auto"]}
	tracks = [t for t in tracks if not t["auto"] or t["lang"] not in manual]
	preferred = tuple(meta["codes"]) + ("en",)
	tracks.sort(key=lambda t: (0 if t["lang"].split("-")[0].lower() in preferred else 1, 1 if t["auto"] else 0))
	for t in tracks:
		log("YouTube caption: %s %s%s" % (t["lang"], t["name"], " (auto)" if t["auto"] else ""))
	return ["youtube:%s|%s" % (video_id, t["lang"] + (".auto" if t["auto"] else "")) for t in tracks]


def stream_sources(video, meta):
	"""Subtitle tracks embedded in a YouTube DASH manifest, current language first."""
	video_id = youtube_video_id(video)
	if not video_id:
		return []
	mpd = "special://home/temp/plugin.video.youtube/%s.mpd" % video_id
	log("Video %s, manifest %s exists=%s" % (video, mpd, xbmcvfs.exists(mpd)))
	if not xbmcvfs.exists(mpd):
		return []
	try:
		manifest = read_file(mpd)
	except Exception as exc:
		log("Manifest read failed: %r" % exc)
		return []
	try:
		tracks = stream_subs.mpd_text_tracks(manifest)
	except Exception as exc:
		log("MPD parse failed: %s" % exc, xbmc.LOGWARNING)
		return []
	log("MPD subtitle tracks: %s" % [t[0] for t in tracks])

	def rank(track):
		lang = track[0].lower()
		return (0 if lang in meta["codes"] or lang.split("-")[0] in meta["codes"] else 1,
				0 if lang.split("-")[0] == "en" else 1)

	return ["stream:%s|%s" % (lang, url) for lang, url, _ in sorted(tracks, key=rank)]


def embedded_sources(video, meta):
	"""Text subtitle tracks inside the playing MKV or MP4 file, current language first."""
	if mp4_extract.is_mp4(video):
		return embedded_mp4_sources(video, meta)
	if not mkv_subs.is_matroska(video):
		return []
	if video.lower().startswith(NON_BROWSABLE[:2]):
		try:
			mkv = mkv_subs.Matroska(video, log=log)
		except Exception as exc:
			log("Matroska header read failed: %r" % exc, xbmc.LOGWARNING)
			return []
	else:
		return []
	tracks = [t for t in mkv.tracks if not t.forced] or mkv.tracks
	for t in tracks:
		log("Embedded subtitle track %d %s %s %s" % (t.number, t.codec, t.language, t.name))

	def rank(t):
		lang = t.language.lower()
		base = lang.split("-")[0]
		return (0 if lang in meta["codes"] or base in meta["codes"] else 1, 0 if base in ("en", "eng") else 1)

	return ["mkv:%d|%s|%s" % (t.number, t.language, video) for t in sorted(tracks, key=rank)]


def embedded_mp4_sources(video, meta):
	if not video.lower().startswith(NON_BROWSABLE[:2]):
		return []
	try:
		mp4 = mp4_extract.Mp4(video)
	except Exception as exc:
		log("MP4 header read failed: %r" % exc, xbmc.LOGWARNING)
		return []
	tracks = mp4.text_tracks()

	def rank(t):
		lang = (t["lang"] or "und").lower()
		base = lang.split("-")[0]
		return (0 if lang in meta["codes"] or base in meta["codes"] else 1, 0 if base in ("en", "eng") else 1)

	return ["mp4:%d|%s|%s" % (t["id"], t["lang"], video) for t in sorted(tracks, key=rank)]


def extract_embedded(src, quiet=False):
	kind = src[:3]
	number, lang, video = src[4:].split("|", 2)
	safe = re.sub(r"[^A-Za-z0-9._-]+", "_", os.path.splitext(urllib.parse.urlparse(video.split("|")[0]).path.rsplit("/", 1)[-1])[0])
	path = TEMP_DIR + "%s.%s.srt" % (safe, lang)
	if xbmcvfs.exists(path):
		log("Using previously extracted subtitle %s" % path)
		return read_file(path)
	if not quiet and not xbmcgui.Dialog().yesno(
		ADDON_NAME,
		"Embedded subtitle extraction can take 1-3 minutes before translation starts.\n"
		"Do you want to continue?",
		nolabel="Cancel",
		yeslabel="Extract and translate"):
		raise mkv_subs.Cancelled("User skipped slow extraction")
	if not xbmcvfs.exists(TEMP_DIR):
		xbmcvfs.mkdirs(TEMP_DIR)
	started = time.time()
	dialog = None if quiet else xbmcgui.DialogProgress()
	if dialog:
		dialog.create(ADDON_NAME, "Extracting embedded subtitle... this can take a few minutes. Press Back to cancel")
	monitor = xbmc.Monitor()
	pulse = [0]

	def cancelled():
		if dialog is None:
			return monitor.abortRequested()
		pulse[0] = (pulse[0] + 3) % 99
		dialog.update(pulse[0], message="Extracting subtitle from video stream... this can take a few minutes")
		return dialog.iscanceled() or monitor.abortRequested()

	try:
		if kind == "mp4":
			events = mp4_extract.Mp4(video, cancelled=cancelled).extract(int(number))
			srt = mkv_subs.to_srt(events, "S_TEXT/UTF8")
		else:
			srt = mkv_subs.Matroska(video, log=log).extract(int(number), cancelled=cancelled)
	finally:
		if dialog:
			dialog.close()
	if not srt.strip():
		raise RuntimeError("Embedded subtitle track %s is empty" % number)
	write_file(path, srt)
	log("Extracted embedded subtitle to %s in %.0fs" % (path, time.time() - started))
	return srt


def load_source(src, quiet=False):
	if src.startswith("mkv:") or src.startswith("mp4:"):
		return extract_embedded(src, quiet)
	if src.startswith("youtube:"):
		video_id, wanted = src[8:].split("|", 1)
		auto = wanted.endswith(".auto")
		lang = wanted[:-5] if auto else wanted
		tracks = youtube_captions.caption_tracks(video_id, log=log)
		track = next((t for t in tracks if t["lang"] == lang and t["auto"] == auto), None)
		if not track:
			raise RuntimeError("YouTube caption %s not available" % wanted)
		return stream_subs.to_srt(youtube_captions.download_vtt(track))
	if src.startswith("stream:"):
		url = src.split("|", 1)[1]
		with urllib.request.urlopen(url, timeout=30) as resp:
			return stream_subs.to_srt(translator.decode_bytes(resp.read()))
	return read_file(src)


def source_label(src):
	if src.startswith("youtube:"):
		video_id, wanted = src[8:].split("|", 1)
		return "%s.%s.srt" % (video_id, wanted.replace(".auto", ""))
	if src.startswith("stream:"):
		return "youtube.%s.srt" % src[7:].split("|", 1)[0]
	if src.startswith("mkv:") or src.startswith("mp4:"):
		lang = src[4:].split("|", 2)[1].split("-")[0]
		return "embedded.%s.srt" % (xbmc.convertLanguage(lang, xbmc.ISO_639_1) or lang)
	return os.path.basename(src.replace("\\", "/"))


def source_code(path):
	parts = os.path.basename(path.replace("\\", "/")).lower().split(".")
	return parts[-2] if len(parts) >= 3 and 2 <= len(parts[-2]) <= 3 else ""


def preview(text, lines=3):
	"""First subtitle cues only, so the log does not hold the whole file."""
	cues = re.split(r"\r?\n\s*\r?\n", (text or "").strip())
	if len(cues) <= lines:
		return text
	return "\n\n".join(cues[:lines]) + "\n\n... (%d more cues, %d chars total)" % (len(cues) - lines, len(text))


def shorten_body(body):
	body = json.loads(json.dumps(body))
	for message in body.get("messages", []):
		content = message.get("content")
		if isinstance(content, list):
			for part in content:
				if part.get("type") == "text" and "-->" in part.get("text", ""):
					part["text"] = preview(part["text"])
		elif isinstance(content, str) and "-->" in content:
			message["content"] = preview(content)
	return body


def write_file(path, text):
	f = xbmcvfs.File(path, "w")
	try:
		f.write(text.encode("utf-8"))
	finally:
		f.close()


def edge_cues(text, n=3):
	blocks = [b for b in str(text).strip().split("\n\n") if b.strip()]
	if len(blocks) <= 2 * n:
		return "\n\n".join(blocks)
	return "\n\n".join(blocks[:n] + ["..."] + blocks[-n:])


def build_subtitle(src, language, quiet=False):
	out_path = output_path(src, language)
	cache_dir = TEMP_DIR + "cache/"
	cached = cache.get(cache_dir, src, language, read_file)
	if cached is not None:
		log("Using cached translation for %s" % src)
		write_output(out_path, cached)
		return out_path
	text = load_source(src, quiet)
	api_key = ADDON.getSetting("api_key")
	api_url = ADDON.getSetting("api_url")

	debug_dir = debug_folder()
	log_requests = ADDON.getSettingBool("log_requests")

	def capture(url, headers, body):
		safe = dict(headers)
		if "Authorization" in safe:
			safe["Authorization"] = "Bearer ***"
		log("REQUEST POST %s\nheaders: %s" % (url, json.dumps(safe)), xbmc.LOGDEBUG)
		log("REQUEST body (first and last 3 cues sent to the AI): %s" % edge_cues(body["messages"][1]["content"][1]["text"]),
			xbmc.LOGDEBUG)

	def capture_response(status, raw):
		try:
			content = json.loads(raw)["choices"][0]["message"]["content"]
		except (ValueError, KeyError, IndexError, TypeError):
			content = raw
		log("RESPONSE HTTP %s (first and last 3 cues returned): %s" % (status, edge_cues(content)), xbmc.LOGDEBUG)

	if debug_dir:
		xbmcvfs.mkdirs(debug_dir)
		write_file(debug_dir + "source_path.txt", src)
		write_file(debug_dir + "to_send.srt", text)

	dialog = None if quiet else xbmcgui.DialogProgress()
	if dialog:
		dialog.create(ADDON_NAME, "Translating to %s... this can take a few minutes. Press Back to cancel" % language)
	monitor = xbmc.Monitor()
	started = time.time()
	pulse = [0]
	timeout = ADDON.getSettingInt("timeout") or 300

	def cancelled():
		if dialog is None:
			return monitor.abortRequested()
		pulse[0] = (pulse[0] + 2) % 99
		elapsed = int(time.time() - started)
		dialog.update(pulse[0], message="AI is processing the subtitle...\n%ds elapsed (can take a few minutes)\nWill timeout at %s seconds" % (elapsed, timeout))
		return dialog.iscanceled() or monitor.abortRequested()

	try:
		translated = translator.translate_subtitle(
			text, language, api_url, api_key,
			ADDON.getSetting("model") or "gpt-4o-mini",
			int(ADDON.getSetting("timeout") or 300),
			extra_headers=translator.parse_headers(ADDON.getSetting("custom_headers")),
			on_request=capture if log_requests else None,
			on_response=capture_response if log_requests else None,
			source_name=source_label(src),
			cancelled=cancelled,
			progress=lambda i, n: dialog and dialog.update(int(i * 100 / max(n, 1))))
	finally:
		if dialog:
			dialog.close()

	cache.put(cache_dir, src, language, translated, write_file)
	write_output(out_path, translated)
	return out_path


def output_path(src, language):
	if not xbmcvfs.exists(TEMP_DIR):
		xbmcvfs.mkdirs(TEMP_DIR)
	iso = xbmc.convertLanguage(language, xbmc.ISO_639_1) or "xx"
	base = os.path.splitext(source_label(src))[0]
	return os.path.join(TEMP_DIR, "%s.aisubtitle.%s.srt" % (base, iso))


def write_output(out_path, translated):
	with open(out_path, "w", encoding="utf-8") as out:
		out.write(translated)
	log("Translated subtitle written to %s" % out_path)


def download():
	src = PARAMS.get("src")
	if not ADDON.getSetting("api_url"):
		notify("Configure the API URL in the add-on settings", xbmcgui.NOTIFICATION_ERROR)
		ADDON.openSettings()
		return
	language = target_language()
	try:
		out_path = build_subtitle(src, language)
	except (mkv_subs.Cancelled, translator.Cancelled):
		log("Subtitle build cancelled by the user")
		notify("Cancelled")
		return
	except Exception as exc:
		log("Subtitle build failed for %s: %r" % (src, exc), xbmc.LOGERROR)
		notify(errors.describe(exc), xbmcgui.NOTIFICATION_ERROR)
		return
	notify("Subtitle ready: %s" % language)
	xbmcplugin.addDirectoryItem(HANDLE, out_path, xbmcgui.ListItem(label=out_path), isFolder=False)
	activate_subtitle(out_path)


def activate_subtitle(path):
	"""Load the subtitle into the player directly; Kodi's own copy to TempSubtitle can fail after long runs."""
	try:
		player = xbmc.Player()
		if player.isPlayingVideo():
			player.setSubtitles(path)
			player.showSubtitles(True)
			log("Subtitle activated in player: %s" % path)
	except Exception as exc:
		log("Subtitle activation failed: %r" % exc, xbmc.LOGWARNING)


if HANDLE >= 0:
	action = PARAMS.get("action")
	if action in ("search", "manualsearch"):
		search()
	elif action == "download":
		download()
	elif action == "settings" or not action:
		ADDON.openSettings()
	xbmcplugin.endOfDirectory(HANDLE)
