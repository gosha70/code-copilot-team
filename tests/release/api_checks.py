# Copyright (c) 2026 Gosha - All Rights Reserved.
# This software may be used and distributed according to the terms of the MIT license.

"""Assert the v2.0.0 API claims against a running server.

Every check here corresponds to something the release notes promise, and
fails loudly when the promise is not kept. The server is expected to be
serving the store built by synth_store.py, whose shape is passed in so
the expected numbers are derived rather than restated.

Usage:
  python3 tests/release/api_checks.py <base-url> <shape.json>

Exit 0 when every check passed, 1 otherwise. One line per check so the
orchestrator can fold the output into its own tally.
"""

from __future__ import annotations

import json
import pathlib
import sys
import urllib.error
import urllib.request

PASS = 0
FAIL = 0
BASE = ""

# What the session page draws per page; the large fixture session must be
# comfortably past it or the windowing claim is never exercised.
TIMELINE_PAGE_SIZE = 100


def get(path: str) -> tuple[int, object]:
    """GET returning (status, parsed-body). A non-2xx is data here, not an
    exception: several checks assert on the refusal itself."""
    try:
        with urllib.request.urlopen(f"{BASE}{path}", timeout=60) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"null")
        except (ValueError, OSError):
            return exc.code, None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return 0, {"transport_error": str(exc)}


def check(name: str, condition: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  PASS: {name}")
    else:
        FAIL += 1
        print(f"  FAIL: {name}" + (f" — {detail}" if detail else ""))
    return condition


def main() -> int:
    global BASE
    BASE = sys.argv[1].rstrip("/")
    shape = json.loads(pathlib.Path(sys.argv[2]).read_text())
    listable = shape["listable"]
    excluded = shape["excluded"]

    # ── the Sessions list says how long it is (#383) ──────────────────
    print("sessions list: total, limit, offset")
    status, body = get("/api/sessions")
    if not check("GET /api/sessions is 200", status == 200, str(body)[:200]):
        return 1
    check("total equals the listable population", body["total"] == listable,
          f"total={body['total']} expected={listable}")
    check("the first page is capped at limit", len(body["sessions"]) == body["limit"])
    check("offset starts at 0", body["offset"] == 0)
    check("noise is excluded and counted", body["excluded_noise"] == excluded,
          f"excluded_noise={body['excluded_noise']} expected={excluded}")

    # A page boundary is where an off-by-one lives: the union of the two
    # pages must be every row exactly once.
    s1, page1 = get("/api/sessions?limit=50&offset=0")
    s2, page2 = get("/api/sessions?limit=50&offset=50")
    if not check("both pages answered 200", s1 == 200 and s2 == 200, f"{s1}/{s2}"):
        return 1
    ids = [s["id"] for s in page1["sessions"]] + [s["id"] for s in page2["sessions"]]
    check("two pages cover the whole list with no gap", len(ids) == listable,
          f"covered={len(ids)} expected={listable}")
    check("two pages do not repeat a row", len(set(ids)) == len(ids))
    check("the last page is partial", len(page2["sessions"]) == listable - 50)
    _, past = get(f"/api/sessions?limit=50&offset={listable}")
    check("an offset past the end is empty, not an error", past["sessions"] == [])
    check("a page past the end still reports the total", past["total"] == listable)

    # Ordering must be total, or a row can appear on two pages. These
    # synthetic sessions share start times by construction.
    for sort in ("started_at", "turn_count", "error_count", "cost_usd"):
        _, a = get(f"/api/sessions?limit=40&offset=0&sort={sort}")
        _, b = get(f"/api/sessions?limit=40&offset=40&sort={sort}")
        combined = [s["id"] for s in a["sessions"]] + [s["id"] for s in b["sessions"]]
        check(f"sort={sort} pages without repeating a row",
              len(set(combined)) == len(combined))

    print("sessions list: refusals")
    check("limit 0 is refused", get("/api/sessions?limit=0")[0] == 400)
    check("negative offset is refused", get("/api/sessions?offset=-1")[0] == 400)
    check("an unknown sort is refused", get("/api/sessions?sort=nope")[0] == 400)
    check("an unknown order is refused", get("/api/sessions?order=sideways")[0] == 400)

    # ── filters combine, and the total follows them (#371 A2) ─────────
    print("filters narrow both rows and total")
    _, all_rows = get("/api/sessions?limit=200")
    model = all_rows["sessions"][0]["model"]
    _, filtered = get(f"/api/sessions?limit=200&model={model}")
    check("a model filter narrows the list", 0 < filtered["total"] <= listable)
    check("the filtered total equals the filtered rows",
          filtered["total"] == len(filtered["sessions"]),
          f"total={filtered['total']} rows={len(filtered['sessions'])}")
    check("every filtered row matches the filter",
          all(s["model"] == model for s in filtered["sessions"]))
    _, nothing = get("/api/sessions?query=no-such-project-anywhere-xyz")
    check("a filter matching nothing totals 0", nothing["total"] == 0)
    check("a filter matching nothing returns no rows", nothing["sessions"] == [])
    _, noisy = get("/api/sessions?include_noise=true&limit=200")
    check("include_noise adds exactly the excluded count",
          noisy["total"] == listable + excluded,
          f"{noisy['total']} != {listable} + {excluded}")

    # ── one session: turns, trace tree, lineage ───────────────────────
    print("session detail and the trace tree (#371 A1)")
    # Found by id, not by count: ingest also records the tool-result
    # records as turns, so the stored count is higher than the number of
    # exchanges written. What matters is that it is far past the window.
    big = [s for s in all_rows["sessions"] if s["session_id"] == shape["big_session_id"]]
    if check("the large session is present", bool(big),
             f"no session {shape['big_session_id']}"):
        check("it is long enough to force the timeline to window",
              big[0]["turn_count"] > TIMELINE_PAGE_SIZE,
              f"turn_count={big[0]['turn_count']} is not past {TIMELINE_PAGE_SIZE}")
        status, detail = get(f"/api/sessions/{big[0]['id']}")
        check("the large session loads", status == 200)
        check("the response carries every turn (the window is drawn, not fetched)",
              len(detail["turns"]) == big[0]["turn_count"],
              f"rows={len(detail['turns'])} count={big[0]['turn_count']}")
        calls = [c for t in detail["turns"] for c in t["tool_calls"]]
        check("it has tool calls", len(calls) > 0)
        check("a call with no recorded result is marked, not failed",
              any(c.get("has_result") is False for c in calls))
        check("a failed call is distinguishable from one with no result",
              any(c.get("has_result") and c.get("is_error") for c in calls))
    check("an unknown session is 404", get("/api/sessions/99999999")[0] == 404)

    print("lineage proven by turn identity (#371 A6)")
    # Both real resume forms must be found, and from the turn uuids
    # alone: one transcript keeps the predecessor's sessionId on the
    # carried records, the other rewrites it.
    for label, child_key, parent_key in [
        ("sessionId preserved", "resumed_child", "resumed_parent"),
        ("sessionId rewritten", "resumed_child_rewritten", "resumed_parent_rewritten"),
    ]:
        want_child = shape.get(child_key)
        want_parent = shape.get(parent_key)
        if not want_child:
            continue
        child = [s for s in all_rows["sessions"] if s["session_id"] == want_child]
        if not check(f"[{label}] the resumed session is present", bool(child)):
            continue
        status, view = get(f"/api/sessions/{child[0]['id']}/thread")
        if not check(f"[{label}] its lineage loads", status == 200, str(view)[:160]):
            continue
        # Named fields, not a substring search over the payload: the old
        # check matched a key that is present in every response and so
        # could not fail.
        check(f"[{label}] lineage is supported for this copilot",
              view.get("lineage_support") == "native",
              f"lineage_support={view.get('lineage_support')!r}")
        check(f"[{label}] the lineage assessment completed",
              view.get("assessment") == "complete",
              f"assessment={view.get('assessment')!r}")
        check(f"[{label}] an ancestor was found",
              view.get("no_ancestor_found") is False,
              f"no_ancestor_found={view.get('no_ancestor_found')!r}")
        thread = view.get("thread")
        check(f"[{label}] it belongs to a thread", isinstance(thread, dict))
        if isinstance(thread, dict):
            check(f"[{label}] the thread holds both sessions",
                  thread.get("member_count", 0) >= 2,
                  f"member_count={thread.get('member_count')}")
            # The parent must be named in the thread, by its own id.
            check(f"[{label}] the predecessor {want_parent} is a member",
                  want_parent in json.dumps(thread),
                  "the thread does not name the transcript it was resumed from")

    # ── feedback is a durable record (#371 A3) ────────────────────────
    # The documented refusal. A pair that shares uuids but falls below
    # max(s/|A|, s/|B|) >= 0.5 must NOT be presented as lineage; without
    # this, lowering the threshold would break no test.
    thin = shape.get("below_threshold_child")
    if thin:
        row = [s for s in all_rows["sessions"] if s["session_id"] == thin]
        if check("the below-threshold session is present", bool(row)):
            status, view = get(f"/api/sessions/{row[0]['id']}/thread")
            if check("its lineage loads", status == 200, str(view)[:160]):
                check("a pair under the containment threshold is not called lineage",
                      view.get("no_ancestor_found") is True,
                      f"no_ancestor_found={view.get('no_ancestor_found')!r} "
                      "— a weak overlap was presented as an ancestor")
                check("and the refusal still reports lineage as assessable",
                      view.get("lineage_support") == "native",
                      "a refusal must not masquerade as unsupported")

    print("feedback round trip (#371 A3)")
    target = all_rows["sessions"][0]["id"]
    status, vocab = get("/api/feedback/vocabulary")
    check("the feedback vocabulary loads", status == 200)
    if status == 200 and vocab.get("names"):
        name = vocab["names"][0]["name"] if isinstance(vocab["names"][0], dict) else vocab["names"][0]
        payload = json.dumps({"name": name, "value": True,
                              "rationale": "release check"}).encode()
        request = urllib.request.Request(
            f"{BASE}/api/sessions/{target}/feedback", data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        wrote = False
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                wrote = response.status in (200, 201)
        except urllib.error.HTTPError as exc:
            print(f"    (feedback POST returned {exc.code})")
        if check("feedback can be written", wrote):
            _, after = get(f"/api/sessions/{target}")
            check("the written feedback is read back",
                  any(r.get("rationale") == "release check" for r in after["feedback"]))

    # ── every page's endpoint answers ─────────────────────────────────
    print("every Studio surface has a live endpoint")
    for label, path in [
        ("dashboard KPIs", "/api/dashboard/kpis"),
        ("benchmark", "/api/dashboard/benchmark"),
        ("harness compare (#371 A4)", "/api/harness"),
        ("team (#174)", "/api/team"),
        ("runs (#190)", "/api/runs"),
        ("pipeline status", "/api/pipeline/status"),
        ("docs registry (Learn)", "/api/docs"),
        ("settings", "/api/settings"),
        ("label correlation", "/api/labels/correlation"),
        ("graph catalogue", "/api/graph/catalogue"),
    ]:
        status, payload = get(path)
        # A page with no data must still answer; only a 5xx or a dead
        # socket is a failure.
        check(f"{label} answers", status not in (0,) and status < 500,
              f"status={status} {str(payload)[:120]}")

    print(f"\napi checks: {PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    # An unhandled exception used to end the run quietly: the remaining
    # assertions simply never printed, and a caller tallying PASS/FAIL
    # lines saw no failure. Report it as one, loudly, and exit nonzero.
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - last line of defence
        import traceback
        traceback.print_exc()
        print(f"  FAIL: the API checks crashed before finishing — {exc!r}")
        print(f"\napi checks: {PASS} passed, {FAIL + 1} failed (run incomplete)")
        raise SystemExit(1)
