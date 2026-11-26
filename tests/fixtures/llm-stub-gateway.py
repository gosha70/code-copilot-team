"""A local stub Anthropic Messages endpoint for the LLM catalog's probe
(#400 FR-15, slice S3), with one negative-control switch per capability.

It plays the model of the probe's canary (scripts/lib/llm-probe.sh):
- asked to run a shell command (the canary's line "Run this exact shell
  command with your Bash tool: <command>"), it calls the Bash tool with it;
- given the tool's result, it replies with the canary's marker, the canary
  token its system prompt gives, and the text the command printed;
- given an image in the prompt, it names the image's colour;
- asked to think, it returns a thinking block first.
Any other request (the harness's own background calls) gets a short text
reply. It answers streamed or not, as asked.

Every request is appended to a JSON-lines log: the path, the model, the
tools offered, whether it streamed or asked to think, the header names and
how it authenticated. A credential is logged only when it is one of the
probe tests' planted sentinels, so a real one can never reach the log.

Usage: llm-stub-gateway.py <log.jsonl> <port-file> [--switch <name>]...
The port is chosen by the system and written to <port-file>. Beside one
switch per capability, two answer with errors that decide nothing: a 500,
and a 404 that names the request path.
"""

from __future__ import annotations

import base64
import json
import re
import struct
import sys
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SWITCHES = {
    "drop-tool-calls",       # tool_call: never calls the tool it was asked to
    "ignore-tool-results",   # tool_result: answers without the tool's result
    "no-stream",             # streaming: a plain JSON body even when asked to stream
    "other-model",           # model_identity: reports another model id
    "ignore-system-prompt",  # system_prompt: leaves out the system prompt's token
    "reject-shape",          # behavioral failure: 400, the request shape refused
    "reject-auth",           # auth: 401, the credential refused
    "exceed-limits",         # limit_controls: reports more output than max_tokens
    "time-out",              # clean_exit: never answers
    "drop-reasoning",        # reasoning_control: no thinking block when asked to think
    "ignore-images",         # image_input: cannot say what the image shows
    "server-error",          # a transient error: 500, overloaded, never a verdict
    "not-found",             # 404 naming the request path, as Express-style proxies do
}
SENTINELS = {"probe-planted-credential", "probe-ambient-credential", "none"}
COMMAND_RE = re.compile(r"Run this exact shell command with your Bash tool: (.+)")
MARKER_RE = re.compile(r"CCT_PROBE_OK:[0-9a-f]+")
TOKEN_RE = re.compile(r"CCT_SYS_OK:[0-9a-f]+")
OTHER_MODEL = "stub-other-model"
BACKGROUND_REPLY = "stub-ok"
UNKNOWN_COLOUR = "unknown"
HANG_SEC = 3600
COLOURS = {"red": (255, 0, 0), "green": (0, 128, 0), "blue": (0, 0, 255),
           "black": (0, 0, 0), "white": (255, 255, 255)}


def _auth_seen(headers) -> dict:
    out = {}
    for name in ("authorization", "x-api-key"):
        value = headers.get(name)
        if value is None:
            continue
        bearer = value.lower().startswith("bearer ")
        token = value.split(" ", 1)[1] if bearer else value
        shown = token if token in SENTINELS else "<other>"
        out[name] = ("Bearer " + shown) if bearer else shown
    return out


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content
                       if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _prompt_text(messages: list) -> str:
    """The text of the user's own messages, never a tool's result."""
    return "\n".join(_text_of(m.get("content")) for m in messages
                     if isinstance(m, dict) and m.get("role") == "user")


def _last_tool_result(messages: list):
    if not messages or messages[-1].get("role") != "user":
        return None
    content = messages[-1].get("content")
    if not isinstance(content, list):
        return None
    for block in content:
        if isinstance(block, dict) and block.get("type") == "tool_result":
            return block.get("content", "")
    return None


def _prompt_image(messages: list):
    for m in messages:
        if not isinstance(m, dict) or m.get("role") != "user" or not isinstance(m.get("content"), list):
            continue
        for block in m["content"]:
            if isinstance(block, dict) and block.get("type") == "image":
                return (block.get("source") or {}).get("data")
    return None


def _png_colour(data_b64: str) -> str:
    """The colour of an 8-bit RGB or RGBA PNG's first pixel, by name."""
    try:
        raw = base64.b64decode(data_b64)
        pos, idat, colour_type = 8, b"", None
        while pos < len(raw):
            length, kind = struct.unpack(">I4s", raw[pos:pos + 8])
            chunk = raw[pos + 8:pos + 8 + length]
            if kind == b"IHDR":
                colour_type = chunk[9]
            elif kind == b"IDAT":
                idat += chunk
            pos += 12 + length
        if colour_type not in (2, 6):
            return UNKNOWN_COLOUR
        # The first row's first pixel follows its filter byte unchanged
        # under every filter type: it has no left or upper neighbour.
        rgb = tuple(zlib.decompress(idat)[1:4])
    except (ValueError, struct.error, zlib.error, IndexError):
        return UNKNOWN_COLOUR
    return min(COLOURS, key=lambda c: sum((a - b) ** 2 for a, b in zip(COLOURS[c], rgb)))


def _reply(body: dict, switches: set):
    """The content blocks and stop reason for one request."""
    messages = body.get("messages") or []
    prompt = _prompt_text(messages)
    marker = MARKER_RE.search(prompt)
    if not marker:
        return [{"type": "text", "text": BACKGROUND_REPLY}], "end_turn"
    blocks = []
    thinking = body.get("thinking") or {}
    if thinking.get("type") in ("enabled", "adaptive") and "drop-reasoning" not in switches:
        blocks.append({"type": "thinking", "thinking": "The canary asks for a fixed reply.",
                       "signature": "stub-signature"})
    image = _prompt_image(messages)
    if image is not None:
        colour = UNKNOWN_COLOUR if "ignore-images" in switches else _png_colour(image)
        blocks.append({"type": "text", "text": f"{marker.group(0)} {colour}"})
        return blocks, "end_turn"
    command = COMMAND_RE.search(prompt)
    result = _last_tool_result(messages)
    tools = {t.get("name") for t in body.get("tools") or [] if isinstance(t, dict)}
    if command and result is None and "Bash" in tools and "drop-tool-calls" not in switches:
        blocks.append({"type": "tool_use", "id": "toolu_stub_1", "name": "Bash",
                       "input": {"command": command.group(1).strip()}})
        return blocks, "tool_use"
    parts = [marker.group(0)]
    token = TOKEN_RE.search(_text_of(body.get("system")))
    if token and "ignore-system-prompt" not in switches:
        parts.append(token.group(0))
    if result is not None and "ignore-tool-results" not in switches:
        parts.append(_text_of(result).strip())
    blocks.append({"type": "text", "text": " ".join(parts)})
    return blocks, "end_turn"


class Handler(BaseHTTPRequestHandler):
    server_version = "llm-stub-gateway/1"
    log_path = ""
    switches: set = set()

    def log_message(self, fmt, *args):  # quiet: the JSON log is the record
        return

    def _record(self, body: dict, reply: str) -> None:
        entry = {
            "method": self.command,
            "path": self.path,
            "model": body.get("model"),
            "stream": bool(body.get("stream")),
            "tools": sorted(t.get("name", "") for t in body.get("tools") or [] if isinstance(t, dict)),
            "thinking": (body.get("thinking") or {}).get("type"),
            "max_tokens": body.get("max_tokens"),
            "header_names": sorted(h.lower() for h in self.headers.keys()),
            "auth": _auth_seen(self.headers),
            "switches": sorted(self.switches),
            "reply": reply,
        }
        with open(self.log_path, "a", encoding="utf-8") as fp:
            fp.write(json.dumps(entry, sort_keys=True) + "\n")

    def _read_json(self) -> dict:
        length = int(self.headers.get("content-length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

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
            self.wfile.write(f"event: {name}\ndata: {json.dumps(payload)}\n\n".encode())
            self.wfile.flush()

    def _error(self, status: int, kind: str, message: str, body: dict) -> None:
        self._record(body, f"error:{status}")
        self._send(status, {"type": "error", "error": {"type": kind, "message": message}})

    def do_GET(self):
        if self.path.split("?", 1)[0].rstrip("/").endswith("/models"):
            self._record({}, "models")
            self._send(200, {"data": [{"id": "stub-model", "type": "model"}], "has_more": False})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):
        body = self._read_json()
        path = self.path.split("?", 1)[0].rstrip("/")
        if path.endswith("/messages/count_tokens"):
            self._record(body, "count_tokens")
            self._send(200, {"input_tokens": 10})
            return
        if not path.endswith("/messages"):
            self._record(body, "not-found")
            self._send(404, {"error": "not found"})
            return
        if "reject-auth" in self.switches:
            self._error(401, "authentication_error", "invalid x-api-key", body)
            return
        if "reject-shape" in self.switches:
            self._error(400, "invalid_request_error", "stub: this endpoint does not accept the request shape", body)
            return
        if "server-error" in self.switches:
            self._error(500, "overloaded_error", "stub: overloaded", body)
            return
        if "not-found" in self.switches:
            self._error(404, "not_found_error", f"Cannot POST {self.path}", body)
            return
        if "time-out" in self.switches:
            self._record(body, "hang")
            time.sleep(HANG_SEC)
            return
        blocks, stop = _reply(body, self.switches)
        model = OTHER_MODEL if "other-model" in self.switches else (body.get("model") or "stub-model")
        out = 5
        if "exceed-limits" in self.switches:
            out = int(body.get("max_tokens") or 0) + 1000
        message = {"id": "msg_stub", "type": "message", "role": "assistant", "model": model,
                   "content": blocks, "stop_reason": stop, "stop_sequence": None,
                   "usage": {"input_tokens": 10, "output_tokens": out}}
        kinds = "+".join(b["type"] for b in blocks)
        if not body.get("stream") or "no-stream" in self.switches:
            self._record(body, f"json:{kinds}")
            self._send(200, message)
            return
        self._record(body, f"sse:{kinds}")
        events = [("message_start", {"type": "message_start",
                                     "message": dict(message, content=[], stop_reason=None,
                                                     usage={"input_tokens": 10, "output_tokens": 1})})]
        for i, block in enumerate(blocks):
            if block["type"] == "text":
                events += [("content_block_start", {"type": "content_block_start", "index": i,
                                                    "content_block": {"type": "text", "text": ""}}),
                           ("content_block_delta", {"type": "content_block_delta", "index": i,
                                                    "delta": {"type": "text_delta", "text": block["text"]}})]
            elif block["type"] == "tool_use":
                events += [("content_block_start", {"type": "content_block_start", "index": i,
                                                    "content_block": dict(block, input={})}),
                           ("content_block_delta", {"type": "content_block_delta", "index": i,
                                                    "delta": {"type": "input_json_delta",
                                                              "partial_json": json.dumps(block["input"])}})]
            else:
                events += [("content_block_start", {"type": "content_block_start", "index": i,
                                                    "content_block": {"type": "thinking", "thinking": ""}}),
                           ("content_block_delta", {"type": "content_block_delta", "index": i,
                                                    "delta": {"type": "thinking_delta",
                                                              "thinking": block["thinking"]}}),
                           ("content_block_delta", {"type": "content_block_delta", "index": i,
                                                    "delta": {"type": "signature_delta",
                                                              "signature": block["signature"]}})]
            events.append(("content_block_stop", {"type": "content_block_stop", "index": i}))
        events += [("message_delta", {"type": "message_delta",
                                      "delta": {"stop_reason": stop, "stop_sequence": None},
                                      "usage": {"output_tokens": out}}),
                   ("message_stop", {"type": "message_stop"})]
        self._sse(events)


def main() -> int:
    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    log_path, port_file, rest = args[0], args[1], args[2:]
    switches = set()
    while rest:
        if rest[0] != "--switch" or len(rest) < 2 or rest[1] not in SWITCHES:
            print(f"llm-stub-gateway: unknown argument {rest[0]!r}; switches: {' '.join(sorted(SWITCHES))}",
                  file=sys.stderr)
            return 2
        switches.add(rest[1])
        rest = rest[2:]
    Handler.log_path = log_path
    Handler.switches = switches
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    with open(port_file, "w", encoding="utf-8") as fp:
        fp.write(str(server.server_address[1]))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
