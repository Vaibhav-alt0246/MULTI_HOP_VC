"""
pipeline.py — End-to-End Pipeline Orchestrator
===============================================
Multi-Hop Reasoning System for VC Technical Due Diligence

Runs the full pipeline in sequence:
    1. whitepaper_parser   → whitepaper claims JSON
    2. github_parser       → codebase knowledge JSON
    3. patent_parser       → patent triples JSON
    4. entity_resolver     → cross-domain entity matches JSON
    5. kg_builder          → typed knowledge graph JSON
    6. path_reasoner       → scored hop chains JSON
    7. generation.question_gen → due-diligence questions JSON  ← deliverable

Logs latency at every stage. This is your Phase 3 optimization map:
whichever stage is slowest is where to tune first.

Usage:
    python src/pipeline.py --whitepaper data/raw/startup.pdf
                           --repo       data/raw/startup_repo/
                           --patents    data/raw/patents/
                           --output     data/processed/

    python src/pipeline.py --whitepaper data/raw/startup.pdf --dry-run
    python src/pipeline.py --whitepaper data/raw/startup.pdf --max-questions 10
"""

import json
import time
import logging
import argparse
import sys
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# Add src/ to path so sibling modules are importable
sys.path.insert(0, str(Path(__file__).parent))


# ── Timing helper ─────────────────────────────────────────────────────────────

class StageTimer:
    """Tracks latency per pipeline stage for the optimization map."""

    def __init__(self):
        self.times: dict[str, float] = {}
        self._start: Optional[float] = None
        self._stage: Optional[str]   = None

    def start(self, stage: str):
        self._stage = stage
        self._start = time.perf_counter()
        logger.info("━━━ STAGE: %s ━━━", stage.upper())

    def stop(self):
        if self._stage and self._start:
            elapsed = time.perf_counter() - self._start
            self.times[self._stage] = round(elapsed, 2)
            logger.info("✓ %s completed in %.2fs", self._stage, elapsed)

    def report(self) -> dict:
        total = sum(self.times.values())
        report = {
            "stage_times_seconds": self.times,
            "total_seconds": round(total, 2),
            "slowest_stage": max(self.times, key=self.times.get) if self.times else None,
        }
        return report

    def print_report(self):
        print(f"\n{'═'*60}")
        print("  PIPELINE TIMING REPORT  (your Phase 3 optimization map)")
        print(f"{'═'*60}")
        total = sum(self.times.values())
        for stage, t in self.times.items():
            pct = (t / total * 100) if total > 0 else 0
            bar = "█" * int(pct / 5)
            print(f"  {stage:<25} {t:>6.2f}s  {bar} {pct:.0f}%")
        print(f"  {'─'*56}")
        print(f"  {'TOTAL':<25} {total:>6.2f}s")
        if self.times:
            slowest = max(self.times, key=self.times.get)
            print(f"\n  Bottleneck → {slowest} ({self.times[slowest]:.2f}s)")
            print(f"  Tune this first in Phase 3.")
        print(f"{'═'*60}\n")


# ── Stage runners ─────────────────────────────────────────────────────────────

def run_whitepaper_parser(
    pdf_path: Path,
    output_dir: Path,
    force_ocr: bool = False,
) -> Optional[Path]:
    from extractors.whitepaper_parser import WhitepaperParser, write_output
    try:
        parser = WhitepaperParser(pdf_path, force_ocr=force_ocr)
        result = parser.parse()
        out    = write_output(result, output_dir)
        logger.info(
            "Whitepaper: %d claims, %d assertions, %d entities",
            result.statistics["technical_claims_extracted"],
            result.statistics["feature_assertions_extracted"],
            result.statistics["unique_entities_found"],
        )
        return out
    except Exception as e:
        logger.error("whitepaper_parser failed: %s", e, exc_info=True)
        return None


def run_github_parser(
    repo_path: Path,
    output_dir: Path,
) -> Optional[Path]:
    from extractors.github_parser import build_dependency_map, build_import_graph
    from extractors.github_parser import build_codebase_knowledge, graph_to_serializable
    try:
        dep_map      = build_dependency_map(repo_path)
        import_graph, import_analysis = build_import_graph(repo_path)
        combined     = build_codebase_knowledge(dep_map, import_analysis, import_graph)

        # Remove verbose raw imports to keep file manageable
        if combined.get("import_graph_analysis"):
            combined["import_graph_analysis"] = {
                k: v for k, v in combined["import_graph_analysis"].items()
                if k != "all_imports_raw"
            }

        out = output_dir / "codebase_knowledge.json"
        out.write_text(json.dumps(combined, indent=2), encoding="utf-8")
        logger.info(
            "Codebase: %d deps, %d internal modules",
            dep_map["metadata"]["total_dependencies"],
            import_analysis["metadata"]["internal_modules"],
        )
        return out
    except Exception as e:
        logger.error("github_parser failed: %s", e, exc_info=True)
        return None


def run_patent_parser(
    patents_dir: Path,
    output_dir: Path,
) -> Optional[Path]:
    from extractors.patent_parser import process_directory
    try:
        triples = process_directory(str(patents_dir), str(output_dir))
        out     = output_dir / "knowledge_base.json"
        logger.info("Patents: %d triples extracted", len(triples))
        return out
    except Exception as e:
        logger.error("patent_parser failed: %s", e, exc_info=True)
        return None


def run_entity_resolver(
    whitepaper_json: Path,
    codebase_json:   Path,
    patent_json:     Path,
    output_dir:      Path,
    threshold:       float = 0.78,
) -> Optional[Path]:
    from resolvers.entity_resolver import resolve_entities
    out = output_dir / "entity_matches.json"
    try:
        matches = resolve_entities(
            whitepaper_path=whitepaper_json,
            codebase_path=codebase_json,
            patent_path=patent_json,
            output_path=out,
            threshold=threshold,
        )
        logger.info("Entity resolver: %d cross-domain matches", len(matches))
        return out
    except Exception as e:
        logger.error("entity_resolver failed: %s", e, exc_info=True)
        return None


def run_kg_builder(
    matches_path: Path,
    output_dir:   Path,
) -> Optional[Path]:
    from graph.kg_builder import build_knowledge_graph, graph_to_json, build_summary
    out = output_dir / "kg.json"
    try:
        G       = build_knowledge_graph(matches_path)
        summary = build_summary(G)
        out.write_text(
            json.dumps(graph_to_json(G), indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        (output_dir / "kg_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8"
        )
        logger.info(
            "KG: %d nodes, %d edges, %d high-risk libs",
            summary["total_nodes"],
            summary["total_edges"],
            len(summary["high_risk_libraries"]),
        )
        return out
    except Exception as e:
        logger.error("kg_builder failed: %s", e, exc_info=True)
        return None


def run_path_reasoner(
    kg_path:    Path,
    output_dir: Path,
    max_hops:   int   = 3,
    threshold:  float = 0.50,
) -> Optional[Path]:
    from reasoning.path_reasoner import load_graph, reason, save_chains
    out = output_dir / "hop_chains.json"
    try:
        G      = load_graph(kg_path)
        chains = reason(G, max_hops=max_hops, chain_threshold=threshold)
        save_chains(chains, out)
        logger.info(
            "Hop reasoner: %d chains, %d with licence conflict, %d with patent",
            len(chains),
            sum(1 for c in chains if c.has_licence_conflict),
            sum(1 for c in chains if c.has_patent_node),
        )
        return out
    except Exception as e:
        logger.error("path_reasoner failed: %s", e, exc_info=True)
        return None


def run_question_gen(
    chains_path:   Path,
    output_dir:    Path,
    dry_run:       bool          = False,
    max_questions: Optional[int] = None,
) -> Optional[Path]:
    from generation.question_gen import generate_questions, save_questions, print_questions
    out = output_dir / "questions.json"
    try:
        questions = generate_questions(
            chains_path=chains_path,
            output_path=out,
            dry_run=dry_run,
            max_questions=max_questions,
        )
        print_questions(questions)
        save_questions(questions, out)
        logger.info("Question gen: %d questions generated", len(questions))
        return out
    except Exception as e:
        logger.error("question_gen failed: %s", e, exc_info=True)
        return None


# ── Pipeline eval harness ─────────────────────────────────────────────────────

def run_eval(questions_path: Path, ground_truth_path: Optional[Path]) -> dict:
    """
    Minimal eval harness for Phase 1 validation.
    Checks: did every question cite at least one real source node?
    If ground_truth_path provided, computes simple overlap score.
    """
    questions_data = json.loads(questions_path.read_text(encoding="utf-8"))
    questions      = questions_data.get("questions", [])

    results = {
        "total_questions": len(questions),
        "questions_with_audit_trail": sum(
            1 for q in questions if q.get("audit_trail")
        ),
        "questions_with_licence_flag": sum(
            1 for q in questions if q.get("has_licence_conflict")
        ),
        "questions_with_patent_flag": sum(
            1 for q in questions if q.get("has_patent_node")
        ),
        "category_breakdown": {},
    }

    for q in questions:
        cat = q.get("question_category", "unknown")
        results["category_breakdown"][cat] = results["category_breakdown"].get(cat, 0) + 1

    # Phase 1 pass/fail: every question must have an audit trail
    results["phase1_pass"] = (
        results["questions_with_audit_trail"] == results["total_questions"]
        and results["total_questions"] > 0
    )

    if ground_truth_path and ground_truth_path.exists():
        gt = json.loads(ground_truth_path.read_text(encoding="utf-8"))
        gt_questions = [q["question"].lower() for q in gt.get("questions", [])]
        gen_questions = [q["question"].lower() for q in questions]
        # Simple keyword overlap: ≥2 shared words of length ≥4
        overlap_count = 0
        for gen_q in gen_questions:
            gen_words = set(w for w in gen_q.split() if len(w) >= 4)
            for gt_q in gt_questions:
                gt_words = set(w for w in gt_q.split() if len(w) >= 4)
                if len(gen_words & gt_words) >= 2:
                    overlap_count += 1
                    break
        results["ground_truth_overlap"] = overlap_count / max(len(gen_questions), 1)

    return results


def print_eval(results: dict):
    print(f"\n{'═'*60}")
    print("  PIPELINE EVAL RESULTS")
    print(f"{'═'*60}")
    print(f"  Total questions generated  : {results['total_questions']}")
    print(f"  With audit trail           : {results['questions_with_audit_trail']}")
    print(f"  With licence flag          : {results['questions_with_licence_flag']}")
    print(f"  With patent flag           : {results['questions_with_patent_flag']}")
    print(f"\n  Category breakdown:")
    for cat, count in results.get("category_breakdown", {}).items():
        print(f"     {cat:<25} {count}")
    if "ground_truth_overlap" in results:
        print(f"\n  Ground truth overlap       : {results['ground_truth_overlap']:.2%}")
    status = "✓ PASS" if results.get("phase1_pass") else "✗ FAIL"
    print(f"\n  Phase 1 check (all questions have audit trail): {status}")
    print(f"{'═'*60}\n")


# ── Main pipeline ─────────────────────────────────────────────────────────────

def run_pipeline(args: argparse.Namespace) -> bool:
    timer      = StageTimer()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    whitepaper_path = Path(args.whitepaper)
    repo_path       = Path(args.repo)       if args.repo    else None
    patents_path    = Path(args.patents)    if args.patents  else None
    gt_path         = Path(args.ground_truth) if args.ground_truth else None

    # Track output paths as they're produced
    whitepaper_json: Optional[Path] = None
    codebase_json:   Optional[Path] = None
    patent_json:     Optional[Path] = None
    matches_json:    Optional[Path] = None
    kg_json:         Optional[Path] = None
    chains_json:     Optional[Path] = None

    # ── Stage 1: Whitepaper parser ────────────────────────────────────────
    timer.start("whitepaper_parser")
    whitepaper_json = run_whitepaper_parser(whitepaper_path, output_dir)
    timer.stop()
    if not whitepaper_json:
        logger.error("Pipeline aborted: whitepaper_parser failed")
        return False

    # ── Stage 2: GitHub parser ────────────────────────────────────────────
    if repo_path and repo_path.exists():
        timer.start("github_parser")
        codebase_json = run_github_parser(repo_path, output_dir)
        timer.stop()
    else:
        logger.warning("No --repo provided or path doesn't exist — skipping github_parser")
        # Create a minimal placeholder so entity_resolver doesn't crash
        codebase_json = output_dir / "codebase_knowledge.json"
        codebase_json.write_text(
            json.dumps({"dependency_map": {"all_dependencies": []},
                        "import_graph_analysis": {"top_third_party_libraries": []}},
                       indent=2),
            encoding="utf-8"
        )

    # ── Stage 3: Patent parser ────────────────────────────────────────────
    if patents_path and patents_path.exists():
        timer.start("patent_parser")
        patent_json = run_patent_parser(patents_path, output_dir)
        timer.stop()
    else:
        logger.warning("No --patents provided or path doesn't exist — skipping patent_parser")
        patent_json = output_dir / "knowledge_base.json"
        patent_json.write_text(
            json.dumps({"metadata": {"total_triples": 0}, "triples": []}, indent=2),
            encoding="utf-8"
        )

    # ── Stage 4: Entity resolver ──────────────────────────────────────────
    timer.start("entity_resolver")
    matches_json = run_entity_resolver(
        whitepaper_json=whitepaper_json,
        codebase_json=codebase_json,
        patent_json=patent_json,
        output_dir=output_dir,
        threshold=args.resolver_threshold,
    )
    timer.stop()
    if not matches_json:
        logger.error("Pipeline aborted: entity_resolver failed")
        return False

    # ── Stage 5: KG builder ───────────────────────────────────────────────
    timer.start("kg_builder")
    kg_json = run_kg_builder(matches_json, output_dir)
    timer.stop()
    if not kg_json:
        logger.error("Pipeline aborted: kg_builder failed")
        return False

    # ── Stage 6: Path reasoner ────────────────────────────────────────────
    timer.start("path_reasoner")
    chains_json = run_path_reasoner(
        kg_path=kg_json,
        output_dir=output_dir,
        max_hops=args.max_hops,
        threshold=args.chain_threshold,
    )
    timer.stop()
    if not chains_json:
        logger.error("Pipeline aborted: path_reasoner failed")
        return False

    # ── Stage 7b: Export structured evidence ─────────────────────────────
    timer.start("evidence_export")
    from reasoning.path_reasoner import DynamicPathReasoner
    dr = DynamicPathReasoner(output_dir.parent)
    dr.export_evidence()
    timer.stop()

    # ── Stage 7c: Contradiction detection ─────────────────────────────────
    timer.start("contradiction_detector")
    from reasoning.contradiction_detector import detect_contradictions
    detect_contradictions(output_dir.parent)
    timer.stop()

    # ── Stage 8: Risk analyzer ────────────────────────────────────────────
    timer.start("risk_analyzer")
    from scoring.risk_analyzer import RiskAnalyzer
    RiskAnalyzer(output_dir.parent).analyze_evidence()
    timer.stop()

    # ── Stage 9: Explainability audit ─────────────────────────────────────
    timer.start("explainability")
    from audit.explainability_engine import explain
    explain(output_dir.parent)
    timer.stop()

    # ── Stage 7: Question generation ──────────────────────────────────────
    timer.start("question_gen")
    questions_json = run_question_gen(
        chains_path=chains_json,
        output_dir=output_dir,
        dry_run=args.dry_run,
        max_questions=args.max_questions,
    )
    timer.stop()
    if not questions_json:
        logger.error("Pipeline aborted: question_gen failed")
        return False

    # ── Timing report ─────────────────────────────────────────────────────
    timer.print_report()

    # Save timing report
    timing_path = output_dir / "pipeline_timing.json"
    timing_path.write_text(
        json.dumps(timer.report(), indent=2),
        encoding="utf-8"
    )

    # ── Eval harness ──────────────────────────────────────────────────────
    eval_results = run_eval(questions_json, gt_path)
    print_eval(eval_results)

    eval_path = output_dir / "eval_results.json"
    eval_path.write_text(
        json.dumps(eval_results, indent=2),
        encoding="utf-8"
    )

    logger.info("Pipeline complete. All outputs in: %s", output_dir)
    logger.info("Final deliverable: %s", questions_json)
    return True


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="End-to-end VC due-diligence pipeline orchestrator"
    )
    # Inputs
    parser.add_argument("--whitepaper", "-w", required=True,
                        help="Path to startup whitepaper PDF")
    parser.add_argument("--repo", "-r",       default=None,
                        help="Path to startup's code repository root")
    parser.add_argument("--patents", "-p",    default=None,
                        help="Path to directory of patent .txt files")
    parser.add_argument("--output", "-o",     default="data/processed/",
                        help="Output directory (default: data/processed/)")
    # Tuning params
    parser.add_argument("--resolver-threshold", type=float, default=0.78,
                        help="Cosine similarity threshold for entity matching (default: 0.78)")
    parser.add_argument("--chain-threshold",    type=float, default=0.50,
                        help="Min chain score for path_reasoner (default: 0.50)")
    parser.add_argument("--max-hops",           type=int,   default=3,
                        help="Max BFS depth in path_reasoner (default: 3)")
    parser.add_argument("--max-questions",      type=int,   default=None,
                        help="Limit questions generated (useful for testing)")
    # Flags
    parser.add_argument("--dry-run",   action="store_true",
                        help="Run without calling LLM API (prints prompts only)")
    parser.add_argument("--ground-truth", default=None,
                        help="Path to ground-truth questions.json for eval scoring")
    parser.add_argument("--ocr",       action="store_true",
                        help="Force OCR extraction for scanned whitepapers")

    args = parser.parse_args()
    success = run_pipeline(args)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
