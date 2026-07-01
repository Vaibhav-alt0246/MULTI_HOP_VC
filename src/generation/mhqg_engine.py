"""Offline and Ollama-backed multi-hop question generation fallback."""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from difflib import SequenceMatcher
from pathlib import Path

import networkx as nx

project_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(project_root / "src"))

from scoring.legal_analyzer import LegalRiskAnalyzer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

_PROPRIETARY_BUZZWORDS: set[str] = {
    "proprietary",
    "military-grade",
    "military grade",
    "revolutionary",
    "patent-pending",
    "patent pending",
    "trade secret",
    "breakthrough",
    "unique algorithm",
    "novel approach",
    "first of its kind",
    "world's first",
    "industry-leading",
    "state of the art",
    "state-of-the-art",
    "one-of-a-kind",
    "custom-built",
    "home-grown",
    "in-house",
    "secret sauce",
    "proprietary model",
    "proprietary architecture",
}


class MHQGEngine:
    """
    Template-based multi-hop question generation engine.

    This reads a fused knowledge graph and generates due-diligence questions
    without calling an external LLM. It supports both Samhitha's
    ``fused_knowledge_graph.json`` and this repo's ``kg.json`` shape.
    """

    def __init__(self, data_dir: Path, min_risk_level: str | None = None) -> None:
        self.data_dir = data_dir
        self.graph_path = self._resolve_graph_path()
        self.output_path = data_dir / "processed" / "due_diligence_questions.json"
        self.min_risk_level = (min_risk_level or "").upper() or None
        self.G = nx.DiGraph()

    def _resolve_graph_path(self) -> Path:
        kg_path = self.data_dir / "processed" / "kg.json"
        fused_path = self.data_dir / "processed" / "fused_knowledge_graph.json"
        return kg_path if kg_path.exists() else fused_path

    def load_graph(self) -> bool:
        if not self.graph_path.exists():
            logger.error("Graph not found: %s", self.graph_path)
            return False

        data = json.loads(self.graph_path.read_text(encoding="utf-8"))
        for node in data.get("nodes", []):
            node_id = node["id"]
            attrs = {k: v for k, v in node.items() if k != "id"}
            self.G.add_node(node_id, **attrs)

        for edge in data.get("edges", data.get("links", [])):
            source = edge["source"]
            target = edge["target"]
            attrs = {k: v for k, v in edge.items() if k not in ("source", "target")}
            self.G.add_edge(source, target, **attrs)

        logger.info(
            "Loaded graph: %d nodes, %d edges",
            self.G.number_of_nodes(),
            self.G.number_of_edges(),
        )
        return True

    def deduplicate_concepts(self, concepts: list[str]) -> list[str]:
        """Deduplicate concept strings using SequenceMatcher similarity."""
        unique: list[str] = []
        for candidate in concepts:
            is_dup = False
            for existing in unique:
                ratio = SequenceMatcher(None, candidate.lower(), existing.lower()).ratio()
                if ratio >= 0.85:
                    is_dup = True
                    break
            if not is_dup:
                unique.append(candidate)
        return unique

    def _buzzword_score(self, text: str) -> float:
        text_lower = text.lower()
        count = sum(1 for bw in _PROPRIETARY_BUZZWORDS if bw in text_lower)
        return min(count * 0.12, 0.36)

    def _avg_similarity(self, source: str, targets: list[str]) -> float:
        if not targets:
            return 0.0
        sims = []
        for target in targets:
            edge_data = self.G.get_edge_data(source, target, default={})
            sims.append(edge_data.get("similarity", edge_data.get("weight", 0.5)))
        return sum(sims) / len(sims)

    def calculate_risk_score(
        self,
        claim_id: str,
        dependencies: list[str],
        patents: list[str],
        claim_text: str,
    ) -> float:
        """Composite risk score from dependency exposure, patent overlap, and buzzwords."""
        dep_score = min(len(dependencies) / 5.0, 1.0)
        raw_pat = min(len(patents) / 4.0, 1.0)
        avg_sim = self._avg_similarity(claim_id, dependencies)
        patent_score = raw_pat * (0.5 + 0.5 * avg_sim)
        buzzword_score = self._buzzword_score(claim_text)
        score = 0.35 * dep_score + 0.45 * patent_score + 0.20 * buzzword_score
        return round(min(score, 1.0), 2)

    def risk_level(self, score: float) -> str:
        if score >= 0.75:
            return "HIGH"
        if score >= 0.40:
            return "MEDIUM"
        return "LOW"

    def _passes_filter(self, level: str) -> bool:
        if not self.min_risk_level:
            return True
        order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        return order.get(level, 0) >= order.get(self.min_risk_level, 0)

    def _node_label(self, node: str) -> str:
        attrs = self.G.nodes[node]
        return attrs.get("label") or attrs.get("node_type") or node

    def generate_questions(self) -> list[dict]:
        questions: list[dict] = []
        claim_nodes = [
            node for node, attrs in self.G.nodes(data=True)
            if attrs.get("label") == "Marketing_Claim" or attrs.get("node_type") == "Claim"
        ]
        logger.info("Found %d claim nodes", len(claim_nodes))

        for claim_id in claim_nodes:
            claim_attrs = self.G.nodes[claim_id]
            claim_text = (
                claim_attrs.get("text")
                or claim_attrs.get("full_text")
                or claim_attrs.get("source_sentence")
                or claim_attrs.get("label")
                or claim_id
            )

            dependencies = [
                nbr for nbr in self.G.successors(claim_id)
                if self._node_label(nbr) in {"Software_Dependency", "Library"}
            ]

            if not dependencies:
                question_text = (
                    f"Your pitch asserts: '{claim_text[:120]}' - yet our codebase analysis "
                    "found no software dependencies that implement this capability. Can you "
                    "walk us through the specific modules, libraries, or proprietary "
                    "components that deliver this feature in production today?"
                )
                q = {
                    "target_claim": claim_id,
                    "claim_text": claim_text,
                    "dependencies": [],
                    "patent_concepts": [],
                    "risk_score": 0.40,
                    "risk_level": "MEDIUM",
                    "generated_question": question_text,
                    "audit_trail": {
                        "hop_1": "Marketing claim - no dependency link found",
                        "hop_2": [],
                        "hop_3": [],
                    },
                }
                if self._passes_filter("MEDIUM"):
                    questions.append(q)
                continue

            patent_concepts: list[str] = []
            for dep in dependencies:
                for nbr in self.G.successors(dep):
                    if self._node_label(nbr) in {"Patent_Concept", "Patent"}:
                        patent_concepts.append(nbr)
            patent_concepts = self.deduplicate_concepts(list(set(patent_concepts)))

            risk_score = self.calculate_risk_score(
                claim_id,
                dependencies,
                patent_concepts,
                claim_text,
            )
            level = self.risk_level(risk_score)
            dep_list = ", ".join(f"'{d}'" for d in dependencies[:4])
            if len(dependencies) > 4:
                dep_list += f", and {len(dependencies) - 4} others"

            if patent_concepts:
                patent_sample = ", ".join(f"'{p}'" for p in patent_concepts[:2])
                question_text = (
                    "You describe your architecture as proprietary, yet your implementation "
                    f"relies on open-source components including {dep_list}. We also "
                    f"identified potential overlap with patented concepts such as "
                    f"{patent_sample}. What specific technical innovation is uniquely "
                    "yours, and what is your legal strategy for avoiding IP infringement "
                    "as you scale commercially?"
                )
            else:
                question_text = (
                    f"Your implementation depends on {dep_list}. Beyond these third-party "
                    "libraries, what proprietary innovation constitutes your defensible "
                    "competitive moat, and how would that moat hold up if a competitor "
                    "forked the same open-source stack?"
                )

            q = {
                "target_claim": claim_id,
                "claim_text": claim_text,
                "dependencies": dependencies,
                "patent_concepts": patent_concepts,
                "risk_score": risk_score,
                "risk_level": level,
                "generated_question": question_text,
                "audit_trail": {
                    "hop_1": "Marketing Claim Extraction",
                    "hop_2": dependencies,
                    "hop_3": patent_concepts,
                },
            }
            if self._passes_filter(level):
                questions.append(q)

        logger.info(
            "Generated %d questions (%s filter applied)",
            len(questions),
            self.min_risk_level or "none",
        )
        return questions

    def export_questions(self, questions: list[dict]) -> None:
        output = {
            "metadata": {
                "total_questions": len(questions),
                "engine": "Multi-Hop Question Generation (MHQG)",
                "min_risk_filter": self.min_risk_level or "none",
                "risk_distribution": {
                    "HIGH": sum(1 for q in questions if q["risk_level"] == "HIGH"),
                    "MEDIUM": sum(1 for q in questions if q["risk_level"] == "MEDIUM"),
                    "LOW": sum(1 for q in questions if q["risk_level"] == "LOW"),
                },
            },
            "questions": questions,
        }
        self.output_path.write_text(
            json.dumps(output, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info("Saved %d questions to %s", len(questions), self.output_path)

    def run(self) -> None:
        if not self.load_graph():
            return
        questions = self.generate_questions()
        self.export_questions(questions)


class LLMQuestionGenerator:
    """
    Ollama-powered fallback generator using semantic retrieval and legal scoring.
    """

    def __init__(
        self,
        data_dir: Path | str = "data/processed",
        model: str = "llama3",
        top_k: int = 5,
    ) -> None:
        self.data_dir = Path(data_dir)
        self.model = model
        self.top_k = top_k
        self.legal_analyzer = LegalRiskAnalyzer()
        from resolvers.retriever import Retriever

        self.retriever = Retriever(
            index_path=self.data_dir / "vector.index",
            metadata_path=self.data_dir / "vector_metadata.json",
        )

    def retrieve_context(self, query: str) -> list[dict]:
        return self.retriever.retrieve(query, top_k=self.top_k)

    def generate_question(self, claim: str) -> tuple[str, dict]:
        """Return ``(question_text, legal_result_dict)``."""
        contexts = self.retrieve_context(claim)
        context_text = ""
        legal_result = {
            "legal_risk_score": 0.0,
            "risk_level": "LOW",
            "reasons": [],
            "overlap_signals": [],
        }

        for c in contexts:
            context_text += f"\nSOURCE: {c.get('source', 'unknown')}\n"
            context_text += f"TEXT: {c.get('text', '')}\n"

            if c.get("source") == "patent":
                legal_result = self.legal_analyzer.analyze(c)
                context_text += f"PATENT ID: {c.get('patent_id', 'UNKNOWN')}\n"
                context_text += f"STATUS: {c.get('status', 'UNKNOWN')}\n"
                context_text += f"JURISDICTION: {c.get('jurisdiction', 'UNKNOWN')}\n"
                context_text += f"ASSIGNEE: {c.get('assignee', 'UNKNOWN')}\n"
                context_text += f"LICENSE TYPE: {c.get('license_type', 'UNKNOWN')}\n"
                if c.get("legal_claims"):
                    context_text += f"LEGAL CLAIMS: {', '.join(c['legal_claims'])}\n"

        prompt = f"""You are an elite venture capital technical and legal due-diligence analyst.

Startup Claim:
{claim}

Retrieved Context:
{context_text}

Legal Risk Summary:
Risk Score: {legal_result['legal_risk_score']}
Risk Level: {legal_result['risk_level']}
Reasons: {', '.join(legal_result['reasons'])}

Analyze hidden dependency risks, patent overlap, legal discrepancies, license
restrictions, and weak proprietary moat.

Generate one aggressive but professional due-diligence question. Return only the question.
"""
        question = self._call_ollama(prompt)
        return question, legal_result

    def _call_ollama(self, prompt: str) -> str:
        try:
            result = subprocess.run(
                ["ollama", "run", self.model],
                input=prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        except FileNotFoundError:
            logger.error("Ollama binary not found. Install Ollama and pull %s.", self.model)
            return "[ERROR: Ollama not installed]"
        except subprocess.TimeoutExpired:
            logger.error("Ollama timed out after 60s for model '%s'", self.model)
            return "[ERROR: Ollama timeout]"
        except Exception as e:
            logger.error("Unexpected error calling Ollama: %s", e)
            return f"[ERROR: {e}]"

        if result.returncode != 0:
            logger.error("Ollama exited with code %d: %s", result.returncode, result.stderr[:200])
            return f"[ERROR: Ollama exit code {result.returncode}]"

        question = (result.stdout or "").strip()
        if not question:
            logger.warning("Ollama returned empty output for model '%s'", self.model)
            return "[ERROR: empty response from Ollama]"
        return question

    def run(self, whitepaper_name: str = "startup") -> None:
        whitepaper_path = self.data_dir / f"{whitepaper_name}_parsed.json"
        if not whitepaper_path.exists():
            logger.error("Whitepaper not found: %s", whitepaper_path)
            sys.exit(1)

        whitepaper = json.loads(whitepaper_path.read_text(encoding="utf-8"))
        claims = whitepaper.get("technical_claims", [])
        if not claims:
            logger.warning("No technical claims found in %s", whitepaper_path)
            return

        all_results: list[dict] = []
        try:
            for i, claim in enumerate(claims, start=1):
                claim_text = claim["sentence"]
                question, legal_result = self.generate_question(claim_text)
                all_results.append({
                    "claim_id": claim.get("claim_id", f"claim_{i:04d}"),
                    "claim": claim_text,
                    "legal_risk_score": legal_result["legal_risk_score"],
                    "risk_level": legal_result["risk_level"],
                    "reasons": legal_result["reasons"],
                    "overlap_signals": legal_result.get("overlap_signals", []),
                    "llm_generated_question": question,
                })
        except KeyboardInterrupt:
            logger.warning("Interrupted - saving %d partial results", len(all_results))
        finally:
            output_path = self.data_dir / "llm_due_diligence_output.json"
            output_path.write_text(
                json.dumps({
                    "metadata": {
                        "total_claims": len(claims),
                        "total_results": len(all_results),
                        "model": self.model,
                        "top_k_retrieval": self.top_k,
                    },
                    "results": all_results,
                }, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            logger.info("Saved %d results to %s", len(all_results), output_path)


def generate_offline_questions(data_dir: Path | str, min_risk_level: str | None = None) -> list[dict]:
    """Generate template-based offline questions and save them to disk."""
    engine = MHQGEngine(Path(data_dir), min_risk_level=min_risk_level)
    if not engine.load_graph():
        return []
    questions = engine.generate_questions()
    engine.export_questions(questions)
    return questions


def main() -> None:
    parser = argparse.ArgumentParser(description="Fallback multi-hop question generation")
    parser.add_argument("--data-dir", default=None, help="Root data directory")
    parser.add_argument("--min-risk", choices=["LOW", "MEDIUM", "HIGH"], default=None)
    parser.add_argument("--ollama", action="store_true", help="Use Ollama instead of templates")
    parser.add_argument("--whitepaper", default="startup")
    parser.add_argument("--model", default="llama3")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    data_dir = Path(args.data_dir) if args.data_dir else project_root / "data"
    if args.ollama:
        generator = LLMQuestionGenerator(
            data_dir=data_dir / "processed",
            model=args.model,
            top_k=args.top_k,
        )
        generator.run(whitepaper_name=args.whitepaper)
    else:
        generate_offline_questions(data_dir, min_risk_level=args.min_risk)


if __name__ == "__main__":
    main()
