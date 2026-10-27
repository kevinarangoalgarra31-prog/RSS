"""Servidor RSS de prueba, independiente y sin dependencias externas."""

from __future__ import annotations

import argparse
import html
import json
import os
import sqlite3
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from email.utils import format_datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree as ET


DEFAULT_TITLE = "Eventos ficticios para Power Automate"
MAX_BODY_BYTES = 64 * 1024


def utc_iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def rss_date(epoch: int) -> str:
    return format_datetime(datetime.fromtimestamp(epoch, timezone.utc), usegmt=True)


class EventStore:
    """Persistencia SQLite con timestamps estrictamente crecientes."""

    def __init__(self, database: str | Path):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("PRAGMA journal_mode=WAL")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        guid TEXT NOT NULL UNIQUE,
                        title TEXT NOT NULL,
                        description TEXT NOT NULL,
                        published_epoch INTEGER NOT NULL UNIQUE,
                        published_at TEXT NOT NULL
                    )
                    """
                )

    def add(self, title: str | None = None, description: str | None = None) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            with connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT COALESCE(MAX(published_epoch), 0) AS last_epoch FROM events"
                ).fetchone()
                published_epoch = max(int(time.time()), int(row["last_epoch"]) + 1)
                event_guid = str(uuid.uuid4())
                clean_title = (title or "").strip() or f"Evento ficticio {published_epoch}"
                clean_description = (description or "").strip() or (
                    "Evento generado únicamente para validar el disparador RSS."
                )
                cursor = connection.execute(
                    """
                    INSERT INTO events (guid, title, description, published_epoch, published_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (event_guid, clean_title, clean_description, published_epoch, utc_iso(published_epoch)),
                )
                event_id = int(cursor.lastrowid)
        return self.get(event_id)

    def get(self, event_id: int) -> dict[str, Any]:
        with closing(self._connect()) as connection:
            row = connection.execute(
                "SELECT * FROM events WHERE id = ?", (event_id,)
            ).fetchone()
        if row is None:
            raise KeyError(event_id)
        return dict(row)

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection:
            rows = connection.execute(
                "SELECT * FROM events ORDER BY published_epoch DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]


def build_feed(store: EventStore, base_url: str) -> bytes:
    base_url = base_url.rstrip("/")
    ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = DEFAULT_TITLE
    ET.SubElement(channel, "link").text = base_url + "/"
    ET.SubElement(channel, "description").text = (
        "Fuente de laboratorio con información totalmente ficticia."
    )
    ET.SubElement(channel, "language").text = "es"
    ET.SubElement(
        channel,
        "{http://www.w3.org/2005/Atom}link",
        {"href": base_url + "/feed.xml", "rel": "self", "type": "application/rss+xml"},
    )
    events = store.list()
    if events:
        ET.SubElement(channel, "lastBuildDate").text = rss_date(events[0]["published_epoch"])
    for event in events:
        item = ET.SubElement(channel, "item")
        event_url = f"{base_url}/events/{event['id']}"
        ET.SubElement(item, "title").text = event["title"]
        ET.SubElement(item, "link").text = event_url
        ET.SubElement(item, "guid", {"isPermaLink": "false"}).text = event["guid"]
        ET.SubElement(item, "description").text = event["description"]
        ET.SubElement(item, "pubDate").text = rss_date(event["published_epoch"])
        ET.SubElement(item, "{http://www.w3.org/2005/Atom}updated").text = event["published_at"]
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def page_html(base_url: str) -> bytes:
    feed_url = html.escape(base_url.rstrip("/") + "/feed.xml")
    content = f"""<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Laboratorio RSS</title>
<style>
body{{font:16px system-ui,sans-serif;max-width:760px;margin:3rem auto;padding:0 1rem;line-height:1.5}}
label{{display:block;margin-top:1rem}}input,textarea{{width:100%;padding:.65rem;box-sizing:border-box}}
button{{margin-top:1rem;padding:.7rem 1.1rem}}code{{overflow-wrap:anywhere}}.note{{background:#f3f5f7;padding:1rem}}
</style></head><body>
<h1>Laboratorio RSS</h1>
<p class="note">Solo genera eventos ficticios. Los timestamps se guardan en SQLite y siempre aumentan.</p>
<p>Feed: <a href="{feed_url}"><code>{feed_url}</code></a></p>
<form method="post" action="/events">
<label>Título ficticio<input name="title" maxlength="200" placeholder="Prueba de retardo #1"></label>
<label>Descripción ficticia<textarea name="description" maxlength="2000" rows="4">Evento de prueba sin datos personales.</textarea></label>
<button type="submit">Agregar evento</button>
</form>
</body></html>"""
    return content.encode("utf-8")


def make_handler(store: EventStore, public_base_url: str | None = None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "RSSLab/1.0"

        def log_message(self, message: str, *args: Any) -> None:
            print(f"{self.address_string()} - {message % args}")

        def base_url(self) -> str:
            if public_base_url:
                return public_base_url.rstrip("/")
            host = self.headers.get("Host", "localhost")
            forwarded = self.headers.get("X-Forwarded-Proto", "http").split(",", 1)[0].strip()
            scheme = forwarded if forwarded in {"http", "https"} else "http"
            return f"{scheme}://{host}"

        def send_bytes(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store, max-age=0")
            self.end_headers()
            self.wfile.write(body)

        def send_json(self, status: int, value: Any) -> None:
            body = json.dumps(value, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_bytes(status, body, "application/json; charset=utf-8")

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/":
                self.send_bytes(HTTPStatus.OK, page_html(self.base_url()), "text/html; charset=utf-8")
                return
            if path == "/feed.xml":
                self.send_bytes(
                    HTTPStatus.OK,
                    build_feed(store, self.base_url()),
                    "application/rss+xml; charset=utf-8",
                )
                return
            if path == "/health":
                self.send_json(HTTPStatus.OK, {"status": "ok"})
                return
            if path.startswith("/events/"):
                try:
                    event = store.get(int(path.removeprefix("/events/")))
                except (ValueError, KeyError):
                    self.send_json(HTTPStatus.NOT_FOUND, {"error": "Evento no encontrado"})
                    return
                body = (
                    "<!doctype html><html lang='es'><meta charset='utf-8'><title>Evento ficticio</title>"
                    f"<body><h1>{html.escape(event['title'])}</h1>"
                    f"<p>{html.escape(event['description'])}</p>"
                    f"<p>Publicado: <time>{html.escape(event['published_at'])}</time></p>"
                    "<p><a href='/'>Volver</a></p></body></html>"
                ).encode("utf-8")
                self.send_bytes(HTTPStatus.OK, body, "text/html; charset=utf-8")
                return
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Ruta no encontrada"})

        def do_POST(self) -> None:  # noqa: N802
            if urlparse(self.path).path != "/events":
                self.send_json(HTTPStatus.NOT_FOUND, {"error": "Ruta no encontrada"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": "Content-Length inválido"})
                return
            if length > MAX_BODY_BYTES:
                self.send_json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "Cuerpo demasiado grande"})
                return
            raw = self.rfile.read(length)
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].lower()
            try:
                if content_type == "application/json":
                    payload = json.loads(raw or b"{}")
                    if not isinstance(payload, dict):
                        raise ValueError("El JSON debe ser un objeto")
                    title = payload.get("title")
                    description = payload.get("description")
                else:
                    payload = parse_qs(raw.decode("utf-8"), keep_blank_values=True)
                    title = payload.get("title", [None])[0]
                    description = payload.get("description", [None])[0]
                if title is not None and not isinstance(title, str):
                    raise ValueError("title debe ser texto")
                if description is not None and not isinstance(description, str):
                    raise ValueError("description debe ser texto")
                if title and len(title) > 200:
                    raise ValueError("title supera 200 caracteres")
                if description and len(description) > 2000:
                    raise ValueError("description supera 2000 caracteres")
                event = store.add(title, description)
            except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as error:
                self.send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
            event["url"] = f"{self.base_url()}/events/{event['id']}"
            if content_type == "application/json":
                self.send_json(HTTPStatus.CREATED, event)
            else:
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", f"/events/{event['id']}")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()

    return Handler


def create_server(host: str, port: int, database: str | Path, public_base_url: str | None = None):
    store = EventStore(database)
    return ThreadingHTTPServer((host, port), make_handler(store, public_base_url))


def main() -> None:
    parser = argparse.ArgumentParser(description="Servidor RSS de prueba para Power Automate")
    parser.add_argument("--host", default=os.getenv("HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("PORT", "8000")))
    parser.add_argument("--database", default=os.getenv("DATABASE", "data/events.db"))
    args = parser.parse_args()
    public_base_url = os.getenv("PUBLIC_BASE_URL") or None
    server = create_server(args.host, args.port, args.database, public_base_url)
    print(f"Servidor listo en http://localhost:{args.port}")
    print(f"Feed local: http://localhost:{args.port}/feed.xml")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor detenido")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
