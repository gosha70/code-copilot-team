#!/usr/bin/env python3
"""`cct doctor` — is this machine ready to run the harness?

Common checks first, then delegation: an adapter's own diagnostics are the
authority on that adapter, so this never re-implements them. An adapter that
is not installed is reported absent, not failing — `cct` is provider-neutral
and assumes nothing is present.

Read-only, and it never prints a secret: for an API key it reports the
variable's NAME and whether it is set, never the value. The #353 review found
exactly that leak in the profile validator; this file is where it would be
most tempting to repeat.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

OK, WARN, BAD, SKIP = "ok", "warn", "fail", "skip"
MARK = {OK: "✓", WARN: "!", BAD: "✗", SKIP: "-"}
COLOR = {OK: "32", WARN: "33", BAD: "31", SKIP: "90"}

# A tool the harness needs, and what stops working without it.
TOOLS = [
    ("git", "everything: branches, worktrees, the origin gate", True),
    ("jq", "the auto-build driver and the review runner read JSON with it", True),
    ("python3", "session analytics, this command", True),
    ("ruby", "the capability and feature registries are read with it", False),
    ("node", "the Studio, the documentation site, the Pi runtime", False),
    ("gh", "opening a pull request at the end of an unattended run", False),
    ("curl", "provider healthchecks", True),
]


#: A variable NAME: what may be printed. Anything else is treated as a value.
ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]{0,63}")


def safe_env_label(value: object) -> str | None:
    """The printable form of an api_key_env field, or None if it is not a name.

    Returning None is the whole point: a field holding a pasted key has no
    printable form, so no caller can accidentally render it.
    """
    return f"${value}" if isinstance(value, str) and ENV_NAME.fullmatch(value) else None


class Report:
    def __init__(self, use_color: bool) -> None:
        self.rows: list[dict] = []
        self.use_color = use_color

    def add(self, section: str, name: str, status: str, detail: str = "") -> None:
        self.rows.append({"section": section, "check": name, "status": status, "detail": detail})

    def worst(self) -> str:
        if any(r["status"] == BAD for r in self.rows):
            return BAD
        if any(r["status"] == WARN for r in self.rows):
            return WARN
        return OK

    def print_human(self) -> None:
        section = None
        for row in self.rows:
            if row["section"] != section:
                section = row["section"]
                print(f"\n{section}")
            mark = MARK[row["status"]]
            if self.use_color:
                mark = f"\033[{COLOR[row['status']]}m{mark}\033[0m"
            detail = f"  — {row['detail']}" if row["detail"] else ""
            print(f"  {mark} {row['check']}{detail}")
        counts = {s: sum(1 for r in self.rows if r["status"] == s) for s in (OK, WARN, BAD, SKIP)}
        print(f"\n{counts[OK]} ok · {counts[WARN]} warning · {counts[BAD]} failed · {counts[SKIP]} skipped")
        if counts[BAD]:
            print("Something the harness needs is missing or broken; the lines marked ✗ say what.")
        elif counts[WARN]:
            print("Usable. The lines marked ! are optional or unconfigured.")


def run(cmd: list[str], timeout: int = 20) -> tuple[int, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except FileNotFoundError:
        return 127, "not installed"
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {timeout}s"


def check_tools(report: Report) -> None:
    for tool, why, required in TOOLS:
        path = shutil.which(tool)
        if path:
            report.add("Tools", tool, OK, path)
        else:
            report.add("Tools", tool, BAD if required else WARN, f"not installed — {why}")


SHIM_BAKED_LINE = re.compile(r'^CCT_REPO_DIR_DEFAULT="(?P<path>.*)"\s*$', re.MULTILINE)


def check_shim(report: Report) -> None:
    """The `cct` on PATH (#410). setup.sh installs a shim that execs
    scripts/cct in a baked checkout; a shim whose checkout has moved fails
    every command, so a passing doctor must have looked at the target."""
    shim = shutil.which("cct")
    if not shim:
        report.add("Tools", "cct", WARN, "not on PATH — `cct start` needs setup.sh --claude-code; ./scripts/cct works from a checkout")
        return
    try:
        text = Path(shim).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        report.add("Tools", "cct", BAD, f"{shim}: unreadable ({exc.strerror})")
        return
    match = SHIM_BAKED_LINE.search(text)
    if match is None:
        report.add("Tools", "cct", OK, f"{shim} (not the setup.sh shim)")
        return
    target = Path(os.environ.get("CCT_REPO_DIR") or match.group("path"))
    if (target / "scripts" / "cct").is_file():
        report.add("Tools", "cct", OK, f"{shim} → {target}")
    else:
        report.add("Tools", "cct", BAD, f"points at a checkout that is gone: {target} — set CCT_REPO_DIR or re-run setup.sh --claude-code")


GATEWAY_VAR = "ANTHROPIC_BASE_URL"
GATEWAY_COMPAT_VARS = ("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS", "ENABLE_TOOL_SEARCH", "DISABLE_FEEDBACK_COMMAND")
GATEWAY_GUIDE = "docs/dgx-spark/setup-cookbook.md"


def check_gateway(report: Report) -> None:
    """#399: a Claude Code gateway and its tool-compatibility settings.
    A text-completion healthcheck cannot see this failure: DeepSeek's
    Anthropic-compatible endpoint accepts prompts and rejects the dynamic
    `tool_definition` block Claude Code adds when a deferred tool loads
    (422 before inference). Names only, never values."""
    if not os.environ.get(GATEWAY_VAR):
        report.add("Gateway", "claude-code", OK, f"{GATEWAY_VAR} not set — native Anthropic endpoint")
        return
    # Value-aware (review of PR #425): only the two settings that remove the
    # dynamic block count. ENABLE_TOOL_SEARCH=true or auto keeps tool search
    # on, and tool search is what adds the block. These are documented
    # booleans, not secrets, so the deciding values are shown.
    betas_off = os.environ.get("CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS") == "1"
    tool_search = os.environ.get("ENABLE_TOOL_SEARCH", "")
    search_off = tool_search.lower() == "false"
    present = [v for v in GATEWAY_COMPAT_VARS if os.environ.get(v)]
    absent = [v for v in GATEWAY_COMPAT_VARS if not os.environ.get(v)]
    detail = f"{GATEWAY_VAR} set; " + (f"set: {', '.join(present)}" if present else "no compatibility variable set")
    if tool_search:
        detail += f" (ENABLE_TOOL_SEARCH={tool_search})"
    if absent:
        detail += f"; not set: {', '.join(absent)}"
    if betas_off or search_off:
        report.add("Gateway", "claude-code", OK, detail)
    else:
        report.add("Gateway", "claude-code", WARN,
                   detail + " — a gateway that rejects dynamic tool blocks (DeepSeek 422 tool_definition) needs "
                   "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS=1 or ENABLE_TOOL_SEARCH=false in a fresh session "
                   f"(ENABLE_TOOL_SEARCH=true does not avoid it); see {GATEWAY_GUIDE}")


def profile_path() -> Path:
    return Path(os.environ.get("CCT_PROVIDER_PROFILE", Path.home() / ".code-copilot-team/providers.toml"))


WIKI_CHECK_LINE = re.compile(r"^wiki-studio expected (?P<expected>\S+): (?P<state>\S+) \((?P<python>.*)\)$", re.MULTILINE)


def check_wiki(repo: Path, report: Report) -> None:
    """#384 FR-12: the wiki tooling as the launcher will run it. The same
    resolver (scripts/lib/wiki_env.sh, via setup-wiki.sh --check) decides
    the state, so a passing row means `./scripts/wiki` would run exactly
    the locked distribution in the repository venv; then `wiki info`
    reports the schema and manifest state from that very interpreter.
    System Python is never consulted."""
    setup = repo / "scripts" / "setup-wiki.sh"
    if not setup.is_file():
        report.add("Wiki", "wiki-studio", SKIP, "scripts/setup-wiki.sh not in this checkout")
        return
    rc, out = run(["bash", str(setup), "--check"])
    match = WIKI_CHECK_LINE.search(out)
    if match is None:
        report.add("Wiki", "wiki-studio", BAD, f"setup-wiki.sh --check gave no state (exit {rc}): {out.strip()[:120]}")
        return
    expected, state, python = match.group("expected"), match.group("state"), match.group("python")
    remedy = f"run: bash {setup}"
    extra = out.strip().splitlines()[1:]
    if state == "ok":
        report.add("Wiki", "wiki-studio", OK, f"{expected} in {python}")
    elif state == "no-venv":
        report.add("Wiki", "wiki-studio", WARN, f"no managed environment ({python} missing); {'; '.join(extra)}; {remedy}")
        return
    elif state.startswith("venv-unsupported:"):
        report.add("Wiki", "wiki-studio", WARN, f"the managed environment runs Python {state.split(':', 1)[1]}, outside the package's range — recreate it, then {remedy}")
        return
    elif state == "missing":
        report.add("Wiki", "wiki-studio", WARN, f"not installed in {python}; {remedy}")
        return
    elif state.startswith("mismatch:"):
        report.add("Wiki", "wiki-studio", WARN, f"{state.split(':', 1)[1]} installed in {python}, expected exactly {expected}; {remedy}")
        return
    else:
        report.add("Wiki", "wiki-studio", BAD, f"unexpected state '{state}' from setup-wiki.sh --check")
        return
    rc, out = run([str(repo / "scripts" / "wiki"), "info", "--json"])
    try:
        info = json.loads(out)
        contract = info["schema_contract"]
        manifest = info["manifest"]
    except (ValueError, KeyError, TypeError):
        report.add("Wiki", "schema", BAD, f"`wiki info --json` unreadable (exit {rc}) — the installed distribution does not behave like wiki-studio {expected}")
        return
    fingerprint = str(contract.get("fingerprint") or "")
    pin_file = repo / "tests" / "fixtures" / "wiki-schema" / "fingerprint.txt"
    try:
        pinned = pin_file.read_text(encoding="utf-8").strip()
    except OSError:
        pinned = ""
    if contract.get("drift"):
        report.add("Wiki", "schema", BAD, f"{contract.get('source')} schema drifted from the declared fingerprint ({fingerprint[:12]}…)")
    elif pinned and fingerprint != pinned:
        # Legacy mode declares no fingerprint, so this is the only check
        # that notices a local edit to an override document.
        report.add("Wiki", "schema", BAD, f"{contract.get('source')} schema fingerprint {fingerprint[:12]}… differs from the pinned {pinned[:12]}… — see knowledge/wiki/schema/POLICY.md")
    else:
        report.add("Wiki", "schema", OK, f"{contract.get('source')} schema, fingerprint {fingerprint[:12]}… matches the pin (knowledge/wiki/schema/POLICY.md)")
    report.add("Wiki", "manifest", OK, f"mode {manifest.get('mode')} ({manifest.get('state')})")


def check_profile(repo: Path, report: Report) -> dict:
    """The provider profile: schema-valid, and are the named keys exported?"""
    profile = profile_path()
    if not profile.is_file():
        report.add("Providers", "provider profile", WARN,
                   f"none at {profile} — peer review is off until one exists")
        return {}
    validator = repo / "scripts/validate-providers-profile.sh"
    if validator.is_file():
        code, out = run(["bash", str(validator), str(profile)])
        summary = next((l.strip() for l in out.split("\n") if "Provider profile:" in l), "")
        if code == 0:
            report.add("Providers", "profile validates", OK, summary)
        else:
            # The validator redacts values itself; its first finding is the
            # actionable line, and the command to see the rest is worth saying.
            first = next((l.strip()[6:].strip() for l in out.split("\n") if l.strip().startswith("FAIL:")), "")
            report.add("Providers", "profile validates", BAD,
                       f"{first or summary} — see scripts/validate-providers-profile.sh")
    else:
        report.add("Providers", "profile validates", SKIP, "validator not found (outside the repository)")

    providers: dict[str, dict] = {}
    try:
        import tomllib
        with open(profile, "rb") as fh:
            providers = (tomllib.load(fh).get("providers") or {})
    except ModuleNotFoundError:
        report.add("Providers", "profile parsed", SKIP, "tomllib needs python 3.11+")
        return {}
    except Exception as exc:  # noqa: BLE001 — reported, not raised
        report.add("Providers", "profile parsed", BAD, str(exc))
        return {}

    for name, body in sorted(providers.items()):
        # Read the field generically. `body.get("api_key_env")` is classified
        # by CodeQL as reading a credential — the literal contains "key" — and
        # the classification follows the value into every message built from
        # it, even though the value is only ever a variable NAME. A profile
        # field whose name ends in "_env" holds such a name by convention; the
        # value is validated below before anything is printed.
        env_name = next((v for k, v in sorted(body.items()) if k.endswith("_env")), None)
        if not env_name:
            continue
        # A variable NAME is safe to print; anything else may be the key
        # itself, pasted into the wrong field. Printing it would leak the
        # credential into a terminal and into CI logs — the exact failure
        # #353 fixed in the validator, reachable here through invalid input.
        label = safe_env_label(env_name)
        if label is None:
            report.add("Providers", f"{name}: api_key_env", BAD,
                       f"not a variable name — {len(str(env_name))} characters, redacted; "
                       "if a key was pasted here, rotate it and store the NAME instead")
            continue
        # Membership, not retrieval: doctor needs to know whether the variable
        # exists, and reading its value would pull a credential into this
        # process and into every downstream string. `in os.environ` answers the
        # question without the secret ever being loaded.
        present = env_name in os.environ
        report.add("Providers", f"{name}: {label}", OK if present else WARN,
                   "set" if present else "not set in this shell — export it in ~/.zshenv")
    return providers


def check_health(repo: Path, report: Report, providers: dict, profile: Path) -> None:
    """Run the provider healthchecks — against the profile we just validated."""
    script = repo / "scripts/providers-health.sh"
    if not providers:
        return
    if not script.is_file():
        report.add("Providers", "healthchecks", SKIP, "providers-health.sh not found")
        return
    # Without --profile the checks ran the DEFAULT profile's commands while
    # the validation above read a different file (#361 review).
    code, out = run(["bash", str(script), "--profile", str(profile)], timeout=90)

    # The script prints a fixed three-column table: PROVIDER STATUS HEALTHCHECK.
    # Matching "fail" anywhere in the output turned its own summary line,
    # "Result: 1 passed, 0 failed", into a failure.
    status_of = {"OK": OK, "FAIL": BAD, "SKIP": SKIP}
    # "  deepseek (openai-compatible) OK   curl …" — the provider column holds
    # a name AND a parenthesised type, so the status is not a fixed field.
    row = re.compile(r"^\s+(?P<name>\S+)(?:\s+\((?P<type>[^)]*)\))?\s+(?P<status>OK|FAIL|SKIP)\b")
    seen = 0
    for line in out.split("\n"):
        match = row.match(line)
        if not match or match.group("name") in ("PROVIDER", "--------"):
            continue
        seen += 1
        status = match.group("status")
        detail = {"OK": "reachable", "FAIL": "healthcheck failed",
                  "SKIP": "no healthcheck defined"}[status]
        report.add("Providers", f"{match.group('name')} healthcheck", status_of[status], detail)
    if seen == 0:
        # No table means the script did not get as far as checking anything.
        report.add("Providers", "healthchecks", BAD if code not in (0, 1) else WARN,
                   f"no provider rows in the output (exit {code})")


def check_repo(repo: Path, report: Report) -> None:
    if not (repo / ".git").exists():
        report.add("Repository", "clone", SKIP, "not run from a clone — repository checks skipped")
        return
    code, out = run(["git", "-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"])
    report.add("Repository", "branch", OK if code == 0 else BAD, out)
    for name, rel in (("feature catalog", "shared/features/catalog.yaml"),
                      ("capability registry", "shared/capabilities/catalog.yaml"),
                      ("learn registry", "scripts/session_analytics/config_data/learn-sections.json")):
        report.add("Repository", name, OK if (repo / rel).is_file() else BAD, rel)


def check_adapters(repo: Path, report: Report, only: str | None) -> None:
    """Delegate. An adapter's own diagnostics are the authority on it."""
    probes = {
        "claude-code": (["claude-code", "help"], "the launcher"),
        "pi": (["pi-code", "doctor"], "pi-code doctor"),
    }
    known = sorted(p.name for p in (repo / "adapters").iterdir() if p.is_dir()) if (repo / "adapters").is_dir() else []
    if only and only not in known:
        print(f"cct doctor: unknown adapter '{only}' (known: {', '.join(known)})", file=sys.stderr)
        raise SystemExit(2)
    for adapter in known:
        if only and adapter != only:
            continue
        probe = probes.get(adapter)
        if probe is None:
            report.add("Adapters", adapter, SKIP, "advisory adapter — files are written into a project, nothing to probe")
            continue
        cmd, label = probe
        if not shutil.which(cmd[0]):
            report.add("Adapters", adapter, SKIP, f"{cmd[0]} not installed — nothing to check")
            continue
        code, out = run(cmd, timeout=60)
        first = next((l for l in out.split("\n") if l.strip()), "")
        report.add("Adapters", f"{adapter} ({label})", OK if code == 0 else BAD, first[:70])


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cct doctor",
        description="Check this machine: tools, provider profile, repository registries, installed adapters.",
    )
    parser.add_argument("--adapter", metavar="ID", help="only this adapter's diagnostics")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--no-network", action="store_true", help="skip provider healthchecks")
    args = parser.parse_args()

    repo = Path(os.environ.get("CCT_REPO_DIR", Path(__file__).resolve().parents[2]))
    report = Report(use_color=sys.stdout.isatty() and not args.json)

    if not args.adapter:
        check_tools(report)
        check_shim(report)
        check_gateway(report)
        check_wiki(repo, report)
        providers = check_profile(repo, report)
        if not args.no_network:
            check_health(repo, report, providers, profile_path())
        else:
            report.add("Providers", "healthchecks", SKIP, "--no-network")
        check_repo(repo, report)
    check_adapters(repo, report, args.adapter)

    if args.json:
        print(json.dumps({"status": report.worst(), "checks": report.rows}, indent=2))
    else:
        report.print_human()
    raise SystemExit(1 if report.worst() == BAD else 0)


if __name__ == "__main__":
    main()
