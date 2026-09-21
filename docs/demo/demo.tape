# demo.tape — the 35-second README demo (#214 Phase 6.3).
#
# Render with docs/demo/render.sh, never with a local vhs: the script runs this
# tape in the container docs/demo/Dockerfile defines, on a copy of the
# repository, and writes only the GIF out.
#
# VHS only types keys; it would record a broken command as calmly as a working
# one. So before rendering, docs/demo/check-tape.py runs every command typed
# below, in order, in one shell, and fails if one exits non-zero or if an
# "# expect:" string is missing from the output. CI runs the same script, so a
# command that stops working fails the build instead of leaving a demo that lies.
#
# Everything shown is real: the installer, the cct CLI on master, and two
# hooks answering a tool call. No model call and no credentials. The installer
# fetches the session-analytics Python packages, the only network use; that
# wait is hidden rather than recorded.
#
# expect: hooks
# expect: Spec-driven development
# expect: Blocked: .env is a protected file
# expect: Blocked: git push requires explicit user approval
# expect: exit 2

Output "/out/demo.gif"

Require bash
Require jq

Set Shell "bash"
Set FontSize 15
Set Width 1100
Set Height 420
Set Padding 18
Set TypingSpeed 35ms
Set WaitTimeout 180s

# A throwaway home and a quiet prompt, off camera. VHS trims the line it
# matches, so an idle prompt is exactly "$".
Hide
Type "export HOME=/tmp/demo-home PS1='$ ' && mkdir -p $HOME && cd /work/code-copilot-team && clear" Enter
Wait /^\$$/
Show

Type "# Install the harness (master), answering no questions. About ten seconds." Enter
Type "bash adapters/claude-code/setup.sh < /dev/null > /tmp/setup.log && ls ~/.claude" Enter
Hide
Wait /^\$$/
Show
Sleep 3s

Type "clear" Enter
Type "# What does it offer? Maturity, release, and which adapters enforce it." Enter
Type "./scripts/cct features | head -n 9" Enter
Wait /^\$$/
Sleep 4s

Type "clear" Enter
Type "# A rail, held: the hook Claude Code runs before every edit." Enter
Type `echo '{"tool_input":{"file_path":".env"}}' | bash ~/.claude/hooks/protect-files.sh; echo "exit $?"` Enter
Wait /^\$$/
Sleep 4s

Type "clear" Enter
Type "# And before every shell command." Enter
Type `echo '{"tool_input":{"command":"git push"}}' | bash ~/.claude/hooks/protect-git.sh; echo "exit $?"` Enter
Wait /^\$$/
Sleep 5s
