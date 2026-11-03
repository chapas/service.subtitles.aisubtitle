import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from resources.lib import translator_file as translator  # noqa: E402

SRT = "1\n00:00:01,000 --> 00:00:03,000\nHello, how are you?\n\n2\n00:00:04,000 --> 00:00:06,000\nGame theory explains the world.\n"

print(translator.translate_subtitle(
	SRT, os.environ.get("AISUB_LANG", "Portuguese"), os.environ["AISUB_URL"], os.environ["AISUB_KEY"],
	os.environ["AISUB_MODEL"], 120, extra_headers=translator.parse_headers(os.environ.get("AISUB_HEADERS"))))
