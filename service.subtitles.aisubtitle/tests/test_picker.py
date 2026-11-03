import importlib
import os
import sys
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "resources", "lib"))


def load_service():
	kodi = {name: mock.MagicMock() for name in ("xbmc", "xbmcaddon", "xbmcgui", "xbmcplugin", "xbmcvfs")}
	kodi["xbmcvfs"].translatePath.return_value = os.path.join(ROOT, "tmp") + os.sep
	argv = sys.argv
	sys.argv = ["plugin://service.subtitles.aisubtitle/", "1", "?action=settings"]
	try:
		with mock.patch.dict(sys.modules, kodi):
			sys.modules.pop("service", None)
			return importlib.import_module("service"), kodi
	finally:
		sys.argv = argv
		sys.modules.pop("service", None)


class PickSourceTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.service, cls.kodi = load_service()

	def setUp(self):
		self.select = self.kodi["xbmcgui"].Dialog.return_value.select
		self.select.reset_mock()
		self.select.return_value = 0

	def test_single_source_skips_dialog(self):
		self.assertEqual(self.service.pick_source(["/m/movie.pt.srt"]), "/m/movie.pt.srt")
		self.select.assert_not_called()

	def test_english_preselected_when_available(self):
		subs = ["/m/movie.pt.srt", "/m/movie.en.srt", "/m/movie.de.srt"]
		self.select.return_value = 1
		chosen = self.service.pick_source(subs)
		self.assertEqual(self.select.call_args.kwargs["preselect"], 1)
		self.assertEqual(chosen, "/m/movie.en.srt")

	def test_first_preselected_when_no_english(self):
		subs = ["/m/movie.pt.srt", "/m/movie.de.srt"]
		self.service.pick_source(subs)
		self.assertEqual(self.select.call_args.kwargs["preselect"], 0)

	def test_cancelled_dialog_returns_none(self):
		self.select.return_value = -1
		self.assertIsNone(self.service.pick_source(["/m/a.en.srt", "/m/a.pt.srt"]))


if __name__ == "__main__":
	unittest.main()
