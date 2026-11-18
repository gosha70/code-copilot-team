# Origin alignment check — llm-catalog (spec follows #411, revision 7)

Date: 2026-11-14 22:55 EST

Supersedes the 2026-11-11 00:10 record. One amendment, foreseen by the
spec itself and by the owner's #411 ruling that `llms.toml` follows
whichever lands first: #411 landed before slice A started, so FR-1 and
D2 now place the catalog, the compatibility records and the stamps in
the CCT home `${CCT_HOME:-~/.cct}` through #411's resolver, with
`CCT_HOME` as the one override (no `CCT_LLM_HOME`). The scenario text
in § User Scenarios says `~/.cct/llms.toml` accordingly. Nothing else
in the bundle changed; the mapping table of the 00:10 record stands.

Origin sources: issue #400 as amended by the owner on 2026-11-10, the
four external references it cites, and the repository at `42f5883`;
the home location is now also governed by issue #411 as ruled on
2026-11-15.

## Mismatches

None. The issue names the user home only as "the user's CCT
directory"; which directory that is was always #411's to decide.

Verdict: aligned
Confidence: high
