# Origin: the first real unattended run (owner, 2026-09-08)

Owner, on #190 after increments A–C merged:

> not D. Take option 3, and before building it, run the unattended
> profile for real at least once. … The cheapest and most informative
> next step is one real unattended run on a small feature, which costs
> a few dollars and either lands, terminates on policy, or fails.
> Whatever it does is the first data point, and it will probably
> surface defects in A through C that no test caught.

The small feature chosen for that run: developer aliases for the team
store. The owner's own store (2026-09-08, seen on the Team tab built in
PR #324) attributes one person's sessions to three developer ids —
`i-am-goga`, `i-am-goga-gmail-com`, `local` — because identity
derivation changed over time. The Team tab and `session-analytics team
status` should be able to fold them into one row under one name,
without rewriting history in the store.
