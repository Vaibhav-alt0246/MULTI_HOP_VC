"""
Shared marketing-to-engineering terminology map.

The keys are regular expressions used with ``re.IGNORECASE`` by parser and
resolver code. Keep replacements concise because they are written into parsed
claim text and embedding-normalized entity strings.
"""

BUZZWORD_MAP: dict[str, str] = {
    r"hyper[\s-]?fast": "high-throughput",
    r"data[\s-]?mesh": "distributed-data-architecture",
    r"web ?3": "decentralized-web",
    r"ai[\s-]?powered": "ML-augmented",
    r"blockchain[\s-]?enabled": "distributed-ledger",
    r"zero[\s-]?knowledge": "ZK-proof",
    r"quantum[\s-]?resistant": "post-quantum-cryptography",
    r"infinite scal": "horizontal-scalability",
    r"trustless": "cryptographically-verified",
    r"seamless(ly)?": "transparent-integration",
    r"plug[\s-]?and[\s-]?play": "drop-in-deployment",
    r"paradigm[\s-]?shift": "architectural-change",
    r"disruptive": "novel-approach",
    r"revolutionary": "novel-approach",
    r"next[\s-]?gen(eration)?": "next-iteration",
    r"real[\s-]?time": "low-latency (<100ms)",
    r"lightning[\s-]?fast": "sub-second-latency",
    r"military[\s-]?grade": "AES-256 / FIPS-140",
    r"enterprise[\s-]?grade": "production-hardened",
    r"on[\s-]?chain": "stored-in-ledger",
    r"off[\s-]?chain": "off-ledger-computation",
    r"layer[\s-]?2": "L2-scaling-protocol",
    r"smart[\s-]?contract": "self-executing-contract-code",
    r"consensus (mechanism|algorithm|protocol)": "distributed-agreement-protocol",
    r"proof[\s-]of[\s-]work": "PoW",
    r"proof[\s-]of[\s-]stake": "PoS",
    r"byzantine": "BFT-tolerant",
    r"sharding": "horizontal-database-partitioning",
    r"merkle": "Merkle-tree-hash-structure",
}

__all__ = ["BUZZWORD_MAP"]
