#!/usr/bin/env python3
"""memkernel-post-compact.py — recover MemKernel context after compaction."""

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
        "session checkpoint decisions conventions next steps",
        checkpoint_only=True,
        top_k=200,
    )
    checkpoint_refs_sorted = sorted(checkpoint_refs, key=lambda ref: ref.timestamp, reverse=True)

    latest_checkpoint = ""
    if checkpoint_refs_sorted:
        memory = svc.get(checkpoint_refs_sorted[0].ref_id)
        if memory is not None:
            latest_checkpoint = memory.content

    context_refs = svc.recall(
        "decisions conventions architecture active work",
        top_k=5,
    )
    context_previews = "\n".join(f"- {ref.preview}" for ref in context_refs) if context_refs else ""

    print("## Recovered from MemKernel (post-compaction)\n")

    print("### Latest checkpoint")
    if latest_checkpoint:
        print(latest_checkpoint)
    else:
        print("No checkpoint found. Use retain(checkpoint=true) before the next compaction.")

    print("\n### Long-term context")
    if context_previews:
        print(context_previews)
    else:
        print("No prior memories found.")

    print("\n---")
    print("Use recall() or get(ref_id) for the full memory content.")


if __name__ == "__main__":
    main()
