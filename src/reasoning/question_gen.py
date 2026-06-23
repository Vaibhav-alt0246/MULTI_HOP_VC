"""
question_gen.py — Adversarial Question Generator
=================================================
Multi-Hop Reasoning System for VC Technical Due Diligence

Takes hop_chains.json (from hop_reasoner.py) and calls an LLM to generate
one pointed, adversarial due-diligence question per chain. Every question
is returned with its full provenance audit trail.

Output:
    data/processed/questions.json

Usage:
    pip install anthropic
    export ANTHROPIC_API_KEY=your_key_here

    python src/reasoning/question_gen.py
    python src/reasoning/question_gen.py --chains data/processed/hop_chains.json
    python src/reasoning/question_gen.py --dry-run   # prints prompts, no API call
"""

import os
import json
import logging
import argparse
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────

MODEL            = "claude-sonnet-4-6"
MAX_TOKENS       = 512
RETRY_ATTEMPTS   = 3
RETRY_DELAY      = 2.0      # seconds between retries
RATE_LIMIT_DELAY = 0.5      # seconds between API calls

# System prompt — instructs the LLM to behave as an adversarial VC analyst
SYSTEM_PROMPT = """You are a senior technical due-diligence analyst at a venture capital firm.
Your job is to generate sharp, specific, adversarial questions that a VC partner should ask
a startup founder during a technical review meeting.

Rules:
- Ask exactly ONE question per response. No preamble, no explanation, just the question.
- The question must be grounded in the specific technical evidence provided.
- Reference the actual library names, patent concepts, or licence types mentioned.
- The question should be something the founder cannot easily deflect with a vague answer.
- Focus on: IP conflicts, licence restrictions, technical feasibility, hidden dependencies,
  or claims that cannot be substantiated by the codebase evidence.
- Tone: professional but pointed. A good question makes the founder pause.
- Do NOT ask generic questions like "How do you plan to scale?" unless directly supported
  by the evidence chain.
- End the question with a question mark."""


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class GeneratedQuestion:
    question_id: str
    chain_id: str
    question: str
    question_category: str      # licence_risk | ip_conflict | feasibility | dependency
    chain_score: float
    hop_count: int
    has_licence_conflict: bool
    has_patent_node: bool
    audit_trail: list[dict]     # human-readable hop-by-hop provenance
    raw_provenance: dict        # full chain provenance for downstream use


# ── Prompt builder ────────────────────────────────────────────────────────────

def build_chain_summary(chain: dict) -> str:
    """
    Convert a hop chain into a structured evidence block for the LLM prompt.
    The more specific this is, the more grounded the generated question will be.
    """
    prov   = chain.get("provenance", {})
    nodes  = prov.get("nodes", [])
    edges  = prov.get("edges", [])
    lines  = ["EVIDENCE CHAIN:"]

    for i, edge in enumerate(edges):
        from_node = next((n for n in nodes if n["node_id"] == edge["from"]), {})
        to_node   = next((n for n in nodes if n["node_id"] == edge["to"]),   {})

        from_type  = from_node.get("node_type", "Unknown")
        to_type    = to_node.get("node_type",   "Unknown")
        from_label = from_node.get("label", edge["from"])
        to_label   = to_node.get("label",   edge["to"])
        edge_type  = edge.get("edge_type", "relates_to")
        weight     = edge.get("weight", 0.0)

        # Pull meaningful metadata per node type
        from_meta = from_node.get("metadata", {})
        to_meta   = to_node.get("metadata",   {})

        hop_line = f"  Hop {i+1}: [{from_type}] \"{from_label}\""
        if from_type == "Claim":
            hop_line += f" (type={from_meta.get('claim_type','?')}, page={from_meta.get('page','?')})"
        elif from_type == "Library":
            hop_line += f" (licence={from_meta.get('licence','?')}, risk={from_meta.get('licence_risk','?')})"
        elif from_type == "Patent":
            hop_line += f" (relationship: {from_meta.get('relationship','?')})"

        hop_line += f"\n        --[{edge_type} | similarity={weight:.2f}]-->"
        hop_line += f"\n        [{to_type}] \"{to_label}\""

        if to_type == "Library":
            hop_line += f" (licence={to_meta.get('licence','?')}, risk={to_meta.get('licence_risk','?')})"
        elif to_type == "Patent":
            hop_line += f"\n        Patent claim context: \"{to_meta.get('source_sentence','')[:150]}\""
        elif to_type == "LicenceType":
            hop_line += f" (commercial_use_restricted={to_meta.get('commercial_use_restricted','?')})"

        lines.append(hop_line)

    lines.append(f"\nCHAIN CONFIDENCE SCORE: {chain.get('chain_score', 0.0):.4f}")

    flags = []
    if chain.get("has_licence_conflict"):
        flags.append("LICENCE CONFLICT DETECTED")
    if chain.get("has_patent_node"):
        flags.append("PATENT OVERLAP DETECTED")
    if flags:
        lines.append("FLAGS: " + " | ".join(flags))

    return "\n".join(lines)


def build_prompt(chain: dict) -> str:
    """Full user prompt sent to the LLM for one chain."""
    chain_summary = build_chain_summary(chain)
    return f"""A startup's technical whitepaper has been cross-referenced against open-source
dependency data and patent databases. The following evidence chain was discovered.

{chain_summary}

Based on this specific evidence chain, generate one adversarial due-diligence question
that a VC partner should ask the startup founder."""


def categorize_question(chain: dict) -> str:
    """Assign a category label to the question based on chain properties."""
    if chain.get("has_licence_conflict"):
        return "licence_risk"
    if chain.get("has_patent_node"):
        return "ip_conflict"
    edges = chain.get("path_edges", [])
    if "implements" in edges:
        return "dependency"
    return "feasibility"


# ── Audit trail builder ───────────────────────────────────────────────────────

def build_audit_trail(chain: dict) -> list[dict]:
    """
    Build a clean, human-readable audit trail from a hop chain.
    This is what gets shown to the VC analyst alongside the question.
    Format: [{step, node_type, label, relationship_to_next}]
    """
    prov  = chain.get("provenance", {})
    nodes = prov.get("nodes", [])
    edges = prov.get("edges", [])
    trail = []

    for i, node in enumerate(nodes):
        step = {
            "step":      i + 1,
            "node_type": node.get("node_type"),
            "label":     node.get("label", node.get("node_id")),
            "metadata":  node.get("metadata", {}),
        }
        if i < len(edges):
            step["relationship_to_next"] = edges[i].get("edge_type")
            step["similarity_score"]     = edges[i].get("weight")
        trail.append(step)

    return trail


# ── LLM caller ───────────────────────────────────────────────────────────────

def call_llm(prompt: str, dry_run: bool = False) -> Optional[str]:
    """
    Call the Anthropic API with retry logic.
    Returns the generated question string, or None on failure.
    """
    if dry_run:
        logger.info("[DRY RUN] Prompt:\n%s", prompt)
        return "[DRY RUN] What specific measures has your team taken to ensure that your use of [library] complies with its [licence] licence given your commercial deployment plans?"

    try:
        import anthropic
    except ImportError:
        raise SystemExit(
            "anthropic package not found.\n"
            "Install: pip install anthropic\n"
            "Then:    export ANTHROPIC_API_KEY=your_key"
        )

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise SystemExit(
            "ANTHROPIC_API_KEY environment variable not set.\n"
            "Run: export ANTHROPIC_API_KEY=your_key"
        )

    client = anthropic.Anthropic(api_key=api_key)

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            # Sanity check: must end with a question mark
            if not text.endswith("?"):
                text = text.rstrip(".") + "?"
            return text

        except Exception as e:
            logger.warning("API call attempt %d/%d failed: %s", attempt, RETRY_ATTEMPTS, e)
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY * attempt)

    logger.error("All %d API attempts failed for this chain", RETRY_ATTEMPTS)
    return None


# ── Main generator ────────────────────────────────────────────────────────────

def generate_questions(
    chains_path: Path,
    output_path: Path,
    dry_run: bool = False,
    max_questions: Optional[int] = None,
) -> list[GeneratedQuestion]:
    """
    Main pipeline: load chains → build prompts → call LLM → collect questions.
    Processes chains in priority order (licence conflicts first, then patents).
    """
    data   = json.loads(chains_path.read_text(encoding="utf-8"))
    chains = data.get("chains", [])

    if max_questions:
        chains = chains[:max_questions]

    logger.info("Generating questions for %d chains...", len(chains))

    questions: list[GeneratedQuestion] = []
    q_counter = 0

    for i, chain in enumerate(chains):
        chain_id = chain.get("chain_id", f"chain_{i:04d}")
        logger.info(
            "[%d/%d] Processing %s (score=%.3f, hops=%d)",
            i + 1, len(chains),
            chain_id,
            chain.get("chain_score", 0),
            chain.get("hop_count", 0),
        )

        prompt   = build_prompt(chain)
        question = call_llm(prompt, dry_run=dry_run)

        if question is None:
            logger.warning("Skipping %s — LLM call failed", chain_id)
            continue

        q_counter += 1
        audit_trail = build_audit_trail(chain)
        category    = categorize_question(chain)

        questions.append(GeneratedQuestion(
            question_id=f"q_{q_counter:04d}",
            chain_id=chain_id,
            question=question,
            question_category=category,
            chain_score=chain.get("chain_score", 0.0),
            hop_count=chain.get("hop_count", 0),
            has_licence_conflict=chain.get("has_licence_conflict", False),
            has_patent_node=chain.get("has_patent_node", False),
            audit_trail=audit_trail,
            raw_provenance=chain.get("provenance", {}),
        ))

        # Rate limiting between API calls
        if not dry_run and i < len(chains) - 1:
            time.sleep(RATE_LIMIT_DELAY)

    logger.info("Generated %d questions from %d chains", len(questions), len(chains))
    return questions


# ── Output ────────────────────────────────────────────────────────────────────

def save_questions(questions: list[GeneratedQuestion], output_path: Path) -> None:
    by_category: dict[str, int] = {}
    for q in questions:
        by_category[q.question_category] = by_category.get(q.question_category, 0) + 1

    output = {
        "metadata": {
            "total_questions": len(questions),
            "by_category": by_category,
            "licence_risk_questions":  sum(1 for q in questions if q.has_licence_conflict),
            "ip_conflict_questions":   sum(1 for q in questions if q.has_patent_node),
            "model_used": MODEL,
        },
        "questions": [asdict(q) for q in questions],
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(output, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )
    logger.info("Saved questions → %s", output_path)


def print_questions(questions: list[GeneratedQuestion]) -> None:
    print(f"\n{'═'*72}")
    print("  GENERATED DUE-DILIGENCE QUESTIONS")
    print(f"{'═'*72}")

    for q in questions:
        flags = []
        if q.has_licence_conflict:
            flags.append("⚠ LICENCE")
        if q.has_patent_node:
            flags.append("⚠ PATENT")
        flag_str = "  ".join(flags)

        print(f"\n  [{q.question_id}] {q.question_category.upper()}  {flag_str}")
        print(f"  Score: {q.chain_score:.4f}  |  Hops: {q.hop_count}  |  Chain: {q.chain_id}")
        print(f"\n  Q: {q.question}")
        print(f"\n  Audit trail:")
        for step in q.audit_trail:
            rel = f" --[{step.get('relationship_to_next')}]--> " if step.get("relationship_to_next") else ""
            print(f"     {step['step']}. [{step['node_type']}] {step['label']}{rel}")
        print(f"  {'─'*66}")

    print(f"\n{'═'*72}\n")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Generate adversarial VC due-diligence questions from hop chains"
    )
    parser.add_argument("--chains",        default="data/processed/hop_chains.json")
    parser.add_argument("--output",        default="data/processed/questions.json")
    parser.add_argument("--max-questions", type=int, default=None,
                        help="Limit number of questions generated (useful for testing)")
    parser.add_argument("--dry-run",       action="store_true",
                        help="Print prompts without calling the API")
    args = parser.parse_args()

    questions = generate_questions(
        chains_path=Path(args.chains),
        output_path=Path(args.output),
        dry_run=args.dry_run,
        max_questions=args.max_questions,
    )
    print_questions(questions)
    save_questions(questions, Path(args.output))


if __name__ == "__main__":
    main()