#!/usr/bin/env bash
# Code-owned authority for automatic supervisor reconstruction.
#
# A run ledger records what happened, but it is not an operator-owned
# grant source. `routing tick --wake` may therefore reconstruct only
# these defaults. Runs started with non-default authority are resumed by
# an operator until a separate operator-owned wake policy exists.

CCT_SUPERVISOR_DEFAULT_MAX_ATTEMPTS=20
CCT_SUPERVISOR_DEFAULT_MAX_COOLDOWNS=12
CCT_SUPERVISOR_DEFAULT_COOLDOWN_SEC=300
CCT_SUPERVISOR_DEFAULT_MAX_WALL_SEC=86400
CCT_SUPERVISOR_DEFAULT_ON_INCOMPLETE=park
