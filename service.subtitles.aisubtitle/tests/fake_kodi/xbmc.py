"""Minimal stand-in for Kodi's xbmc module so the add-on runs on a PC."""
import json
import os
import time

LOGDEBUG, LOGINFO, LOGWARNING, LOGERROR = 0, 1, 2, 3
ISO_639_1, ISO_639_2, ENGLISH_NAME = 0, 1, 2

STATE = {
	"playing": os.environ.get("FAKE_PLAYING", ""),
	"subtitle": os.environ.get("FAKE_SUBTITLE", "eng"),
	"started": time.time() - 30,
	"labels": {},
}

_LANGS = {
	"english": ("en", "eng", "English"), "en": ("en", "eng", "English"), "eng": ("en", "eng", "English"),
	"portuguese": ("pt", "por", "Portuguese"), "pt": ("pt", "por", "Portuguese"), "por": ("pt", "por", "Portuguese"),
	"spanish": ("es", "spa", "Spanish"), "es": ("es", "spa", "Spanish"), "spa": ("es", "spa", "Spanish"),
}


def log(msg, level=LOGINFO):
	print("[kodi %s] %s" % (("DEBUG", "INFO", "WARNING", "ERROR")[level], msg), flush=True)


def convertLanguage(value, fmt):
	entry = _LANGS.get((value or "").lower())
	return entry[fmt] if entry else ""


def getInfoLabel(label):
	if label in ("Player.FilenameAndPath", "Player.Filename"):
		return STATE["labels"].get(label, STATE["playing"])
	return STATE["labels"].get(label, "")


def executeJSONRPC(query):
	req = json.loads(query)
	if req.get("method") == "Player.GetProperties":
		return json.dumps({"result": {"currentsubtitle": {"name": "", "language": STATE["subtitle"]}}})
	return json.dumps({"result": {}})


class Player:
	def isPlayingVideo(self):
		return bool(STATE["playing"])

	def getPlayingFile(self):
		return STATE["playing"]

	def getSubtitles(self):
		return STATE["subtitle"]

	def getTime(self):
		return time.time() - STATE["started"]


class Monitor:
	def abortRequested(self):
		return False

	def waitForAbort(self, timeout=0):
		time.sleep(timeout)
		return False
