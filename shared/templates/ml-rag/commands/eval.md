Run the RAG evaluation pipeline:
1. Load evaluation dataset from eval/datasets/
2. Run retrieval evaluation (recall@k, precision@k)
3. Run answer quality evaluation (LLM-as-judge)
4. Print summary table with pass/fail thresholds
5. If any metric is below threshold, flag it clearly
