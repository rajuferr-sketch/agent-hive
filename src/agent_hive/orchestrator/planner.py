"""Planner — request analysis, complexity scoring and mode selection.

Three operating modes:

* **A — simple** (complexity < simple_threshold): one capable agent works
  independently.
* **C — adaptive** (simple_threshold..adaptive_threshold): 2-10 agents,
  one per workstream.
* **B — collective** (> adaptive_threshold): all 20 agents contribute to
  the same mission, with integration, cross-review and final validation.

Complexity is a 0..1 heuristic combining length, domain breadth and
multi-part structure. The Master Agent can force any mode explicitly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from agent_hive.config.loader import SystemConfig

MODE_A = "A"
MODE_C = "C"
MODE_B = "B"

# domain → keyword triggers
DOMAIN_KEYWORDS: dict[str, list[str]] = {
    "code": ["code", "program", "function", "class", "script", "bug", "refactor",
             "implement", "algorithm", "codice", "funzione", "programmazione"],
    "docs": ["document", "readme", "manual", "guide", "documentation", "documentazione"],
    "security": ["security", "vulnerability", "authentication", "encryption", "threat",
                 "sicurezza", "password", "secret"],
    "data": ["database", "schema", "sql", "migration", "query", "index", "database"],
    "frontend": ["ui", "ux", "interface", "frontend", "layout", "design", "css", "html"],
    "api": ["api", "endpoint", "rest", "graphql", "contract", "webhook"],
    "testing": ["test", "qa", "coverage", "pytest", "testing", "test"],
    "operations": ["deploy", "ci", "cd", "docker", "pipeline", "infrastructure", "devops"],
    "performance": ["performance", "optimize", "latency", "throughput", "benchmark",
                    "prestazioni", "ottimizzare"],
    "architecture": ["architecture", "design system", "microservice", "scalability",
                     "architettura", "progetto"],
}

# domain → capabilities used to match agents
DOMAIN_CAPABILITIES: dict[str, list[str]] = {
    "code": ["programming", "refactoring", "debugging"],
    "docs": ["documentation"],
    "security": ["security", "threat_modeling"],
    "data": ["database"],
    "frontend": ["frontend", "design", "ux"],
    "api": ["api", "contract_design"],
    "testing": ["testing", "testing_design", "quality"],
    "operations": ["automation", "deployment"],
    "performance": ["performance", "profiling", "optimization"],
    "architecture": ["architecture", "scalability"],
}

# agents always part of a collective mission (pipeline roles)
PIPELINE_ROLES = ["integration", "qa", "verifier", "reviewer", "validator"]


@dataclass(slots=True)
class Analysis:
    complexity: float
    domains: list[str]
    keywords: list[str]
    multi_part: bool
    mode: str = MODE_A
    forced: bool = False


@dataclass(slots=True)
class Workstream:
    title: str
    capability: str
    description: str
    depends_on: list[str] = field(default_factory=list)


def analyze(text: str, config: SystemConfig) -> Analysis:
    """Score the request complexity and detect domains."""
    text = (text or "").strip()
    words = re.findall(r"\w+", text.lower())
    complexity = 0.05
    # length factor
    complexity += min(len(words) / 400, 1.0) * 0.25
    # domain breadth
    domains = [
        d for d, kws in DOMAIN_KEYWORDS.items()
        if any(k in text.lower() for k in kws)
    ]
    complexity += {0: 0.0, 1: 0.05}.get(len(domains), 0.05 * min(len(domains), 6))
    # multi-part structure (numbered items, bullets, explicit steps)
    multi_part = bool(
        re.search(r"(^|\n)\s*(\d+\.|-|\*)\s", text) or len(re.findall(r"\band then\b|\bpoi\b|\be anche\b", text.lower())) > 1
    )
    if multi_part:
        complexity += 0.12
    # big-mission signals
    if re.search(r"\b(entire|complete|full|end.to.end|intero|completo|sistema|progetto)\b", text.lower()):
        complexity += 0.15
    complexity = round(max(0.0, min(1.0, complexity)), 2)
    keywords = sorted({w for w in words if len(w) > 3})[:15]
    return Analysis(complexity=complexity, domains=domains,
                    keywords=keywords, multi_part=multi_part)


def choose_mode(analysis: Analysis, config: SystemConfig, forced: str | None = None) -> str:
    """Select operating mode: A (simple), C (adaptive), B (collective)."""
    if forced:
        if forced not in {MODE_A, MODE_B, MODE_C}:
            raise ValueError(f"Invalid mode '{forced}' — use A, C or B")
        analysis.mode, analysis.forced = forced, True
        return forced
    if analysis.complexity < config.simple_threshold:
        mode = MODE_A
    elif analysis.complexity < config.adaptive_threshold:
        mode = MODE_C
    else:
        mode = MODE_B
    analysis.mode = mode
    return mode


def plan_workstreams(analysis: Analysis, config: SystemConfig) -> list[Workstream]:
    """Decompose the mission into capability-oriented workstreams."""
    if analysis.mode == MODE_A:
        capability = DOMAIN_CAPABILITIES.get(
            analysis.domains[0] if analysis.domains else "code", ["analysis"]
        )[0]
        return [Workstream(
            title="Single-agent execution",
            capability=capability,
            description="Complete the request independently with the best-matched agent.",
        )]

    if analysis.domains:
        domains = analysis.domains
    else:
        domains = ["code"]
    streams = [
        Workstream(
            title=f"Workstream: {domain}",
            capability=DOMAIN_CAPABILITIES[domain][0],
            description=(
                f"Handle the '{domain}' dimension of the mission; align with the "
                "shared mission context and other agents' contributions."
            ),
        )
        for domain in domains
    ]
    # Cap the adaptive mode
    if analysis.mode == MODE_C and len(streams) < config.adaptive_min_agents:
        streams.extend([
            Workstream(title="Workstream: verification",
                       capability="verification",
                       description="Cross-check the produced work for consistency."),
            Workstream(title="Workstream: quality review",
                       capability="quality",
                       description="Review deliverable quality against acceptance criteria."),
        ])
    return streams
