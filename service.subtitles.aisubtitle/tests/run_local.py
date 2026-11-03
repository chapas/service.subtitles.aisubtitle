"""Run the add-on on a PC with fake Kodi modules and the real network/API.

Examples:
  python tests/run_local.py search   "plugin://plugin.video.youtube/play/?video_id=mScpHTIi-kM"
  python tests/run_local.py download "plugin://plugin.video.youtube/play/?video_id=mScpHTIi-kM"
  python tests/run_local.py download "<mkv url>"

The API key comes from FAKE_SETTING_API_KEY. FAKE_YESNO=0 answers "No" to confirmations,
FAKE_CANCEL_AFTER=<seconds> presses Back on progress dialogs.
"""
import os
import runpy
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
ADDON_DIR = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HERE, "fake_kodi"))
sys.path.insert(0, ADDON_DIR)

action, playing = sys.argv[1], sys.argv[2]
os.environ["FAKE_PLAYING"] = playing

import xbmc  # noqa: E402
import xbmcplugin  # noqa: E402

xbmc.STATE["playing"] = playing
script = os.path.join(ADDON_DIR, "service.py")

sys.argv = [script, "1", "?action=search"]
runpy.run_path(script, run_name="__main__")
if action == "download":
	if not xbmcplugin.ITEMS:
		sys.exit("search returned nothing to download")
	url = xbmcplugin.ITEMS[0][0]
	del xbmcplugin.ITEMS[:]
	print("\n=== selecting %s ===" % url, flush=True)
	sys.argv = [script, "1", "?" + url.split("?", 1)[1]]
	runpy.run_path(script, run_name="__main__")
	for path, _ in xbmcplugin.ITEMS:
		if os.path.exists(path):
			with open(path, encoding="utf-8") as f:
				print("\n=== result %s ===\n%s" % (path, "".join(f.readlines()[:12])))
