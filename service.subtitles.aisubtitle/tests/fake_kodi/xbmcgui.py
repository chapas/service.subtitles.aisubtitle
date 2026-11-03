import os
import time

NOTIFICATION_INFO, NOTIFICATION_WARNING, NOTIFICATION_ERROR = "info", "warning", "error"
# FAKE_YESNO=0 answers "No" to confirmations; FAKE_CANCEL_AFTER=<seconds> presses Back on progress dialogs.


class Dialog:
	def notification(self, heading, message, icon=None, time=0, sound=True):
		print("[fake notification:%s] %s" % (icon, message), flush=True)

	def yesno(self, heading, message, nolabel="", yeslabel="", autoclose=0, defaultbutton=None):
		answer = os.environ.get("FAKE_YESNO", "1") == "1"
		print("[fake yesno] %s -> %s" % (message.replace("\n", " | "), "Yes" if answer else "No"), flush=True)
		return answer


class DialogProgress:
	def __init__(self):
		self.opened = 0
		self.last = None

	def create(self, heading, message=""):
		self.opened = time.time()
		print("[fake progress] open: %s" % message.replace("\n", " | "), flush=True)

	def update(self, percent, message=""):
		text = "%3d%% %s" % (percent, message.replace("\n", " | "))
		if text != self.last:
			self.last = text
			print("[fake progress] %s" % text, flush=True)

	def iscanceled(self):
		limit = float(os.environ.get("FAKE_CANCEL_AFTER", "0") or 0)
		return bool(limit) and time.time() - self.opened > limit

	def close(self):
		print("[fake progress] closed after %.1fs" % (time.time() - self.opened), flush=True)


class ListItem:
	def __init__(self, label="", label2="", path=""):
		self.label, self.label2 = label, label2
		self.props = {}

	def setArt(self, art):
		pass

	def setProperty(self, key, value):
		self.props[key] = value

	def getLabel(self):
		return self.label

	def getLabel2(self):
		return self.label2
