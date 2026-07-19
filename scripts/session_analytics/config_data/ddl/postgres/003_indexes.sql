-- session_analytics indexes. Additive; safe to re-run.

CREATE INDEX IF NOT EXISTS idx_session_copilot ON copilot_session(copilot);
CREATE INDEX IF NOT EXISTS idx_session_developer ON copilot_session(developer_id);
CREATE INDEX IF NOT EXISTS idx_session_started ON copilot_session(started_at);
CREATE INDEX IF NOT EXISTS idx_turn_session ON copilot_turn(session_id);
CREATE INDEX IF NOT EXISTS idx_toolcall_turn ON copilot_tool_call(turn_id);
CREATE INDEX IF NOT EXISTS idx_toolcall_name ON copilot_tool_call(tool_name);
CREATE INDEX IF NOT EXISTS idx_toolresult_call ON copilot_tool_result(tool_call_id);
CREATE INDEX IF NOT EXISTS idx_fileaccess_session ON copilot_file_access(session_id);
CREATE INDEX IF NOT EXISTS idx_fileaccess_path ON copilot_file_access(file_path);
CREATE INDEX IF NOT EXISTS idx_error_session ON copilot_error(session_id);
CREATE INDEX IF NOT EXISTS idx_label_turn ON heuristic_label(turn_id);
CREATE INDEX IF NOT EXISTS idx_kpi_session ON session_kpi(session_id);
CREATE INDEX IF NOT EXISTS idx_benchres_session ON benchmark_result(session_ref);
CREATE INDEX IF NOT EXISTS idx_benchres_result ON benchmark_result(result);
CREATE INDEX IF NOT EXISTS idx_trace_session ON trace_document(session_ref);
