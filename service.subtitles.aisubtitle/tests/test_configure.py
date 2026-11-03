import importlib
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def run_configure(argv, check_side_effect=None):
	addon = mock.MagicMock()
	settings = {"api_url": "https://api.x/v1", "api_key": "KEY"}
	addon.getSetting.side_effect = lambda key: settings.get(key, "")
	addon.getLocalizedString.side_effect = lambda i: "msg%d" % i
	addon.getAddonInfo.return_value = "AI Subtitle"
	dialog = mock.MagicMock()
	kodi = {
		"xbmcaddon": mock.MagicMock(Addon=mock.MagicMock(return_value=addon)),
		"xbmcgui": mock.MagicMock(Dialog=mock.MagicMock(return_value=dialog)),
	}
	saved_argv = sys.argv
	sys.argv = ["configure.py"] + argv
	try:
		with mock.patch.dict(sys.modules, kodi):
			sys.modules.pop("configure", None)
			with mock.patch("resources.lib.translator_file.check_connection",
							side_effect=check_side_effect) as check:
				importlib.import_module("configure")
	finally:
		sys.argv = saved_argv
		sys.modules.pop("configure", None)
	return addon, dialog, check


class ApiKeyCheckTests(unittest.TestCase):
	def test_api_key_change_runs_check_and_reports_success(self):
		addon, dialog, check = run_configure(["api_key=NEW"])
		addon.setSetting.assert_called_with("api_key", "NEW")
		check.assert_called_once_with("https://api.x/v1", "KEY")
		dialog.notification.assert_called_once()
		self.assertEqual(dialog.notification.call_args.args[1], "msg32020")

	def test_api_url_change_runs_check(self):
		_, _, check = run_configure(["api_url=https%3A%2F%2Fapi.y%2Fv1"])
		check.assert_called_once()

	def test_failed_check_reports_warning_with_reason(self):
		_, dialog, _ = run_configure(["api_key=BAD"], check_side_effect=RuntimeError("HTTP 401: nope"))
		message = dialog.notification.call_args.args[1]
		self.assertIn("msg32021", message)
		self.assertIn("API key", message)
		self.assertEqual(dialog.notification.call_args.args[2], mock.ANY)

	def test_unrelated_setting_skips_check(self):
		_, _, check = run_configure(["model=gpt-x"])
		check.assert_not_called()


if __name__ == "__main__":
	unittest.main()
