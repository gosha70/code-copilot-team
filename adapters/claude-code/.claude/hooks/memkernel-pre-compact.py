#!/usr/bin/env python3
"""memkernel-pre-compact.py — store a checkpoint before compaction."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime

import chromadb
from chromadb.api import ClientAPI as ChromaClientAPI

from memkernel.config import MemKernelSettings
from memkernel.core.models import MemoryType
from memkernel.core.services import MemoryService
from memkernel.retrieval.chunking import ASTChunker
from memkernel.retrieval.embeddings import SentenceTransformerEmbedding
from memkernel.retrieval.search import HybridSearchService
from memkernel.retrieval.sparse import BM25Index
from memkernel.storage.chroma import ChromaVectorStore

logging.basicConfig(stream=sys.stderr, level=logging.WARNING)


def build_service() -> MemoryService:
    settings = MemKernelSettings()
    persist = settings.chroma_persist_path
    client: ChromaClientAPI = chromadb.EphemeralClient() if not persist else chromadb.PersistentClient(path=persist)
    store = ChromaVectorStore(settings, client=client)
    embedding = SentenceTransformerEmbedding(settings)
    sparse = BM25Index()
    search_svc = HybridSearchService(store, embedding, sparse, settings)
    svc = MemoryService(store, embedding, sparse, search_svc, settings, chunker=ASTChunker(settings))
    svc.rebuild_sparse_index()
    return svc


def main() -> None:
    raw = sys.stdin.read().strip()
    event = json.loads(raw) if raw else {}
    summary = str(event.get("summary", "Compaction triggered — no summary provided."))

    now = datetime.now(UTC)
    session_id = now.strftime("checkpoint-%Y%m%d-%H%M%S")
    content = f"SESSION CHECKPOINT — {now.isoformat()}\n\n{summary}"

    svc = build_service()
    ref_id = svc.retain(
        content=content,
        type=MemoryType.EPISODE,
        checkpoint=True,
        session_id=session_id,
    )
    print(f"MemKernel: checkpoint retained — ref_id={ref_id}", file=sys.stderr)


if __name__ == "__main__":
    main()
