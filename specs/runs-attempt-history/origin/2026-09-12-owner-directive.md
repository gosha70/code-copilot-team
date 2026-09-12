# Origin: the sixth real unattended run (2026-09-12)

Owner, 2026-09-12, after #340 (D2) merged:

> My recommendation: the real unattended run first, using the next
> feature you actually want shipped—not a feature invented to exercise
> the harness.

The feature: the Runs tab (#333) reads a run's ledger, but D1 (#339)
and D2 (#340) changed what a ledger holds. A run now records the
reviewer probe's answer (`reviewer-probe.json`), a round-time fallback
(`reviewer_fallback` event, `fallback` in the round's findings), and —
after a resume — its earlier terminations under dated names
(`termination-<epoch>.json`) with `resumed` in the journal. The reader
shows none of it: a run that terminated, was resumed and landed reads
as a plain landing; a run whose reviewer answered the probe in 8 s and
then failed the round shows neither fact. The owner's own question of
2026-09-11 ("What is about the progress on #190?") was answered from
these ledgers by hand.
