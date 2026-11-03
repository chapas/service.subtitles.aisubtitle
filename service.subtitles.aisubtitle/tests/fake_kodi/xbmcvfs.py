import os
import tempfile

ROOT = os.path.join(tempfile.gettempdir(), "fake_kodi")
SPECIAL = {
	"special://temp/": os.path.join(ROOT, "temp") + os.sep,
	"special://home/temp/": os.path.join(ROOT, "temp") + os.sep,
	"special://profile/": os.path.join(ROOT, "profile") + os.sep,
}


def translatePath(path):
	for prefix, real in SPECIAL.items():
		if path.startswith(prefix):
			return real + path[len(prefix):].replace("/", os.sep)
	return path


def exists(path):
	return os.path.exists(translatePath(path))


def mkdirs(path):
	os.makedirs(translatePath(path), exist_ok=True)
	return True


def listdir(path):
	real = translatePath(path)
	if not os.path.isdir(real):
		return [], []
	names = os.listdir(real)
	return ([n for n in names if os.path.isdir(os.path.join(real, n))],
			[n for n in names if os.path.isfile(os.path.join(real, n))])


class Stat:
	def __init__(self, path):
		self._stat = os.stat(translatePath(path))

	def st_mtime(self):
		return self._stat.st_mtime


class File:
	def __init__(self, path, mode="r"):
		real = translatePath(path)
		if "w" in mode:
			os.makedirs(os.path.dirname(real) or ".", exist_ok=True)
		self._f = open(real, "wb" if "w" in mode else "rb")

	def readBytes(self, size=-1):
		return self._f.read() if size < 0 else self._f.read(size)

	def read(self):
		return self._f.read().decode("utf-8", "replace")

	def write(self, data):
		self._f.write(data if isinstance(data, bytes) else data.encode("utf-8"))
		return True

	def close(self):
		self._f.close()
