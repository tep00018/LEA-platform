"""Check a course's vector store after onboarding.

Usage (from the repository root):

    python data_foundation/verify_rag_content.py DEMO101
    python data_foundation/verify_rag_content.py DEMO101 --query "What is machine learning?"

Reports the collection name, chunk count, source files and a sample, then runs one or
more retrieval queries through the same tool LEA uses at runtime (embedding search plus
reranking) and prints the top results. Exits with status 1 if the store is missing or
empty, so it can be used in scripts.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

from src.core.course_registry import default_registry  # noqa: E402
from src.core.validation import InvalidIdentifier, course_code  # noqa: E402


def inspect_store(code: str) -> bool:
    import chromadb

    path = default_registry().vector_store_path(code)
    if not (path / "chroma.sqlite3").exists():
        print(f"No vector store for {code} at {path}")
        return False

    client = chromadb.PersistentClient(path=str(path))
    names = [c if isinstance(c, str) else c.name for c in client.list_collections()]
    print(f"Vector store: {path}")
    print(f"Collections:  {names}")
    if code not in names:
        print(f"Expected a collection named {code}; LEA will only use it if it is the only one.")
        if len(names) != 1:
            return False
    collection = client.get_collection(code if code in names else names[0])
    count = collection.count()
    print(f"Chunks:       {count}")
    if count == 0:
        return False

    sample = collection.get(limit=min(count, 500), include=["metadatas", "documents"])
    sources = Counter((m or {}).get("source_file", "unknown") for m in sample["metadatas"])
    print(f"Source files (first {len(sample['metadatas'])} chunks):")
    for name, n in sources.most_common():
        print(f"  {n:4d}  {name}")
    first = (sample["documents"] or [""])[0] or ""
    print(f"Sample chunk: {first[:300]!r}")
    return True


def run_queries(code: str, queries: list[str]) -> None:
    from src.mcp.tools.rag_retrieval_tool import RAGRetrievalTool

    tool = RAGRetrievalTool()
    for query in queries:
        result = tool.execute({"query": query, "course": code, "max_results": 3})
        print(f"\nQuery: {query!r}  success={result.get('success')}")
        if not result.get("success"):
            print(f"  error: {result.get('error')}")
            continue
        for i, item in enumerate(result.get("results", []), 1):
            source = item.get("metadata", {}).get("source_file", "?")
            text = str(item.get("content", ""))[:200].replace("\n", " ")
            print(f"  {i}. [{source}] {text}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("course", help="Course code, e.g. DEMO101")
    parser.add_argument("--query", action="append", help="Retrieval query to try (repeatable)")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    try:
        code = course_code(args.course)
    except InvalidIdentifier as e:
        print(e)
        return 2

    if not inspect_store(code):
        return 1
    queries = args.query or [f"What is covered in week 1 of {code}?"]
    run_queries(code, queries)
    return 0


if __name__ == "__main__":
    sys.exit(main())
