import sys
import urllib.parse

import xbmcaddon
import xbmcgui

from resources.lib import errors
from resources.lib import translator_file as translator

ADDON = xbmcaddon.Addon()
ALLOWED = ("target_language", "api_url", "api_key", "model", "timeout", "custom_headers", "debug_folder",
		   "log_requests", "debug_logging")

args = dict(urllib.parse.parse_qsl("&".join(a.lstrip("?") for a in sys.argv[1:])))
updates = {k: v for k, v in args.items() if k in ALLOWED}
if updates:
	for key, value in updates.items():
		ADDON.setSetting(key, value)
	if "api_key" in updates or "api_url" in updates:
		try:
			translator.check_connection(ADDON.getSetting("api_url"), ADDON.getSetting("api_key"))
			xbmcgui.Dialog().notification(ADDON.getAddonInfo("name"), ADDON.getLocalizedString(32020))
		except Exception as exc:
			xbmcgui.Dialog().notification(ADDON.getAddonInfo("name"),
										  "%s: %s" % (ADDON.getLocalizedString(32021), errors.describe(exc)),
										  xbmcgui.NOTIFICATION_WARNING, 8000)
else:
	ADDON.openSettings()
