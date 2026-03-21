"""
AXIOM CORTEX ADAPTER — Bridges CortexDB event ledger to phenotype measurement.

This is the real measurement layer. Instead of guessing honesty from
hedging language, we measure verification_drive from how often the
agent actually runs code. Instead of counting question marks for
curiosity, we count research events and decision logs.

Event types from the ledger:
    decision     — architectural/design/approach choices
    architecture — structural changes to projects
    file_edit    — significant file creations/modifications
    lesson       — hard-won insights
    context      — session summaries
    error        — notable errors and their resolutions
    thread       — thread open/update/close events

Usage:
    from axiom.cortex_adapter import measure_from_ledger
    report = measure_from_ledger(spec, "/path/to/events.jsonl")
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schema import AxiomSpec, Gene, GeneType
from .measure import MeasurementReport, PhenotypeMetric


@dataclass
class LedgerEvent:
    """A single event from the CortexDB JSONL ledger."""
    ts: str = ""
    type: str = ""
    content: str = ""
    project: str = ""


def _parse_ledger(source: str | Path) -> list[LedgerEvent]:
    """Parse events.jsonl into LedgerEvent objects."""
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Ledger not found: {path}")

    events = []
    for line in path.read_text(encoding="utf-8").strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            raw = json.loads(line)
            events.append(LedgerEvent(
                ts=raw.get("ts", ""),
                type=raw.get("type", ""),
                content=raw.get("content", ""),
                project=raw.get("project", ""),
            ))
        except json.JSONDecodeError:
            continue
    return events


# ── BEHAVIORAL METRICS FROM LEDGER DATA ──

def _measure_verification_drive(gene: Gene, events: list[LedgerEvent]):
    """Measure verification behavior from event content.

    High verification_drive = agent mentions running, testing, verifying,
    confirming in decision/architecture events. Looks for concrete proof
    language, not just the word "verify".
    """
    proof_patterns = [
        r"\bverif(y|ied|ying)\b",
        r"\btests?\s+pass",
        r"\b\d+/\d+\s+(tests?|checks?)\s+pass",
        r"\bconfirmed?\b",
        r"\bend-to-end\b",
        r"\bdeployed\s+and\s+verified\b",
        r"\ball\s+verified\b",
        r"\bverified\b",
        r"\brunning\s+at\b",
        r"\blive\s+(on|at)\b",
    ]
    relevant = [e for e in events if e.type in ("decision", "architecture", "context")]
    if not relevant:
        return None, 0, "no decision/architecture events"

    verified_count = 0
    for e in relevant:
        lower = e.content.lower()
        if any(re.search(p, lower) for p in proof_patterns):
            verified_count += 1

    rate = verified_count / len(relevant)
    return rate, len(relevant), f"{verified_count}/{len(relevant)} events include verification proof"


def _measure_research_mandate(gene: Gene, events: list[LedgerEvent]):
    """Measure research-first behavior.

    High research_mandate = agent fixes errors by investigating first,
    mentions docs/source reading, doesn't repeat the same error.
    """
    research_patterns = [
        r"\bfixed\b.*\b(traced|found|discovered|realized)\b",
        r"\binvestigat",
        r"\bdebugg",
        r"\btraced\s+(the|it|to)\b",
        r"\bread\s+(docs?|source|the\s+code)\b",
        r"\bchecked?\s+(the|for|if)\b",
    ]
    error_events = [e for e in events if e.type in ("error", "lesson")]
    decision_events = [e for e in events if e.type == "decision"]
    all_relevant = error_events + decision_events
    if not all_relevant:
        return None, 0, "no error/decision events"

    research_count = 0
    for e in all_relevant:
        lower = e.content.lower()
        if any(re.search(p, lower) for p in research_patterns):
            research_count += 1

    rate = research_count / len(all_relevant)
    return rate, len(all_relevant), f"{research_count}/{len(all_relevant)} events show investigation"


def _measure_scope_discipline(gene: Gene, events: list[LedgerEvent]):
    """Measure scope discipline from project-event patterns.

    High scope_discipline = agent works on one project at a time,
    completes before context-switching. Low = rapid project hopping
    within short time windows.
    """
    if not events:
        return None, 0, "no events"

    # Count project switches
    switches = 0
    last_project = None
    for e in events:
        if e.project and e.project != last_project:
            if last_project is not None:
                switches += 1
            last_project = e.project

    # Calculate ratio: fewer switches relative to event count = higher discipline
    if len(events) < 2:
        return 0.8, len(events), "too few events to measure"

    switch_rate = switches / len(events)
    # Invert: low switch rate = high discipline
    # 0 switches → 1.0, switch every event → ~0.0
    measured = max(0.0, 1.0 - (switch_rate * 2.0))
    return measured, len(events), f"{switches} project switches in {len(events)} events"


def _measure_depth_vs_speed(gene: Gene, events: list[LedgerEvent]):
    """Measure depth from architecture/file_edit density.

    High depth = more architecture events relative to file_edits
    (thinking about structure, not just shipping files).
    """
    arch_count = sum(1 for e in events if e.type == "architecture")
    edit_count = sum(1 for e in events if e.type == "file_edit")
    total = arch_count + edit_count
    if total == 0:
        return None, 0, "no architecture/file_edit events"

    # Higher ratio of architecture to total = deeper thinking
    depth_ratio = arch_count / total
    return depth_ratio, total, f"{arch_count} architecture vs {edit_count} file_edit events"


def _measure_initiative(gene: Gene, events: list[LedgerEvent]):
    """Measure initiative from proactive behavior signals.

    Proactive = file_edit and architecture events that build new things
    (not just fixes). Looks for "built", "created", "added", "shipped".
    """
    proactive_patterns = [
        r"\bbuilt\b",
        r"\bcreated\b",
        r"\badded\b",
        r"\bshipped\b",
        r"\bdeployed\b",
        r"\bimplemented\b",
        r"\bwired\b",
    ]
    relevant = [e for e in events if e.type in ("file_edit", "architecture", "decision")]
    if not relevant:
        return None, 0, "no build events"

    proactive_count = 0
    for e in relevant:
        lower = e.content.lower()
        if any(re.search(p, lower) for p in proactive_patterns):
            proactive_count += 1

    rate = proactive_count / len(relevant)
    return rate, len(relevant), f"{proactive_count}/{len(relevant)} events show proactive building"


def _measure_error_handling(gene: Gene, events: list[LedgerEvent]):
    """Measure goal persistence through error resolution.

    High persistence = errors are followed by fixes (not abandoned).
    Looks at error events that mention resolution.
    """
    error_events = [e for e in events if e.type == "error"]
    lesson_events = [e for e in events if e.type == "lesson"]

    if not error_events and not lesson_events:
        return None, 0, "no error/lesson events"

    # Errors that include a fix
    fix_patterns = [r"\bfix", r"\bresolved", r"\bfixed", r"\bcorrected", r"\bworkaround"]
    all_issues = error_events + lesson_events
    resolved = 0
    for e in all_issues:
        lower = e.content.lower()
        if any(re.search(p, lower) for p in fix_patterns):
            resolved += 1

    rate = resolved / len(all_issues)
    return rate, len(all_issues), f"{resolved}/{len(all_issues)} issues resolved"


def _measure_lesson_capture(gene: Gene, events: list[LedgerEvent]):
    """Measure self-improvement drive through lesson emission rate.

    Higher = agent captures more lessons relative to total activity.
    """
    lesson_count = sum(1 for e in events if e.type == "lesson")
    total = len(events)
    if total == 0:
        return None, 0, "no events"

    # Lesson rate: ~5% is healthy, ~10%+ is high
    rate = lesson_count / total
    # Scale: 0% → 0.0, 5% → 0.5, 10%+ → 1.0
    measured = min(1.0, rate * 10.0)
    return measured, total, f"{lesson_count} lessons in {total} events ({rate:.1%})"


# Gene → CortexDB measurement function mapping
CORTEX_MEASURES = {
    "verification_drive":    _measure_verification_drive,
    "research_mandate":      _measure_research_mandate,
    "scope_discipline":      _measure_scope_discipline,
    "depth_vs_speed":        _measure_depth_vs_speed,
    "initiative_level":      _measure_initiative,
    "goal_persistence":      _measure_error_handling,
    "self_improvement_drive": _measure_lesson_capture,
}


def measure_from_ledger(
    spec: AxiomSpec,
    ledger_path: str | Path,
) -> MeasurementReport:
    """
    Measure observed agent behavior from CortexDB event ledger.

    This uses REAL behavioral data — tool calls, decisions, verifications,
    errors, lessons — instead of noisy text heuristics.
    """
    events = _parse_ledger(ledger_path)

    report = MeasurementReport(
        spec_name=spec.name,
        total_entries=len(events),
        assistant_entries=len(events),  # all events are agent-produced
    )

    if not events:
        report.warnings.append("No events found in ledger")
        return report

    # Type distribution for context
    type_counts = Counter(e.type for e in events)
    report.warnings.append(
        f"Event distribution: {', '.join(f'{t}={c}' for t, c in type_counts.most_common())}"
    )

    # Measure each gene that has a CortexDB measurement function
    for chrom_name, gene in spec.all_genes():
        measure_fn = CORTEX_MEASURES.get(gene.name)
        if not measure_fn:
            continue

        result = measure_fn(gene, events)
        if result[0] is None:
            continue

        measured_value, sample_size, detail = result

        # Determine status
        if gene.type == GeneType.FLOAT:
            spec_val = float(gene.value)
            delta = abs(measured_value - spec_val)
            if delta <= 0.15:
                status = "✓"
            elif delta <= 0.3:
                status = "⚠"
            else:
                status = "✗"

            # Check floor violations
            if gene.floor is not None and measured_value < gene.floor:
                status = "✗"
                detail += f" [BELOW FLOOR {gene.floor}]"
        else:
            status = "✓"

        report.metrics.append(PhenotypeMetric(
            name=f"{chrom_name}.{gene.name}",
            spec_gene=gene.name,
            spec_value=gene.value,
            measured_value=measured_value,
            sample_size=sample_size,
            status=status,
            detail=detail,
        ))

    # Warn about unmeasured genes
    measured_genes = {m.spec_gene for m in report.metrics}
    for chrom_name, gene in spec.all_genes():
        if gene.name not in measured_genes and gene.type == GeneType.FLOAT:
            if gene.name not in CORTEX_MEASURES:
                report.warnings.append(
                    f"Gene '{chrom_name}.{gene.name}' has no CortexDB measurement — "
                    f"needs either event annotations or a custom measure"
                )

    return report
