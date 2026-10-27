import json
import tempfile
import threading
import unittest
from email.utils import parsedate_to_datetime
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

from rss_server import EventStore, build_feed, create_server


class EventStoreTests(unittest.TestCase):
    def test_timestamps_are_strictly_increasing_and_persisted(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "events.db"
            with patch("rss_server.time.time", return_value=1_800_000_000):
                store = EventStore(database)
                first = store.add("Uno")
                second = store.add("Dos")
                reopened = EventStore(database)
                third = reopened.add("Tres")
            self.assertEqual(
                [first["published_epoch"], second["published_epoch"], third["published_epoch"]],
                [1_800_000_000, 1_800_000_001, 1_800_000_002],
            )

    def test_feed_is_valid_rss_with_required_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            store = EventStore(Path(directory) / "events.db")
            store.add("Evento & prueba", "Sin datos reales")
            root = ET.fromstring(build_feed(store, "https://rss.example.test"))
            self.assertEqual(root.tag, "rss")
            item = root.find("./channel/item")
            self.assertIsNotNone(item)
            self.assertEqual(item.findtext("title"), "Evento & prueba")
            self.assertTrue(item.findtext("guid"))
            self.assertIsNotNone(parsedate_to_datetime(item.findtext("pubDate")))
            self.assertEqual(item.findtext("link"), "https://rss.example.test/events/1")


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.server = create_server(
            "127.0.0.1", 0, Path(self.temporary.name) / "events.db"
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temporary.cleanup()

    def test_post_event_then_read_feed(self):
        request = Request(
            self.base_url + "/events",
            data=json.dumps({"title": "Prueba API", "description": "Ficticio"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request) as response:
            self.assertEqual(response.status, 201)
            created = json.load(response)
        self.assertEqual(created["title"], "Prueba API")
        with urlopen(self.base_url + "/feed.xml") as response:
            self.assertEqual(response.headers.get_content_type(), "application/rss+xml")
            feed = response.read()
        self.assertIn(b"Prueba API", feed)


if __name__ == "__main__":
    unittest.main()
