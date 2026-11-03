# AI Subtitle (service.subtitles.aisubtitle)

Kodi subtitle add-on that finds or extracts subtitles for a video and translates them with an OpenAI-compatible AI API.

## Features

- Translates subtitles into the language selected in Kodi, with Portuguese mapped to European Portuguese (Portugal).
- Sources: YouTube captions, subtitles embedded in MKV and MP4 files, and the add-on's own subtitle search.
- Translates the whole subtitle in one request, with a configurable timeout.
- Caches translations so repeated playback does not call the API again.
- Shows a progress dialog that can be cancelled with Back.
- Logs the first and last three cues sent and returned, to keep Kodi logs short.

## Requirements

- Kodi 21 (tested on Kodi 21.2, NVIDIA Shield).
- Python 3 add-on runtime (`xbmc.python` 3.0.0).
- An OpenAI-compatible chat completions endpoint and API key.

## Installation

1. Download `service.subtitles.aisubtitle-0.5.40.zip` from the releases.
2. In Kodi, go to Settings > Add-ons > Install from zip file and select the zip.
3. Open the add-on settings and set:
   - `api_url`: base URL of the endpoint (for example `https://api.deepinfra.com/v1/openai`).
   - `api_key`: your API key.
   - `model`: model name (default `gpt-4o-mini`).
   - `timeout`: request timeout in seconds (default 300).
   - `custom_headers` (optional): extra headers as `Name: value` separated by `;`.
   - `debug_folder` (optional): folder for request and response dumps.

## Usage

Play a video, open the subtitle menu, and choose **AI Subtitle**. The add-on picks a source, translates it, saves the result to the add-on temp folder, and loads it into the player.

## Project layout

```
service.subtitles.aisubtitle/
  addon.xml                  Add-on metadata and version
  service.py                 Entry point: search, download, translate, activate
  configure.py               Settings helper that checks the API connection
  resources/settings.xml     Settings definitions
  resources/lib/
	translator_file.py       Whole-file translation client
	translator.py            SRT parsing and legacy chunked translation
	youtube_captions.py      YouTube caption track lookup
	mkv_subs.py, mp4_extract.py  Embedded subtitle extraction
	stream_subs.py           Subtitle stream handling
	cache.py                 Translation cache
	errors.py                User-facing error messages
  tests/                     Unit tests and a fake Kodi module set
```

## Testing

From the `service.subtitles.aisubtitle` folder:

```
python -m unittest discover -s tests -p "test_*.py"
```

Some scripts in `tests/` (for example `live_api_check.py`) call real services and need API access.

## Notes

- Temporary and cached files are stored in the add-on profile `temp` folder.
- `test_cancel` prints a `ConnectionAbortedError` traceback during the run; this is expected.

## License

Not yet specified.
