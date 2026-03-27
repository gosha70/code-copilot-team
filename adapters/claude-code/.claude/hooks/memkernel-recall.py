#!/usr/bin/env python3
"""memkernel-recall.py — recover MemKernel context at session start."""

from __future__ import annotations

import logging

import chromadb
from chromadb.api import ClientAPI as ChromaClientAPI

from memkernel.config import MemKernelSettings
from memkernel.core.services import MemoryService
from memkernel.retrieval.chunking import ASTChunker
from memkernel.retrieval.embeddings import SentenceTransformerEmbedding
from memkernel.retrieval.search import HybridSearchService
from memkernel.retrieval.sparse import BM25Index
from memkernel.storage.chroma import ChromaVectorStore

logging.basicConfig(level=logging.WARNING)


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
    svc = build_service()

    checkpoint_refs = svc.recall(
        "session checkpoint recent decisions next steps",
        checkpoint_only=True,
        top_k=50,
    )
    checkpoint_refs_sorted = sorted(checkpoint_refs, key=lambda ref: ref.timestamp, reverse=True)

    latest_checkpoint = ""
    if checkpoint_refs_sorted:
        memory = svc.get(checkpoint_refs_sorted[0].ref_id)
        if memory is not None:
            latest_checkpoint = memory.content

    context_refs = svc.recall(
        "recent decisions conventions active work",
        top_k=6,
    )
    context_previews = "\n".join(f"- {ref.preview}" for ref in context_refs) if context_refs else ""

    print("## Recovered from MemKernel\n")

    print("### Latest checkpoint")
    if latest_checkpoint:
        print(latest_checkpoint)
    else:
        print("No checkpoint found yet.")

    print("\n### Relevant memory")
    if context_previews:
        print(context_previews)
    else:
        print("No prior memories found.")

    print("\n---")
    print("Use recall() or get(ref_id) to retrieve full details for anything relevant.")


if __name__ == "__main__":
    main()
