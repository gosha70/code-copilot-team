# Mutation ledger — #289 T1–T3, re-run whole at T4

- **Date:** 2026-09-03
- **Environment:** the arc's verification mode — kuzu 0.11.3, mcp
  1.29.1 and pytest in an isolated venv, so the three cluster modules
  run with **ZERO skips** (80 passed, 11 subtests passed). Live-Kùzu
  and registered-MCP-tool classes are included, not skipped.
- **Method:** one scripted pass at the final HEAD. Each mutation:
  apply → clear every `__pycache__` → run → collect FAIL, ERROR **and**
  SUBFAILED names → restore → continue. Baseline green before the first
  mutation, and re-verified green after the last restore
  (80 passed, 11 subtests passed in 4.73s).
- **34 mutations, 34 caught, 0 escaped.**
- Consolidates every mutation exercised during T1–T3 AND each review
  round's reproduced attacks, so closure evidence is one pass at one
  commit.

## Corrections made while consolidating

Two defects in the LEDGER itself surfaced on the first whole-run and
are recorded rather than quietly fixed:

- **T2-M12 escaped at first.** Deleting the CLI's absent-path precheck
  changed nothing observable, because with kuzu installed
  `connect_read_only` refuses an absent database too — and the test
  asserted only the shared prefix `"graph database absent"`, which is
  also a prefix of the open's own `"absent or unopenable"` message. The
  precheck is the guarantee this slice owns; the driver's behaviour is
  not. `test_absent_path_is_usage_error_with_zero_creation` now asserts
  the message does NOT say "unopenable", pinning which layer refused,
  and the mutation dies.
- **Two mutations were miscounted as catching 0 tests.** The driver's
  regex matched `FAILED`/`ERROR` but not pytest's `SUBFAILED(...)`
  lines, so the subtest-driven `limit` discriminators looked empty. The
  parser now counts subtest failures; T3-M11 and T3-M12 are caught by
  `test_non_integer_limits_are_refused_never_coerced`.

Three earlier mutations were found to be no-ops rather than escapes
during the task rounds, and were re-anchored before this pass: an
empty-dict `or` expression that returns its second operand, and two
anchors that matched `similar_sessions` as well as `session_clusters`.

## Equivalent mutants, recorded not gamed

`identity=root` in `clusters.py` is EQUIVALENT under the smallest-root
union rule — root and `members[0]` compute the same value — so it
cannot be killed and is not counted. It is replaced by T1-M2a
(`identity = members[-1]`). The complementary experiment — reversing
the union rule while keeping `identity=members[0]` — correctly
SURVIVES, which is the positive evidence that identity does not depend
on union-find internals.

| Mutation | Caught by (tests) | First discriminators |
|---|---|---|
| T1-M1 count adjacencies, not directed records | 6 | test_as_dict_carries_the_directed_count_by_name; test_count_covers_every_record_inside_the_component; test_populated_graph_exits_zero_and_prints_the_report … |
| T1-M2a identity = largest member | 3 | test_as_dict_carries_the_directed_count_by_name; test_clusters_order_by_descending_size_then_identity; test_identity_is_the_lexicographically_smallest_member |
| T1-M3 singleton clusters allowed | 5 | test_membership_shortcut_would_have_said_two; test_min_cluster_size_is_two; test_self_loop_alone_is_not_a_cluster_of_one … |
| T1-M4 unsorted key iteration | 13 | test_as_dict_carries_the_directed_count_by_name; test_chain_groups_a_and_c_though_they_share_no_edge; test_clustered_session_returns_its_unnamed_cluster … |
| T1-M5 ascending size order | 2 | test_clusters_order_by_descending_size_then_identity; test_list_mode_is_largest_first |
| T1-M6 directed-only grouping (no undirected union) | 2 | test_identity_is_the_lexicographically_smallest_member; test_member_order_does_not_follow_insertion |
| T1-M7 members not sorted | 11 | test_as_dict_carries_the_directed_count_by_name; test_chain_groups_a_and_c_though_they_share_no_edge; test_clustered_session_returns_its_unnamed_cluster … |
| T2-M1 unclustered ignores incidence (whole inventory) | 11 | test_cli_end_to_end_exit_zero_on_ready_graph; test_counts_partition_the_inventory_for_producible_edges; test_destination_only_node_is_not_unclustered … |
| T2-M2 unclustered from cluster MEMBERSHIP (rejected shortcut) | 3 | test_membership_shortcut_would_have_said_two; test_self_loop_member_is_not_reported_unclustered; test_self_loop_node_is_neither_clustered_nor_unclustered |
| T2-M3 incidence from sources only (drops destinations) | 2 | test_destination_only_node_is_not_unclustered; test_one_way_chain_leaves_only_the_isolated_session |
| T2-M4 edges re-read instead of the single capture | 1 | test_edges_are_read_once_per_run |
| T2-M5 provenance labels blurred into one | 1 | test_report_labels_the_two_bases_distinctly |
| T2-M6 limitations block dropped | 2 | test_no_claim_that_members_currently_share_an_envelope; test_transitive_limitation_is_stated_not_implied |
| T2-M7 unbuilt graph treated as healthy empty | 5 | test_unbuilt_graph_is_a_cli_usage_error; test_unbuilt_graph_is_a_graph_prerequisite; test_unbuilt_graph_is_a_usage_error … |
| T2-M8 score leaked into the pure layer | 1 | test_scores_do_not_change_grouping_or_counting |
| T2-M9 internal state leaked into the report bytes | 1 | test_report_key_set_is_a_fixed_contract |
| T2-M10 is_unclustered drops the membership half | 1 | test_is_unclustered_requires_graph_membership |
| T2-M11 inventory not retained on the report | 7 | test_clustered_session_returns_its_unnamed_cluster; test_clustered_unclustered_and_missing_node_on_a_real_store; test_edgeless_member_is_still_plainly_unclustered … |
| T2-M12 CLI creates the store instead of refusing | 1 | test_absent_path_is_usage_error_with_zero_creation |
| T2-M13 CLI repairs the race with a create-capable open | 1 | test_disappearing_path_is_refused_not_repaired |
| T2-M14 zero clusters reported as a failure exit | 1 | test_ready_graph_with_zero_edges_exits_zero |
| T2-M15 refused config escapes as a traceback | 1 | test_refused_config_is_a_usage_error_before_any_graph_open |
| T3-M1 missing graph node answered as 'unclustered' | 2 | test_clustered_unclustered_and_missing_node_on_a_real_store; test_relational_session_absent_from_graph_gets_graph_guidance |
| T3-M2 new prerequisite literal for a missing graph node | 2 | test_clustered_unclustered_and_missing_node_on_a_real_store; test_relational_session_absent_from_graph_gets_graph_guidance |
| T3-M3 list mode ordered smallest-first | 1 | test_list_mode_is_largest_first |
| T3-M4 limit ignored | 3 | test_limit_bounds_the_list_but_not_the_count; test_valid_integer_limits_are_still_accepted; test_zero_limit_returns_no_rows_without_error |
| T3-M5 cluster_count reports the truncated page | 2 | test_limit_bounds_the_list_but_not_the_count; test_zero_limit_returns_no_rows_without_error |
| T3-M6 provenance/limitations notes dropped | 2 | test_results_are_basis_honest_and_carry_provenance; test_surfaces_share_one_provenance_source |
| T3-M7 absent graph opened anyway | 1 | test_unset_path_is_a_graph_prerequisite |
| T3-M8 race repaired instead of refused | 1 | test_disappearing_path_is_refused_not_repaired |
| T3-M9 unbuilt graph swallowed as healthy empty | 1 | test_unbuilt_graph_is_a_graph_prerequisite |
| T3-M10 tool re-reads the inventory instead of the report | 2 | test_clustered_unclustered_and_missing_node_on_a_real_store; test_tool_reads_the_inventory_once |
| T3-M11 limit coerced with int() instead of validated | 1 | test_non_integer_limits_are_refused_never_coerced |
| T3-M12 bool accepted as an int limit | 1 | test_non_integer_limits_are_refused_never_coerced |

## Notes on the load-bearing catches

- **T1-M1 (6)** — the directed-vs-adjacency count. Collapsing
  reciprocal pairs breaks the T1 fixture, the reader, the CLI report
  and the MCP payload at once: the choice is pinned in one place and
  consumed everywhere.
- **T1-M4 (13)** and **T1-M7 (11)** — determinism is structural. Losing
  sorted iteration or sorted members falls over most of the suite,
  which is the point: FR-C is by construction, not by one assertion.
- **T2-M1/M2/M3 (11/3/2)** — the three ways to get `unclustered` wrong:
  ignore incidence, derive it from cluster membership (the shortcut the
  review rejected), or count only edge sources. The last matters most
  in practice — #287's top-K is asymmetric, so a session appearing only
  as a destination is routine, and it survived until a destination-only
  discriminator was added.
- **T2-M10 / T3-M10 (1/2)** — one snapshot decides everything. Dropping
  the membership half of `is_unclustered`, or re-reading the inventory
  in the tool, both let two reads disagree.
- **T2-M9 (1)** — the report's key set is a published contract; internal
  state carried for callers must not leak into the bytes.
- **T3-M2 (2)** — the missing-graph-node answer must reuse
  `similar_sessions`' existing `prerequisite: "graph"` shape. That is
  the precise rule; `clustered`/`unclustered` are this slice's own
  result states and are not affected by it.
- Single-test catches are deliberate: each such test exists to
  discriminate exactly one weakening (T2-M15's refused-config test is
  the only thing that can see configuration validated before the graph
  is opened).
