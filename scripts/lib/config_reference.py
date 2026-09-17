#!/usr/bin/env python3
"""Render the configuration reference from the schemas and defaults.

Called by scripts/generate-config-reference.sh; see that script for the
source list and the drift gate. Every row here is read from a file that
already describes the setting — nothing in this module invents prose about
a key, and a source that cannot be read is an error, never an empty table.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HEADER = """# Configuration Reference

> **GENERATED — do not edit.** Run `scripts/generate-config-reference.sh` to
> regenerate. Sources of truth: `shared/schemas/automation.schema.json`,
> `shared/schemas/providers.schema.json`,
> `scripts/session_analytics/config_data/defaults.json`, and the environment
> names in `scripts/session_analytics/config.py`. To change an entry, edit
> the source — a drift guard (`--check`) fails the build if this file is stale.

Every setting the harness reads, by the file it lives in. On a machine with
the harness installed, `cct config explain <key>` answers the same questions
for one key — including the value in effect and which layer set it — and
`cct config validate` runs every validator below.

Three rules hold across all of them:

- **A key's default lives with its schema or defaults file, never in prose.**
- **Secrets are named, not stored:** a profile or config holds the *name* of
  an environment variable; the value stays in your shell.
- **More specific wins:** defaults file, then user config, then the
  environment, then command-line arguments.
"""


def die(msg: str) -> "NoReturn":  # type: ignore[valid-type]
    print(f"[ERROR] {msg}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> dict:
    if not path.is_file():
        die(f"source not found: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        die(f"{path} is not valid JSON: {exc}")


def one_line(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).replace("|", "\\|")


def type_of(spec: dict) -> str:
    if "enum" in spec:
        return " \\| ".join(f"`{v}`" for v in spec["enum"])
    if "$ref" in spec:
        return f"see `{spec['$ref'].rsplit('/', 1)[-1]}`"
    t = spec.get("type")
    if isinstance(t, list):
        return " \\| ".join(t)
    if t == "array":
        item = spec.get("items", {})
        return f"array of {item.get('type', 'values')}"
    return t or "—"


def schema_rows(node: dict, defs: dict, prefix: str = "", depth: int = 0) -> list[tuple[str, str, str, str]]:
    """(key, type, required, description) for every documented property."""
    rows: list[tuple[str, str, str, str]] = []
    props = node.get("properties") or {}
    required = set(node.get("required") or [])
    for name, spec in props.items():
        resolved = spec
        if "$ref" in spec:
            ref = defs.get(spec["$ref"].rsplit("/", 1)[-1], {})
            resolved = {**ref, **{k: v for k, v in spec.items() if k != "$ref"}}
        key = f"{prefix}.{name}" if prefix else name
        rows.append((key, type_of(resolved), "yes" if name in required else "",
                     one_line(resolved.get("description", ""))))
        if depth < 2 and (resolved.get("properties")):
            rows += schema_rows(resolved, defs, key, depth + 1)
    return rows


def table(rows: list[tuple[str, str, str, str]], head: tuple[str, ...]) -> str:
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def automation_section(repo: Path) -> str:
    schema = load_json(repo / "shared/schemas/automation.schema.json")
    defs = schema.get("$defs", {})
    rows = [(f"`{k}`", t, req, desc) for k, t, req, desc in schema_rows(schema, defs)]
    if not rows:
        die("automation schema produced no rows")
    described = sum(1 for r in rows if r[3])
    note = ""
    if described < len(rows):
        note = (f"\n{len(rows) - described} of these keys carry no description in the schema; "
                "their shape is still enforced by `scripts/validate-automation-config.sh`, "
                "which refuses any key the schema does not declare.\n")
    return (f"""## `specs/<feature-id>/automation.json`

Per-feature automation contract for an auto-build run: which phases exist,
how the branch is named, what counts as a passing test, which reviewer
gates, and the caps that stop the run. Written from
`shared/templates/sdd/automation-template.json` by `/auto-build`, validated
by `scripts/validate-automation-config.sh`. The schema is closed: an
unknown key is an error, not an ignored line.
{note}
{table(rows, ("Key", "Type", "Required", "What it does"))}
""")


def providers_section(repo: Path) -> str:
    schema = load_json(repo / "shared/schemas/providers.schema.json")
    defs = schema.get("$defs", {})
    provider = defs.get("provider") or die("providers schema has no $defs.provider")
    rows = [(f"`{k}`", type_of(v), "yes" if k in (provider.get("required") or []) else "",
             one_line(v.get("description", "")))
            for k, v in provider["properties"].items()]
    top = []
    for name, spec in schema["properties"].items():
        if name == "providers":
            continue
        for key, sub in (spec.get("patternProperties") or spec.get("properties") or {}).items():
            label = key.replace("^", "").replace("$", "").replace("\\\\", "").replace("\\", "")
            top.append((f"`[{name}] {label}`", type_of(sub), "", one_line(sub.get("description", ""))))
    return (f"""## `~/.code-copilot-team/providers.toml`

The reviewers available on this machine and the default pairings. Seeded by
`setup.sh` from `shared/templates/provider-profile-template.toml`; validated
by `scripts/validate-providers-profile.sh`.

**Two parsing rules that bite.** The profile parser keeps everything after
`=` as the value, so a trailing `# comment` on a value line becomes part of
it. It also keeps TOML escape sequences literally, so a healthcheck needs
`curl --oauth2-bearer $VAR` rather than an escaped `-H` header.

### Per provider — `[providers.<name>]`

{table(rows, ("Key", "Type", "Required", "What it does"))}

### Top level

{table(top, ("Key", "Type", "Required", "What it does"))}
""")


def analytics_section(repo: Path) -> str:
    defaults = load_json(repo / "scripts/session_analytics/config_data/defaults.json")
    config_py = (repo / "scripts/session_analytics/config.py")
    constants_py = (repo / "scripts/session_analytics/constants.py")
    for p in (config_py, constants_py):
        if not p.is_file():
            die(f"source not found: {p}")
    config_src = config_py.read_text(encoding="utf-8")
    constants_src = constants_py.read_text(encoding="utf-8")

    env_names = dict(re.findall(r'^(ENV_[A-Z0-9_]+)\s*=\s*"([^"]+)"', config_src, re.M))
    cfg_names = dict(re.findall(r'^(CFG_[A-Z0-9_]+)\s*=\s*"([^"]+)"', constants_src, re.M))
    if not env_names or not cfg_names:
        die("could not read the ENV_/CFG_ constants — the reference would be empty")

    # `env(ENV_X) or block.get(C.CFG_Y)` and `helper(C.CFG_Y, ENV_X)` are the
    # two shapes config.py uses to pair a variable with a key.
    pairs: dict[str, str] = {}
    for env_c, cfg_c in re.findall(r"env\((ENV_[A-Z0-9_]+)\)[^\n]*?C\.(CFG_[A-Z0-9_]+)", config_src):
        if env_c in env_names and cfg_c in cfg_names:
            pairs.setdefault(cfg_names[cfg_c], env_names[env_c])
    for cfg_c, env_c in re.findall(r"C\.(CFG_[A-Z0-9_]+),\s*(ENV_[A-Z0-9_]+)", config_src):
        if env_c in env_names and cfg_c in cfg_names:
            pairs.setdefault(cfg_names[cfg_c], env_names[env_c])

    def flat(node, prefix=""):
        for k, v in node.items():
            if k.startswith("_"):
                continue
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                yield from flat(v, key)
            else:
                yield key, v

    # Pairing rule. An exact path wins. Otherwise a variable may claim a key
    # only when its NAME carries both halves of that key: it ends in the
    # leaf, and it mentions the block the leaf sits in (CCT_SA_JUDGE_BASE_URL
    # for judge.base_url; CCT_SA_EMBED_BACKEND for embedding.backend, whose
    # block is abbreviated). Matching on the leaf alone paired
    # judge.by_copilot.<tool>.backend with CCT_SA_EMBED_BACKEND — a variable
    # that does not control that key — so a leaf with no block evidence, or
    # with more than one candidate, stays unpaired.
    all_vars = sorted(set(env_names.values()))

    def claim(key: str) -> str:
        if key in pairs:
            return pairs[key]
        segments = key.split(".")
        if len(segments) < 2:
            return ""
        leaf, parent = segments[-1].upper(), segments[-2].upper()[:4]
        # The IMMEDIATE parent, not any ancestor: judge.by_copilot.<tool>.backend
        # would otherwise claim CCT_SA_JUDGE_BACKEND, which sets the default
        # judge rather than that copilot's override.
        found = [v for v in all_vars if v.endswith("_" + leaf) and parent and parent in v]
        return found[0] if len(found) == 1 else ""

    rows = []
    for key, value in flat(defaults):
        env = claim(key)
        shown = "*(empty)*" if value in ("", None) else f"`{json.dumps(value)}`"
        rows.append((f"`{key}`", shown, f"`{env}`" if env else ""))
    if not rows:
        die("defaults.json produced no rows")

    claimed = {claim(k) for k, _ in flat(defaults)} | {pairs[k] for k in pairs}
    unpaired = sorted(set(env_names.values()) - claimed - {""})
    # A constant whose value ends in "_" is a prefix the code completes per
    # key (CCT_SA_CALIBRATION_<KEY>), not a variable anyone sets by that name.
    prefixes = [v for v in unpaired if v.endswith("_")]
    plain = [v for v in unpaired if not v.endswith("_")]
    extra = ""
    if plain:
        extra += ("\n### Environment variables with no defaults entry\n\n"
                  "Read directly by the code that needs them (paths, ids, and the\n"
                  "runtime toggles that have no stored default):\n\n"
                  + "\n".join(f"- `{v}`" for v in plain) + "\n")
    if prefixes:
        extra += ("\n### Environment prefixes\n\n"
                  "Completed per key by the code that reads them:\n\n"
                  + "\n".join(f"- `{v}<KEY>`" for v in prefixes) + "\n")

    note = ("\nA key with no variable is set in the config file or the Studio's\n"
            "Settings page only. A variable that selects for a whole block — the\n"
            "default judge, for instance — is listed under the tables rather than\n"
            "guessed onto one row.\n")
    return (f"""## Session analytics — `~/.cct/session-analytics.json` and the environment

Layered: `config_data/defaults.json`, then `~/.cct/session-analytics.json`,
then the repo-root `.env`, then real environment variables, then CLI
arguments. The Studio's Settings page writes the same keys. An API key is
stored by name in the environment, never in the config file.

{table(rows, ("Key", "Default", "Environment variable"))}
{note}{extra}""")


def main() -> None:
    repo = Path(sys.argv[1] if len(sys.argv) > 1 else ".").resolve()
    parts = [HEADER, automation_section(repo), providers_section(repo), analytics_section(repo),
             """## Where the rest lives

- **Claude Code session settings** (`~/.claude/settings.json`, hooks wiring,
  permissions) — [Setup Cookbook](../adapters/claude-code/docs/claude-code-setup-cookbook.md)
  and [Permissions Guide](../adapters/claude-code/docs/permissions-guide.md).
- **Pi's TOML config** — [Pi Configuration Reference](../adapters/pi/docs/configuration-reference.md).
- **Review and auto-build runtime switches** (`CCT_REVIEW_DIFF_MAX_LINES`,
  `CCT_PEER_REVIEW_ENABLED`, and the rest of the `CCT_*` namespace) — named
  where they are used, in [Auto code review setup](auto-code-review-setup.md)
  and the [auto-build skill](../shared/skills/auto-build-loop/SKILL.md).
"""]
    print("\n".join(p.rstrip() + "\n" for p in parts).rstrip() + "\n", end="")


if __name__ == "__main__":
    main()
