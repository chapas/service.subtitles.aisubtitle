import re
import socket
import urllib.error


def http_status(exc):
	match = re.match(r"HTTP (\d{3})", str(exc))
	return int(match.group(1)) if match else 0


def describe(exc):
	status = http_status(exc)
	if status in (401, 403):
		return "API key rejected (HTTP %d). Check the API key in settings." % status
	if status == 404:
		return "API URL or model not found (HTTP 404). Check the API URL and model in settings."
	if status == 429:
		return "Rate limit reached (HTTP 429). Wait a minute and try again."
	if status >= 500:
		return "AI service error (HTTP %d). Try again later." % status
	if isinstance(exc, (socket.timeout, TimeoutError)):
		return "Request timed out. Increase the timeout in settings or try again."
	if isinstance(exc, urllib.error.URLError):
		return "Network error: %s" % (exc.reason,)
	if isinstance(exc, ValueError):
		return "Unexpected response from the AI service."
	return str(exc) or exc.__class__.__name__
