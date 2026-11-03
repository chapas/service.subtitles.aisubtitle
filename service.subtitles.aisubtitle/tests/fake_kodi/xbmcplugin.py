ITEMS = []


def addDirectoryItem(handle, url, listitem, isFolder=False):
	ITEMS.append((url, listitem))
	print("[fake list] %s | %s | %s" % (listitem.getLabel(), listitem.getLabel2(), url), flush=True)
	return True


def endOfDirectory(handle, succeeded=True):
	print("[fake list] end (%d items)" % len(ITEMS), flush=True)
