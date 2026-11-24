"""A local stub LLM endpoint for the #400 captures (S0).

It answers OpenAI Responses (POST .../responses), OpenAI Chat Completions
(POST .../chat/completions) and Anthropic Messages (POST .../messages),
streamed or not, with one fixed assistant message, and lists models at
GET .../models. Every request is appended to a JSON-lines log: the path,
the protocol, the model asked for, whether it streamed, the header names
it carried, and how it authenticated. An authentication value is logged
only when it is one of the capture's planted sentinels; anything else is
logged as "<other>", so a real credential can never reach the log.

Usage: capture-stub.py <log.jsonl> <port-file>
The port is chosen by the system and written to <port-file>.
"""

from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPLY = "stub-ok"
SENTINELS = {"capture-planted-credential", "capture-ambient-credential", "none"}


def _auth_seen(headers) -> dict:
    out = {}
    for name in ("authorization", "x-api-key", "api-key"):
        value = headers.get(name)
        if value is None:
            continue
        token = value.split(" ", 1)[1] if value.lower().startswith("bearer ") else value
        shown = token if token in SENTINELS else "<other>"
        out[name] = ("Bearer " + shown) if value.lower().startswith("bearer ") else shown
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "capture-stub/1"
    log_path = ""

    def log_message(self, fmt, *args):  # quiet: the JSON log is the record
        return

    def _record(self, protocol: str, body: dict) -> None:
        entry = {
            "method": self.command,
            "path": self.path,
            "protocol": protocol,
            "model": body.get("model"),
            "stream": bool(body.get("stream")),
            "tools": len(body.get("tools") or []),
            "header_names": sorted(h.lower() for h in self.headers.keys()),
            "auth": _auth_seen(self.headers),
        }
        with open(self.log_path, "a", encoding="utf-8") as fp:
            fp.write(json.dumps(entry, sort_keys=True) + "\n")

    def _read_json(self) -> dict:
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            return {}

    def _send(self, status: int, payload: dict) -> None:
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _sse(self, events: list) -> None:
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.send_header("cache-control", "no-cache")
        self.end_headers()
        for name, payload in events:
            chunk = ""
            if name:
                chunk += f"event: {name}\n"
            chunk += "data: " + (payload if isinstance(payload, str) else json.dumps(payload)) + "\n\n"
            self.wfile.write(chunk.encode())
            self.wfile.flush()

    def do_GET(self):
        if self.path.rstrip("/").endswith("/models"):
            self._record("models", {})
            self._send(200, {"object": "list", "data": [{"id": "capture-model", "object": "model"}]})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        body = self._read_json()
        path = self.path.split("?", 1)[0].rstrip("/")
        model = body.get("model") or "capture-model"
        now = int(time.time())
        if path.endswith("/responses"):
            self._record("openai-responses", body)
            item = {"id": "msg_1", "type": "message", "status": "completed", "role": "assistant",
                    "content": [{"type": "output_text", "text": REPLY, "annotations": []}]}
            usage = {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}
            done = {"id": "resp_1", "object": "response", "created_at": now, "status": "completed",
                    "model": model, "output": [item], "usage": usage}
            if not body.get("stream"):
                self._send(200, done)
                return
            started = dict(done, status="in_progress", output=[])
            self._sse([
                ("response.created", {"type": "response.created", "response": started}),
                ("response.output_item.added", {"type": "response.output_item.added", "output_index": 0,
                                                "item": dict(item, status="in_progress", content=[])}),
                ("response.output_text.delta", {"type": "response.output_text.delta", "item_id": "msg_1",
                                                "output_index": 0, "content_index": 0, "delta": REPLY}),
                ("response.output_item.done", {"type": "response.output_item.done", "output_index": 0,
                                               "item": item}),
                ("response.completed", {"type": "response.completed", "response": done}),
            ])
            return
        if path.endswith("/chat/completions"):
            self._record("openai-chat", body)
            if not body.get("stream"):
                self._send(200, {"id": "chat_1", "object": "chat.completion", "created": now, "model": model,
                                 "choices": [{"index": 0, "finish_reason": "stop",
                                              "message": {"role": "assistant", "content": REPLY}}],
                                 "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}})
                return
            base = {"id": "chat_1", "object": "chat.completion.chunk", "created": now, "model": model}
            self._sse([
                (None, dict(base, choices=[{"index": 0, "delta": {"role": "assistant", "content": REPLY},
                                            "finish_reason": None}])),
                (None, dict(base, choices=[{"index": 0, "delta": {}, "finish_reason": "stop"}],
                            usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2})),
                (None, "[DONE]"),
            ])
            return
        if path.endswith("/messages"):
            self._record("anthropic-messages", body)
            message = {"id": "msg_1", "type": "message", "role": "assistant", "model": model,
                       "content": [{"type": "text", "text": REPLY}], "stop_reason": "end_turn",
                       "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}}
            if not body.get("stream"):
                self._send(200, message)
                return
            self._sse([
                ("message_start", {"type": "message_start", "message": dict(message, content=[], stop_reason=None)}),
                ("content_block_start", {"type": "content_block_start", "index": 0,
                                         "content_block": {"type": "text", "text": ""}}),
                ("content_block_delta", {"type": "content_block_delta", "index": 0,
                                         "delta": {"type": "text_delta", "text": REPLY}}),
                ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
                                   "usage": {"output_tokens": 1}}),
                ("message_stop", {"type": "message_stop"}),
            ])
            return
        self._record("unknown", body)
        self._send(404, {"error": "not found"})


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    Handler.log_path = sys.argv[1]
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    with open(sys.argv[2], "w", encoding="utf-8") as fp:
        fp.write(str(server.server_address[1]))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
