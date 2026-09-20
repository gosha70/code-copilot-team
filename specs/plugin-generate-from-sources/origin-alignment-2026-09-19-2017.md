# Origin alignment check — plugin-generate-from-sources

Checked 2026-09-19 20:17, after the build (tasks 1–6) and before review. Supersedes the 13:42 record, which went stale when plan.md gained the owner's decisions, the corrected budget wording and the runtime results. This check compares the origin with what was built, not only with what was planned.

Origin: specs/plugin-generate-from-sources/origin/2026-09-19-owner-direction-step-2.md
(owner messages in the #363 session) and issue #363.

Origin claim:
> Package the existing skills, agents and commands from their
> authoritative sources: generate the plugin, do not maintain another
> authored copy. Keep setup.sh supported. Address duplicate hooks and
> plugin-namespaced commands when both installation paths coexist. No
> broad redesign. Eval comes afterwards and is separately authorized.

Working claim (as built):
> One new section in scripts/generate.sh writes skills, agents,
> commands, the seven hook scripts, templates/sdd and review-decide.sh
> into the plugin, with a single path rewrite in agents and commands and
> a clean scoped to the five generated subdirectories. The output is
> committed-form and covered by CI's existing drift check. setup.sh is
> untouched apart from an inert guard in five shared hook scripts.
> Same-named components under both installs are verified and documented,
> with no code. Plugin 1.1.0. No eval.

Each clause of the origin against the build:

1. "Generate, never a second authored copy." Only plugin.json and
   hooks/hooks.json are authored. tests/test-generate.sh asserts the
   forward and reverse source-to-copy match, byte identity for skills,
   hooks, helper and templates, and that a file with no source is
   removed by the next run. The previously hand-copied, drifted
   verify-after-edit.sh is now generated.
2. "Keep setup.sh supported." A fresh setup.sh install from the branch
   into a throwaway HOME passes tests/test-shared-structure.sh 826/826,
   and the installed hook still runs with no plugin root set.
3. "Address duplicate hooks." The five non-safety hooks step aside only
   as the plugin copy with setup.sh's copy installed; the two protect
   hooks carry no guard and still block (exit 2) under both installs.
   tests/test-hooks.sh covers each case.
4. "Address plugin-namespaced commands." Probe 4 showed no
   de-duplication and no collision; docs/install.md says so. The owner
   confirmed on 2026-09-19 that verify-and-document is what was meant.
5. "No broad redesign." One generator section and one sed expression.
   Neither build-time verification that could have grown the design
   (bare agent names, substitution in command bodies) needed a change,
   so the stop rule did not trigger.
6. "Eval is separate." Not run. The four authorized probes were plain
   `claude -p` runs, $0.2973 in total, nothing installed.

Differences from the origin, all now ruled on by the owner:

1. More than "skills, agents and commands" is generated (hook scripts,
   templates/sdd, review-decide.sh). Approved as D3.
2. The six always-on skills ship as ordinary skills, because a plugin
   cannot ship always-loaded rules. Approved as D1; stated in
   docs/install.md.
3. Namespaced commands are met by verification and documentation.
   Confirmed by the owner.
4. The duplicate-hook guard excludes the two safety hooks. Approved as
   D2.

Verdict: aligned
Confidence: high

High, where 13:42 was medium: the three scope judgements that held it at
medium were each put to the owner and decided, and the build was checked
against every clause of the origin rather than against the plan alone.

Known limits, none of them a departure from the origin: probe 2 proved
the path resolution but its Read was denied by the headless permission
check, so the file read itself is unproven; the plugin copy of
review-decide.md still carries the source's "installed by setup.sh"
comment, because FR-2 changes paths only.
