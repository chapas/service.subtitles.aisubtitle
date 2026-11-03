"""Manual check: python tests/mkv_check.py "<url|headers>" [out.srt]"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "resources", "lib"))
import mkv_subs  # noqa: E402

url = sys.argv[1]
started = time.time()
mkv = mkv_subs.Matroska(url, log=print)
print("cues:", mkv.cues_pos, "scale:", mkv.scale)
for t in mkv.tracks:
	print("track", t.number, t.codec, t.language, t.name, t.forced)
if mkv.tracks:
	srt = mkv.extract(mkv.tracks[0].number)
	print("\n".join(srt.splitlines()[:12]))
	print("chars:", len(srt), "seconds:", round(time.time() - started, 1))
	if len(sys.argv) > 2:
		with open(sys.argv[2], "w", encoding="utf-8") as f:
			f.write(srt)
