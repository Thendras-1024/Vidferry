import datetime
import sqlite3
import unittest

from app.db.base import _local_timestamp


class DatabaseTimeTests(unittest.TestCase):
    def test_current_timestamp_uses_local_time(self):
        conn = sqlite3.connect(":memory:")
        conn.create_function("current_timestamp", 0, _local_timestamp)
        conn.execute("CREATE TABLE sample (created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("INSERT INTO sample DEFAULT VALUES")
        created_at = conn.execute("SELECT created_at FROM sample").fetchone()[0]

        self.assertEqual(created_at[:16], datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))


if __name__ == "__main__":
    unittest.main()
