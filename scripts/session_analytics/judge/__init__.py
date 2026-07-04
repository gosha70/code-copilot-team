# session_analytics.judge — LLM-as-Judge heuristic labeling.
#
# Mirrors the benchmark_runner.judge design (Protocol + registry + additive
# output) but labels session TURNS rather than benchmark attempts. The
# claude-code judge reuses the proven headless `claude -p` subprocess pattern;
# the ollama judge is the local-only default (stdlib urllib, no extra deps).
