Run the retrieval evaluation pipeline:
1. Load evaluation dataset from eval/datasets/
2. Run retrieval evaluation (recall@k, precision@k, MRR)
3. Run hybrid search ablations (dense-only vs sparse-only vs hybrid)
4. Print summary table with pass/fail thresholds
5. If any metric is below threshold, flag it clearly
