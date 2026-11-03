import os

# Settings come from FAKE_SETTING_<ID> environment variables.
DEFAULTS = {
	"target_language": "Portuguese",
	"api_url": "https://api.deepinfra.com/v1/openai",
	"model": "deepseek-ai/DeepSeek-V4.1-Flash-1017",
	"timeout": "600",
	"custom_headers": "x-deepinfra-service-tier: flex",
	"debug_folder": "",
	"log_requests": "true",
	"api_key": "",
}


class Addon:
	def __init__(self, addon_id=None):
		pass

	def getSetting(self, key):
		return os.environ.get("FAKE_SETTING_" + key.upper(), DEFAULTS.get(key, ""))

	def getSettingBool(self, key):
		return self.getSetting(key).lower() == "true"

	def getAddonInfo(self, key):
		return {"name": "AI Subtitle", "id": "service.subtitles.aisubtitle", "version": "dev"}.get(key, "")

	def openSettings(self):
		print("[fake] openSettings()")
