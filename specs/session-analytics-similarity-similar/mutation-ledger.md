# Mutation ledger — #287 T1–T3, re-run whole at T4

- **Date:** 2026-09-02
- **Environment:** the review's own verification mode — kuzu 0.11.3 +
  mcp<2 installed, so `test_similarity` runs with ZERO skips (75
  tests), live graph and registered-MCP-tool classes included.
- **Method:** one scripted pass at the final T3 HEAD. Each mutation:
  apply → clear every `__pycache__` → run → collect FAIL **and** ERROR
  names → restore all files → verify green. Baseline green before the
  first mutation and after the last restore. **24 mutations, 24
  caught, 0 escaped.**
- Consolidates the mutations exercised during each task's build AND
  each review round's reproduced attacks (the escaped
  provider-dropping grouping mutation, the TOCTOU connect, the
  commit-outside-the-phase defect) so closure evidence is one pass at
  one commit.

| Mutation | Caught by (tests) | First discriminators |
|---|---|---|
| T1-M1 space key drops the provider | 5 | test_dim_conflict_reported_and_nobody_disqualified; test_each_component_alone_separates; test_grouping_separates_by_provider … |
| T1-M2 grouping keys unvalidated envelopes | 5 | test_deterministic_partition; test_dim_conflict_reported_and_nobody_disqualified; test_grouping_separates_by_provider … |
| T1-M3 dim_conflict disqualifies both groups | 2 | test_dim_conflict_reported_and_nobody_disqualified; test_grouping_separates_by_dim |
| T1-M4 naive sum-of-squares cosine | 3 | test_huge_components_do_not_overflow_to_nan; test_mixed_magnitudes_stay_finite; test_tiny_components_do_not_underflow_to_false_zero_norm |
| T1-M5 cosine returns 0.0 on zero norm | 1 | test_zero_norm_is_a_caller_bug_not_a_score |
| T1-M6 descending-id tie-break | 1 | test_deterministic_tie_break_by_ascending_id |
| T1-M7 threshold ignored | 5 | test_below_threshold_yields_empty_healthy; test_healthy_empty_for_a_below_threshold_session; test_neighbors_carry_score_basis_and_snapshot_note … |
| T1-M8 similarity knobs coerced without validation | 8 | test_boolean_threshold_refused; test_boolean_top_k_refused; test_fractional_top_k_refused_not_truncated … |
| T2-M1 eligible-sources-only replacement | 2 | test_all_ineligible_retires_everything_and_says_so; test_removed_source_edges_are_retired |
| T2-M2 cross-group pair formation | 1 | test_cross_space_edges_are_impossible |
| T2-M3 no transaction at all | 3 | test_commit_failure_triggers_rollback_and_preserves_edges; test_injected_write_failure_preserves_previous_edge_set; test_live_pass_writes_and_survives_injected_failure |
| T2-M4 commit outside the protected phase | 2 | test_commit_failure_triggers_rollback_and_preserves_edges; test_live_pass_writes_and_survives_injected_failure |
| T2-M5 unconditional rollback masks the original error | 2 | test_cleanup_never_replaces_the_original_error; test_live_pass_writes_and_survives_injected_failure |
| T2-M6 nothing-eligible early return despite existing edges | 1 | test_all_ineligible_retires_everything_and_says_so |
| T2-M7 readiness gate dropped | 2 | test_live_cli_unready_graph_and_happy_path; test_unready_graph_is_a_prerequisite_error_before_any_read |
| T2-M8 create missing graph nodes instead of counting | 1 | test_missing_graph_node_counted_never_created |
| T2-M9 CLI absent-path pre-check dropped | 1 | test_absent_graph_path_is_usage_error_with_zero_creation |
| T3-M1 server drops the kuzu_path plumbing | 1 | test_registered_tool_reads_the_configured_graph |
| T3-M2 create-capable connect in the MCP read | 1 | test_disappearing_path_is_refused_not_recreated |
| T3-M3 healthy empty misdiagnosed as missing work | 1 | test_healthy_empty_for_a_below_threshold_session |
| T3-M4 basis dropped from neighbor rows | 1 | test_neighbors_carry_score_basis_and_snapshot_note |
| T3-M5 stored envelope accepted without validation | 1 | test_invalid_envelope_gets_targeted_overwrite_guidance |
| T3-M6 invalid-envelope guidance collapsed to plain embed | 1 | test_invalid_envelope_gets_targeted_overwrite_guidance |
| T3-M7 KPIs dropped from the payload | 1 | test_neighbor_kpis_included_with_rubric_and_honest_absence |

## Reading notes

- **T1-M8 (8)** — coercion-without-validation breaks every knob test
  at once: the validators are load-bearing for T2's edge semantics,
  which is why the review demanded them before T2 existed.
- **T1-M1/M2 (5 each)** — the space key and the grouping boundary are
  now protected at BOTH levels; the review's escaped mutation
  (constant provider inside grouping) is T1-M2's family and now fails
  the grouping-level discriminators.
- **T2-M3/M4/M5** — the transaction contract is three separately
  discriminated lies: no transaction, commit outside it, and cleanup
  masking the original error.
- Single-test catches are deliberate: each such test exists precisely
  to discriminate that one weakening (e.g. T3-M1's registered-tool
  test is the only thing that can see the server-side plumbing).
