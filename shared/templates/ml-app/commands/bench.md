Run the benchmark/evaluation pipeline:
1. Load benchmark datasets from the configured directory
2. Run each strategy (direct, RAG, etc.) against the test cases
3. Collect metrics: accuracy, token usage, cost, latency
4. Print summary table with per-strategy results
5. Flag any strategy that regresses below baseline thresholds
