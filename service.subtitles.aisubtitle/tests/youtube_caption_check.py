import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from resources.lib import stream_subs, youtube_captions  # noqa: E402

video_id = sys.argv[1] if len(sys.argv) > 1 else "mScpHTIi-kM"
tracks = youtube_captions.caption_tracks(video_id, log=print)
for t in tracks:
	print(t["lang"], t["name"], "auto" if t["auto"] else "manual")
track = youtube_captions.pick_track(tracks, ("en",))
if track:
	srt = stream_subs.to_srt(youtube_captions.download_vtt(track))
	print("Picked", track["lang"], track["name"])
	print(srt[:600])
