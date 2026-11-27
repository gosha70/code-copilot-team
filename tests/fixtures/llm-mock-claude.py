"""A stand-in for `claude -p` in the LLM catalog's probe tests (#400 FR-15,
slice S3). CCT_LLM_PROBE_CMD runs it in place of Claude Code, behind the
stub gateway (llm-stub-gateway.py), as the real binary runs in the S3
capture.

It speaks to ANTHROPIC_BASE_URL as Claude Code 2.1.332 was seen to:
- it streams from POST <base>/v1/messages?beta=true, with the system
  prompt it appends, the Bash tool, adaptive thinking, the model of
  ANTHROPIC_MODEL and max_tokens from CLAUDE_CODE_MAX_OUTPUT_TOKENS;
- with --output-format stream-json it prints one assistant record per
  content block, the stream's events under --include-partial-messages, a
  user record for each tool result, and a result record;
- it runs the Bash tool calls --allowedTools allows (Bash: any command;
  Bash(<command>): exactly that one), in its working directory, and sends
  their output back; any other call is refused, as a headless run cannot
  ask, and listed in the result's permission_denials;
- a refused credential (401, 403) gets an api_retry record per retry, up
  to CLAUDE_CODE_MAX_RETRIES, then an error result; a rejected request
  (400, 422) gets "API Error: <status> <message>" at once, from the model
  "<synthetic>"; a plain JSON body where a stream was asked for is read as
  the reply.
Like Claude Code, it sends the model without a context suffix: "model[1m]"
goes out as "model".
With CCT_PROBE_MOCK_ENV_LOG set, it writes the names of the variables it
received to that file, and the names of any whose value is a probe test's
planted sentinel. Three switches make it misbehave as a harness can:
CCT_PROBE_MOCK_CRASH=1 kills it with SIGSEGV after its answer (=image: only
on a run whose prompt comes as stream-json, the probe's image run),
CCT_PROBE_MOCK_GARBAGE=1 prints a line that is not JSON instead of its
records, and CCT_PROBE_MOCK_IGNORE_TERM=1 ignores TERM, so that only the
watchdog's KILL ends it. `--version` prints 2.1.332.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
import urllib.error
import urllib.request

VERSION = "2.1.332 (Claude Code)"
BASE_SYSTEM = "You are a coding assistant run headless for a health check."
DEFAULT_MAX_TOKENS = 32000
DEFAULT_MAX_RETRIES = 10
MAX_TURNS = 10
TOOL_TIMEOUT_SEC = 60
SENTINEL_VALUES = {"probe-ambient-credential", "probe-ambient-switch"}
NOT_LOGGED_IN = "Not logged in · Please run /login"
TOOLS = [
    {"name": "Bash", "description": "Run a shell command.",
     "input_schema": {"type": "object", "properties": {"command": {"type": "string"}},
                      "required": ["command"]}},
    {"name": "Read", "description": "Read a file.",
     "input_schema": {"type": "object", "properties": {"file_path": {"type": "string"}},
                      "required": ["file_path"]}},
]
FLAGS = {"-p", "--print", "--verbose", "--include-partial-messages", "--no-session-persistence"}
CRASH_AFTER_ANSWER = False
RULE_RE = re.compile(r"([A-Za-z]+)(?:\(([^)]*)\))?")
DENIALS: list = []
VALUED = {"--output-format", "--input-format", "--append-system-prompt", "--allowedTools",
          "--permission-mode"}


def emit(record: dict) -> None:
    sys.stdout.write(json.dumps(record) + "\n")
    sys.stdout.flush()


def finish(text: str, is_error: bool, turns: int, output_tokens: int) -> int:
    emit({"type": "result", "subtype": "success", "is_error": is_error, "result": text,
          "num_turns": turns, "usage": {"output_tokens": output_tokens}, "permission_denials": DENIALS})
    if CRASH_AFTER_ANSWER:
        os.kill(os.getpid(), signal.SIGSEGV)
    return 1 if is_error else 0


def synthetic(text: str, error: str | None = None) -> None:
    record = {"type": "assistant",
              "message": {"model": "<synthetic>", "role": "assistant",
                          "content": [{"type": "text", "text": text}],
                          "usage": {"input_tokens": 0, "output_tokens": 0}}}
    if error:
        record["error"] = error
    emit(record)


def parse_args(argv: list) -> dict:
    opts, i = {}, 0
    while i < len(argv):
        a = argv[i]
        if a in FLAGS:
            opts[a] = True
            i += 1
        elif a in VALUED and i + 1 < len(argv):
            opts[a] = argv[i + 1]
            i += 2
        else:
            print(f"error: unknown option '{a}'", file=sys.stderr)
            sys.exit(1)
    return opts


def log_env() -> None:
    path = os.environ.get("CCT_PROBE_MOCK_ENV_LOG")
    if not path:
        return
    with open(path, "w", encoding="utf-8") as fp:
        json.dump({"names": sorted(os.environ),
                   "sentinel_values": sorted(k for k, v in os.environ.items() if v in SENTINEL_VALUES)}, fp)


def read_sse(resp, partial: bool) -> dict:
    """The message a stream of Anthropic events builds."""
    message, blocks, inputs, name = {}, {}, {}, None
    for raw in resp:
        line = raw.decode("utf-8", "replace").rstrip("\n")
        if line.startswith("event:"):
            name = line[6:].strip()
            continue
        if not line.startswith("data:"):
            continue
        event = json.loads(line[5:].strip())
        if partial:
            emit({"type": "stream_event", "event": event})
        kind = event.get("type", name)
        if kind == "message_start":
            message = dict(event["message"])
        elif kind == "content_block_start":
            blocks[event["index"]] = dict(event["content_block"])
        elif kind == "content_block_delta":
            block, delta = blocks[event["index"]], event["delta"]
            if delta.get("type") == "text_delta":
                block["text"] = block.get("text", "") + delta["text"]
            elif delta.get("type") == "thinking_delta":
                block["thinking"] = block.get("thinking", "") + delta["thinking"]
            elif delta.get("type") == "signature_delta":
                block["signature"] = delta["signature"]
            elif delta.get("type") == "input_json_delta":
                inputs[event["index"]] = inputs.get(event["index"], "") + delta["partial_json"]
        elif kind == "message_delta":
            message.update(event.get("delta") or {})
            message["usage"] = dict(message.get("usage") or {}, **(event.get("usage") or {}))
    for index, text in inputs.items():
        blocks[index]["input"] = json.loads(text or "{}")
    message["content"] = [blocks[i] for i in sorted(blocks)]
    return message


def bash_allowed(command: str, allowed: str) -> bool:
    """As Claude Code reads --allowedTools: Bash allows any command,
    Bash(<command>) exactly that one; a command with anything more needs
    approval, which a headless run cannot give."""
    for tool, exact in RULE_RE.findall(allowed):
        if tool == "Bash" and (exact == "" or exact.strip() == command.strip()):
            return True
    return False


def run_tool(block: dict, allowed: str):
    """The tool's output, and whether it was refused."""
    command = block.get("input", {}).get("command", "")
    if block.get("name") != "Bash" or not bash_allowed(command, allowed):
        DENIALS.append({"tool_name": block.get("name"), "tool_use_id": block.get("id"),
                        "tool_input": block.get("input", {})})
        return f"{command} needs approval", True
    done = subprocess.run(["bash", "-c", command], capture_output=True, text=True, timeout=TOOL_TIMEOUT_SEC)
    return (done.stdout + done.stderr).strip(), False


def main() -> int:
    argv = sys.argv[1:]
    if argv == ["--version"]:
        print(VERSION)
        return 0
    global CRASH_AFTER_ANSWER
    opts = parse_args(argv)
    log_env()
    crash = os.environ.get("CCT_PROBE_MOCK_CRASH")
    CRASH_AFTER_ANSWER = crash == "1" or (crash == "image" and opts.get("--input-format") == "stream-json")
    if os.environ.get("CCT_PROBE_MOCK_IGNORE_TERM") == "1":
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if os.environ.get("CCT_PROBE_MOCK_GARBAGE") == "1":
        print("mock: this is not JSON")
        return 0
    partial = bool(opts.get("--include-partial-messages"))
    if opts.get("--input-format") == "stream-json":
        messages = [json.loads(l)["message"] for l in sys.stdin.read().splitlines() if l.strip()]
    else:
        messages = [{"role": "user", "content": sys.stdin.read()}]
    model = re.sub(r"\[[0-9A-Za-z]+\]$", "", os.environ.get("ANTHROPIC_MODEL", "claude-default"))
    system = BASE_SYSTEM + ("\n\n" + opts["--append-system-prompt"] if opts.get("--append-system-prompt") else "")
    headers = {"content-type": "application/json", "anthropic-version": "2023-06-01"}
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        headers["authorization"] = "Bearer " + os.environ["ANTHROPIC_AUTH_TOKEN"]
    elif os.environ.get("ANTHROPIC_API_KEY"):
        headers["x-api-key"] = os.environ["ANTHROPIC_API_KEY"]
    base = os.environ.get("ANTHROPIC_BASE_URL", "").rstrip("/")
    max_tokens = int(os.environ.get("CLAUDE_CODE_MAX_OUTPUT_TOKENS") or DEFAULT_MAX_TOKENS)
    max_retries = int(os.environ.get("CLAUDE_CODE_MAX_RETRIES") or DEFAULT_MAX_RETRIES)
    emit({"type": "system", "subtype": "init", "model": model, "tools": [t["name"] for t in TOOLS]})
    if not base:
        synthetic(NOT_LOGGED_IN, "authentication_failed")
        return finish(NOT_LOGGED_IN, True, 1, 0)

    turns, output_tokens = 0, 0
    while turns < MAX_TURNS:
        turns += 1
        body = {"model": model, "max_tokens": max_tokens, "stream": True,
                "system": [{"type": "text", "text": system}], "messages": messages,
                "tools": TOOLS, "thinking": {"type": "adaptive"}}
        attempt = 0
        while True:
            req = urllib.request.Request(base + "/v1/messages?beta=true", data=json.dumps(body).encode(),
                                         headers=headers, method="POST")
            try:
                resp = urllib.request.urlopen(req)
                break
            except urllib.error.HTTPError as err:
                detail = err.read().decode("utf-8", "replace")
                try:
                    msg = json.loads(detail).get("error", {}).get("message", detail)
                except ValueError:
                    msg = detail
                if err.code in (400, 422):
                    text = f"API Error: {err.code} {msg}"
                    synthetic(text)
                    return finish(text, True, turns, output_tokens)
                auth = err.code in (401, 403)
                if attempt >= max_retries:
                    text = NOT_LOGGED_IN if auth else f"API Error: {err.code} {msg}"
                    synthetic(text, "authentication_failed" if auth else None)
                    return finish(text, True, turns, output_tokens)
                attempt += 1
                emit({"type": "system", "subtype": "api_retry", "attempt": attempt,
                      "max_retries": max_retries, "retry_delay_ms": 0, "error_status": err.code,
                      "error": "authentication_failed" if auth else "server_error"})
            except urllib.error.URLError as err:
                text = f"API Error: Connection error. {err.reason}"
                synthetic(text)
                return finish(text, True, turns, output_tokens)
        with resp:
            if resp.headers.get("content-type", "").startswith("text/event-stream"):
                message = read_sse(resp, partial)
            else:
                message = json.loads(resp.read())
        output_tokens += int((message.get("usage") or {}).get("output_tokens") or 0)
        for block in message.get("content", []):
            emit({"type": "assistant",
                  "message": {"id": message.get("id"), "model": message.get("model"), "role": "assistant",
                              "content": [block], "usage": {"input_tokens": 10, "output_tokens": 1}}})
        if message.get("stop_reason") != "tool_use":
            text = "".join(b.get("text", "") for b in message.get("content", []) if b.get("type") == "text")
            return finish(text, False, turns, output_tokens)
        results = []
        for b in message.get("content", []):
            if b.get("type") == "tool_use":
                text, refused = run_tool(b, opts.get("--allowedTools", ""))
                results.append({"type": "tool_result", "tool_use_id": b["id"], "content": text, "is_error": refused})
        emit({"type": "user", "message": {"role": "user", "content": results}})
        messages = messages + [{"role": "assistant", "content": message.get("content", [])},
                               {"role": "user", "content": results}]
    return finish("error: too many turns", True, turns, output_tokens)


if __name__ == "__main__":
    sys.exit(main())
