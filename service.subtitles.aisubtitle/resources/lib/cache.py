import hashlib
import os


def cache_key(source_id, language):
	digest = hashlib.sha1(("%s|%s" % (source_id, language)).encode("utf-8")).hexdigest()
	return digest[:20]


def cache_path(folder, source_id, language):
	return os.path.join(folder, "cache_%s.srt" % cache_key(source_id, language))


def get(folder, source_id, language, read):
	path = cache_path(folder, source_id, language)
	if not os.path.exists(path):
		return None
	return read(path)


def put(folder, source_id, language, text, write):
	os.makedirs(folder, exist_ok=True)
	write(cache_path(folder, source_id, language), text)
