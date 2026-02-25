Run the document ingestion pipeline:
1. Check for new documents in the configured source directory
2. Run chunking with the current strategy settings
3. Generate embeddings and upsert to vector store
4. Extract entities/relations and update knowledge graph
5. Report: documents processed, chunks created, entities extracted
