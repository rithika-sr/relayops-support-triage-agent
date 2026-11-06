"""A small local HTTP service shaped like the GitHub Issues REST API, for connector tests.

It implements only what the connector uses. `mode` scripts failures: "ok", "reject" (422 on create),
"unauthorized" (401 everywhere), "lose_response" (create succeeds, then the connection is dropped), and
"server_error" (500 on create, nothing created).
"""

from __future__ import annotations

import json
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse


class FakeGitHub:
    def __init__(self, repo: str = "acme/support") -> None:
        self.repo, self.token, self.mode = repo, secrets.token_urlsafe(16), "ok"
        self.issues: list[dict[str, Any]] = []
        self.requests: list[tuple[str, str]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_: Any) -> None:
                pass

            def _json(self, code: int, body: Any) -> None:
                raw = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def _auth(self) -> bool:
                if fake.mode == "unauthorized" or self.headers.get("Authorization") != f"Bearer {fake.token}":
                    self._json(401, {"message": "Bad credentials"})
                    return False
                return True

            def do_GET(self) -> None:
                u = urlparse(self.path)
                fake.requests.append(("GET", u.path))
                if not self._auth():
                    return
                if u.path == f"/repos/{fake.repo}":
                    self._json(200, {"full_name": fake.repo, "permissions": {"push": True}})
                elif u.path == f"/repos/{fake.repo}/issues":
                    q = parse_qs(u.query)
                    page, per = int(q.get("page", ["1"])[0]), int(q.get("per_page", ["30"])[0])
                    label = q.get("labels", [None])[0]
                    rows = [i for i in fake.issues if not label or label in i["labels"]]
                    self._json(200, rows[(page - 1) * per : page * per])
                else:
                    self._json(404, {"message": "Not Found"})

            def do_POST(self) -> None:
                u = urlparse(self.path)
                fake.requests.append(("POST", u.path))
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
                if not self._auth():
                    return
                if u.path != f"/repos/{fake.repo}/issues":
                    self._json(404, {"message": "Not Found"})
                    return
                if fake.mode == "reject" or not body.get("title"):
                    self._json(422, {"message": "Validation Failed"})
                    return
                if fake.mode == "server_error":
                    self._json(500, {"message": "Server Error"})
                    return
                issue = {
                    "number": len(fake.issues) + 1,
                    "title": body["title"],
                    "body": body.get("body", ""),
                    "labels": body.get("labels", []),
                    "state": "open",
                }
                fake.issues.append(issue)
                if fake.mode == "lose_response":
                    self.close_connection = True
                    self.connection.close()
                    return
                self._json(201, issue)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self) -> FakeGitHub:
        self.thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        self.server.shutdown()
        self.server.server_close()
