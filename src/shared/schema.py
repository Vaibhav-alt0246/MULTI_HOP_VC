"""
schema.py — Canonical constants for vc_due_diligence pipeline.
Every module that references node types, edge types, or output filenames
must import from here instead of using string literals.
"""

NODE_TYPES = {
    "CLAIM":               "Claim",
    "LIBRARY":             "Library",
    "PATENT":              "Patent",
    "LICENCE_TYPE":        "LicenceType",
    "STARTUP":             "Startup",
    "MARKETING_CLAIM":     "Marketing_Claim",
    "PATENT_CONCEPT":      "Patent_Concept",
    "CODE_MODULE":         "Code_Module",
    "OPENSOURCE_LICENSE":  "OpenSource_License",
}

EDGE_TYPES = {
    "IMPLEMENTS":                   "implements",
    "CITES":                        "cites",
    "CONFLICTS_WITH":               "conflicts_with",
    "LICENCED_UNDER":               "licenced_under",
    "LICENSED_UNDER":               "licenced_under",
    "SIMILAR_TO":                   "similar_to",
    "REQUIRES_IP_REVIEW":           "REQUIRES_IP_REVIEW",
    "POTENTIALLY_IMPLEMENTED_BY":   "POTENTIALLY_IMPLEMENTED_BY",
    "ASSERTS":                      "ASSERTS",
    "IMPORTS":                      "IMPORTS",
    "SUPPORTS":                     "supports",
}

# Canonical output filenames — every stage must write to exactly these names
OUTPUT_FILES = {
    "whitepaper":             "startup_parsed.json",
    "patents":                "knowledge_base.json",
    "codebase":               "codebase_knowledge.json",
    "entity_matches":         "entity_matches.json",
    "kg":                     "kg.json",
    "hop_chains":             "hop_chains.json",
    "structured_evidence":    "structured_evidence.json",
    "contradiction_evidence": "contradiction_evidence.json",
    "vc_risk_report":         "vc_risk_report.json",
    "audited_vc_report":      "audited_vc_report.json",
    "questions":              "due_diligence_questions.json",
}
# Direct constant aliases — kg_builder.py imports these by name
EDGE_LICENSED_UNDER              = EDGE_TYPES["LICENCED_UNDER"]
EDGE_LICENCED_UNDER              = EDGE_TYPES["LICENCED_UNDER"]
EDGE_IMPLEMENTS                  = EDGE_TYPES["IMPLEMENTS"]
EDGE_CITES                       = EDGE_TYPES["CITES"]
EDGE_CONFLICTS_WITH              = EDGE_TYPES["CONFLICTS_WITH"]
EDGE_SIMILAR_TO                  = EDGE_TYPES["SIMILAR_TO"]
EDGE_REQUIRES_IP_REVIEW          = EDGE_TYPES["REQUIRES_IP_REVIEW"]
EDGE_POTENTIALLY_IMPLEMENTED_BY  = EDGE_TYPES["POTENTIALLY_IMPLEMENTED_BY"]
EDGE_ASSERTS                     = EDGE_TYPES["ASSERTS"]
EDGE_IMPORTS                     = EDGE_TYPES["IMPORTS"]
EDGE_SUPPORTS                    = EDGE_TYPES["SUPPORTS"]
NODE_CLAIM        = NODE_TYPES["CLAIM"]
NODE_LIBRARY      = NODE_TYPES["LIBRARY"]
NODE_PATENT       = NODE_TYPES["PATENT"]
NODE_LICENCE_TYPE = NODE_TYPES["LICENCE_TYPE"]
NODE_STARTUP      = NODE_TYPES["STARTUP"]