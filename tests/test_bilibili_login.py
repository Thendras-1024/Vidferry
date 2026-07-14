import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from queue import Queue
from unittest.mock import patch

import sau_backend as backend


class BilibiliWebLoginTests(unittest.TestCase):
    def test_qrcode_file_is_emitted_when_pty_reader_waits_for_more_output(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            base_dir = Path(temp_dir)

            class FakeProcess:
                exitstatus = 1

                def __init__(self):
                    self.alive = True
                    self.output = Queue()
                    self.output.put("选择一种登录方式\n❯ 短信登录\n扫码登录\n")
                    self.writes = []

                def read(self, _size):
                    value = self.output.get(timeout=2)
                    if value is None:
                        raise EOFError
                    return value

                def write(self, value):
                    self.writes.append(value)
                    (base_dir / "qrcode.png").write_bytes(b"fake-png")
                    self.alive = False
                    self.output.put(None)

                def isalive(self):
                    return self.alive

                def terminate(self, force=False):
                    self.alive = False
                    self.output.put(None)

            fake_process = FakeProcess()

            class FakePtyProcess:
                @staticmethod
                def spawn(_command, cwd=None, dimensions=None):
                    return fake_process

            status_queue = Queue()
            fake_winpty = types.SimpleNamespace(PtyProcess=FakePtyProcess)
            with patch.object(backend, "BASE_DIR", base_dir), patch.object(
                backend, "ensure_biliup_binary", return_value=base_dir / "biliup.exe"
            ), patch.dict(sys.modules, {"winpty": fake_winpty}):
                worker = threading.Thread(
                    target=backend.bilibili_cookie_gen,
                    args=("测试账号", status_queue),
                    daemon=True,
                )
                worker.start()
                worker.join(timeout=3)

            self.assertFalse(worker.is_alive())
            self.assertEqual(fake_process.writes, ["\x1b[B\r"])
            messages = []
            while not status_queue.empty():
                messages.append(status_queue.get_nowait())
            self.assertTrue(messages[0].startswith("data:image/png;base64,"))
            self.assertEqual(messages[-1], "500")


if __name__ == "__main__":
    unittest.main()
