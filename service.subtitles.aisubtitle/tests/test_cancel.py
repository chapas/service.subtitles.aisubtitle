import os
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "resources", "lib"))
import translator_file as translator  # noqa: E402


class SlowHandler(BaseHTTPRequestHandler):
	def do_POST(self):
		self.rfile.read(int(self.headers.get("Content-Length", 0)))
		time.sleep(5)
		self.send_response(200)
		self.end_headers()
		self.wfile.write(b'{"choices":[{"message":{"content":"x"}}]}')

	def log_message(self, *args):
		pass


class CancelTest(unittest.TestCase):
	def test_cancel_aborts_request(self):
		server = HTTPServer(("127.0.0.1", 0), SlowHandler)
		threading.Thread(target=server.handle_request, daemon=True).start()
		started = time.time()
		with self.assertRaises(translator.Cancelled):
			translator.translate_subtitle("1\n00:00:01,000 --> 00:00:02,000\nHi\n", "Portuguese",
										  "http://127.0.0.1:%d/v1" % server.server_port, "k", "m",
										  timeout=30, cancelled=lambda: time.time() - started > 0.5)
		self.assertLess(time.time() - started, 2)
		server.server_close()


if __name__ == "__main__":
	unittest.main()
