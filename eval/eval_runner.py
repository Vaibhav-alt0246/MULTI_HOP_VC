"""Small evaluation runner for retrieval Recall@K and question audit coverage."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
sys.path.insert(0, str(PROJECT_ROOT))

from eval.metrics import audit_trail_coverage, recall_at_ks


def evaluate_retrieval(
    eval_queries_path: Path,
    data_dir: Path,
    ks: tuple[int, ...] = (1, 3, 5),
) -> dict:
    """Evaluate Retriever results against query/source ground truth."""
    from resolvers.retriever import Retriever

    eval_queries = json.loads(eval_queries_path.read_text(encoding="utf-8"))
    retriever = Retriever(
        index_path=data_dir / "vector.index",
        metadata_path=data_dir / "vector_metadata.json",
    )
    ranked_results = [
        retriever.retrieve(item["query"], top_k=max(ks))
        for item in eval_queries
    ]
    expected_sources = [item["expected_source"] for item in eval_queries]
    return recall_at_ks(ranked_results, expected_sources, ks=ks)


def evaluate_questions(questions_path: Path) -> dict:
    """Evaluate generated question artifacts for minimal audit coverage."""
    data = json.loads(questions_path.read_text(encoding="utf-8"))
    questions = data.get("questions", [])
    return {
        "total_questions": len(questions),
        "audit_trail_coverage": audit_trail_coverage(questions),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run VC due-diligence evaluation checks")
    parser.add_argument("--data-dir", default="data/processed")
    parser.add_argument("--eval-queries", default=None)
    parser.add_argument("--questions", default=None)
    parser.add_argument("--output", default="data/processed/eval_results.json")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    results: dict = {}

    if args.eval_queries:
        results["retrieval"] = evaluate_retrieval(Path(args.eval_queries), data_dir)
    if args.questions:
        results["questions"] = evaluate_questions(Path(args.questions))

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
