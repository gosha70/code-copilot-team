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


def check_profile(repo: Path, report: Report) -> dict:
    """The provider profile: schema-valid, and are the named keys exported?"""
    profile = Path(os.environ.get("CCT_PROVIDER_PROFILE", Path.home() / ".code-copilot-team/providers.toml"))
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
        env_name = body.get("api_key_env")
        if not env_name:
            continue
        # The NAME and whether it is set. Never the value.
        present = bool(os.environ.get(env_name))
        report.add("Providers", f"{name}: ${env_name}", OK if present else WARN,
                   "set" if present else "not set in this shell — export it in ~/.zshenv")
    return providers


def check_health(repo: Path, report: Report, providers: dict) -> None:
    script = repo / "scripts/providers-health.sh"
    if not providers:
        return
    if not script.is_file():
        report.add("Providers", "healthchecks", SKIP, "providers-health.sh not found")
        return
    code, out = run(["bash", str(script)], timeout=90)
    for line in out.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("="):
            continue
        low = stripped.lower()
        if "healthy" in low or "ok" in low or "unhealthy" in low or "fail" in low:
            status = BAD if ("unhealthy" in low or "fail" in low) else OK
            report.add("Providers", stripped[:70], status)
    if code not in (0, 1):
        report.add("Providers", "healthcheck run", BAD, f"exit {code}")


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
        providers = check_profile(repo, report)
        if not args.no_network:
            check_health(repo, report, providers)
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
