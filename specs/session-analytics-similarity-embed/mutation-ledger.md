# Mutation ledger — #285 T1–T4, re-run whole at T5

- **Date:** 2026-09-02
- **Method:** one scripted pass at the final T4 HEAD. Each mutation:
  apply → clear every `__pycache__` → run `test_embedding` → collect
  FAIL **and** ERROR test names → restore all files → verify the
  baseline is green again. The suite was green before the first
  mutation and after the last restore. A mutation "escapes" if the
  suite stays green under it; **28/28 were caught, 0 escaped.**
- These are re-runs of the mutations exercised during each task's own
  build, consolidated so the closure evidence is one pass at one
  commit rather than a trail of per-task snapshots.

| Mutation | Caught by (tests) | First discriminators |
|---|---|---|
| T1-V1 drop the zero-vector rule | 1 | test_zero_vector_refused |
| T1-V2 collapse validation to one shape check | 16 | test_bad_timestamp_refused; test_boolean_dim_refused; test_boolean_element_refused … |
| T1-V3 build_envelope stores an empty model | 20 | test_bad_timestamp_refused; test_boolean_dim_refused; test_boolean_element_refused … |
| T1-C1 restore the hardcoded default reconstruction | 4 | test_all_five_layers_cli_wins; test_cli_empty_model_is_a_value_not_an_absence; test_missing_embedding_block_is_refused_not_reconstructed … |
| T1-C2 env beats CLI | 2 | test_all_five_layers_cli_wins; test_cli_empty_model_is_a_value_not_an_absence |
| T1-C3 CLI layer read by truthiness | 1 | test_cli_empty_model_is_a_value_not_an_absence |
| T2-M1 widen the allowlist with a session JOIN | 9 | test_duplicate_sequence_num_fails_that_session_only; test_empty_and_null_previews_contribute_nothing; test_happy_path_embeds_and_writes_a_valid_envelope … |
| T2-M2 disorder the query | 1 | test_ordered_by_sequence_num |
| T2-M3 empty session embedded as empty string | 3 | test_all_blank_previews_are_unembeddable_too; test_empty_session_is_unembeddable_not_empty_string; test_unembeddable_session_counted_without_calling_embed |
| T2-M4 newest-first retention | 1 | test_truncation_keeps_the_head_and_is_reported |
| T2-M5 truncation unreported | 2 | test_truncation_is_counted_and_still_embeds; test_truncation_keeps_the_head_and_is_reported |
| T2-M6 remove the duplicate-sequence check | 3 | test_duplicate_refused_even_when_one_side_has_no_preview; test_duplicate_sequence_num_fails_that_session_only; test_duplicate_sequence_num_is_refused |
| T2-M7 duplicate check below the preview skip | 1 | test_duplicate_refused_even_when_one_side_has_no_preview |
| T3-M1 substitute the configured model on missing identity | 1 | test_legacy_shape_without_model_identity_is_refused |
| T3-M2 switch to the legacy endpoint | 3 | test_probe_is_a_real_embed_call; test_registry_backend_uses_the_configured_base_url; test_success_parses_the_captured_shape |
| T3-M3 drop the pre-wire empty-model gate | 1 | test_empty_configured_model_refuses_before_any_http |
| T3-M4 accept any embedding count | 1 | test_wrong_embedding_count_is_refused |
| T3-M5 probe becomes a no-op | 1 | test_probe_is_a_real_embed_call |
| T3-M6 restore the float() coercion | 2 | test_boolean_element_survives_to_the_validator_and_is_refused; test_string_number_survives_to_the_validator_and_is_refused |
| T3-M7 factory drops base_url | 1 | test_registry_backend_uses_the_configured_base_url |
| T3-M8 registry stops forwarding base_url | 2 | test_backend_is_constructed_with_the_resolved_config; test_registry_backend_uses_the_configured_base_url |
| T4-M1 probe unconditionally | 2 | test_existing_envelope_untouched_without_overwrite; test_no_work_second_run_contacts_backend_zero_times |
| T4-M2 overwrite pre-clears the column | 1 | test_overwrite_failed_embed_preserves_exact_prior_value |
| T4-M3 write without FR-9 validation | 1 | test_malformed_backend_result_is_refused_by_fr9_and_nothing_written |
| T4-M4 distribution from the configured model | 1 | test_skipped_distribution_reads_stored_envelopes_only |
| T4-M5 embed unembeddable sessions | 1 | test_unembeddable_session_counted_without_calling_embed |
| T4-M6 CLI drops the extra_overrides seam | 1 | test_cli_flags_reach_the_resolved_config |
| T4-M7 failed>0 exits zero | 1 | test_failed_nonzero_exit |

## Reading notes

- **T1-V2 (16) and T1-V3 (20)** are the two contract-wide mutations:
  collapsing the validator or blanking the stored model breaks
  discriminators across every layer that consumes envelopes — which is
  the point of having one normative validator.
- **T2-M1 (9)**: widening the allowlist with a session JOIN fails the
  planted-marker test AND the structural SQL pins AND downstream
  runner tests — the privacy boundary is not one assertion deep.
- Single-test catches (e.g. T2-M7, T3-M3, T4-M4) are deliberate:
  each of those tests exists precisely to discriminate that one
  weakening from its neighbours.
