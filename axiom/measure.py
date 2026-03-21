"""
AXIOM MEASURE — Phenotype measurement against genotype specification.

This is the moat. Anyone can write a YAML schema. Phenotype measurement —
"your agent SAYS it has 0.85 verification drive, here's the actual
measured value from logs" — is genuinely novel.

The measurement system analyzes agent interaction logs and computes
observed behavioral metrics, then compares them against the .axiom
spec to find drift, miscalibration, and expression failures.

Usage:
    from axiom.measure import measure_phenotype
    report = measure_phenotype(spec, log_entries)
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .schema import AxiomSpec, Gene, GeneType


# ── LOG ENTRY FORMAT ──
# The measurement system works with structured logs.
# Each entry has: timestamp, role (user/assistant/system/tool),
# content, and optional metadata.

@dataclass
class LogEntry:
    timestamp: str = ""
    role: str = ""           # user, assistant, system, tool
    content: str = ""
    metadata: dict = field(default_factory=dict)
    # Derived metrics (computed during analysis)
    word_count: int = 0
    has_hedging: bool = False
    has_verification: bool = False
    has_question: bool = False
    has_humor: bool = False
    has_apology: bool = False
    has_refusal: bool = False
    has_tool_call: bool = False
    response_ms: int = 0


# ── PHENOTYPE METRICS ──

@dataclass
class PhenotypeMetric:
    """A single measured behavioral metric."""
    name: str
    spec_gene: str              # which gene this maps to
    spec_value: Any             # what the spec says
    measured_value: float       # what we actually observed
    sample_size: int            # how many data points
    status: str = ""            # ✓ aligned, ⚠ drift, ✗ violation
    detail: str = ""            # human-readable explanation

    @property
    def delta(self) -> float | None:
        if isinstance(self.spec_value, (int, float)) and isinstance(self.measured_value, (int, float)):
            return abs(float(self.measured_value) - float(self.spec_value))
        return None


@dataclass
class MeasurementReport:
    """Complete phenotype measurement report."""
    spec_name: str
    total_entries: int
    assistant_entries: int
    metrics: list[PhenotypeMetric] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def aligned_count(self) -> int:
        return sum(1 for m in self.metrics if m.status == "✓")

    @property
    def drift_count(self) -> int:
        return sum(1 for m in self.metrics if m.status == "⚠")

    @property
    def violation_count(self) -> int:
        return sum(1 for m in self.metrics if m.status == "✗")

    def summary(self) -> str:
        lines = [
            f"═══ AXIOM PHENOTYPE REPORT: {self.spec_name} ═══",
            f"Log entries analyzed: {self.total_entries} ({self.assistant_entries} assistant)",
            f"Metrics measured: {len(self.metrics)}",
            f"  ✓ Aligned: {self.aligned_count}",
            f"  ⚠ Drift:   {self.drift_count}",
            f"  ✗ Violation: {self.violation_count}",
            "",
        ]

        for m in self.metrics:
            spec_str = f"{m.spec_value}"
            meas_str = f"{m.measured_value:.2f}" if isinstance(m.measured_value, float) else str(m.measured_value)
            lines.append(
                f"  {m.status} {m.name:<30} spec={spec_str:<8} actual={meas_str:<8} "
                f"(n={m.sample_size}) {m.detail}"
            )

        if self.warnings:
            lines.append("")
            lines.append("Warnings:")
            for w in self.warnings:
                lines.append(f"  ⚡ {w}")

        return "\n".join(lines)


# ── LOG PARSING ──

def parse_logs(source: str | Path | list[dict]) -> list[LogEntry]:
    """
    Parse logs from various formats into LogEntry objects.

    Supports:
    - List of dicts with role/content keys
    - JSONL file (one JSON object per line)
    - Plain text file with "role: content" format
    """
    if isinstance(source, list):
        return [_parse_entry(e) for e in source]

    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Log file not found: {path}")

    entries = []
    text = path.read_text()

    # Try JSONL
    try:
        for line in text.strip().split("\n"):
            line = line.strip()
            if line:
                entries.append(_parse_entry(json.loads(line)))
        return entries
    except json.JSONDecodeError:
        pass

    # Try full JSON array
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [_parse_entry(e) for e in data]
    except json.JSONDecodeError:
        pass

    # Fall back to plain text: "assistant: Hello" format
    for line in text.strip().split("\n"):
        match = re.match(r"^(user|assistant|system|tool):\s*(.+)", line, re.IGNORECASE)
        if match:
            entries.append(LogEntry(role=match.group(1).lower(), content=match.group(2)))

    return entries


def _parse_entry(raw: dict) -> LogEntry:
    """Parse a single log entry dict."""
    entry = LogEntry(
        timestamp=str(raw.get("timestamp", raw.get("ts", ""))),
        role=raw.get("role", "").lower(),
        content=raw.get("content", raw.get("text", raw.get("message", ""))),
        metadata=raw.get("metadata", {}),
    )
    _annotate_entry(entry)
    return entry


def _annotate_entry(entry: LogEntry):
    """Compute derived metrics for a log entry."""
    text = entry.content
    entry.word_count = len(text.split())

    lower = text.lower()

    # Hedging / uncertainty markers
    hedging_patterns = [
        r"\bi('m| am) not (sure|certain)\b",
        r"\bi don'?t know\b",
        r"\bpossibly\b", r"\bperhaps\b", r"\bmaybe\b",
        r"\bmight be\b", r"\bcould be\b",
        r"\buncertain\b", r"\bnot confident\b",
        r"\bI think\b", r"\bI believe\b",
    ]
    entry.has_hedging = any(re.search(p, lower) for p in hedging_patterns)

    # Verification markers
    verify_patterns = [
        r"\bverif(y|ied|ying|ication)\b",
        r"\bconfirm(ed|ing)?\b",
        r"\bvalidat(e|ed|ing|ion)\b",
        r"\bchecked?\b",
        r"\btested?\b",
        r"\bproved?\b",
        r"\bproven\b",
    ]
    entry.has_verification = any(re.search(p, lower) for p in verify_patterns)

    # Questions
    entry.has_question = "?" in text

    # Humor markers
    humor_patterns = [
        r"\bhaha\b", r"\blol\b", r"\b[;:]-?\)\b",
        r"😂|😄|🤣|😆|😏",
        r"\bjoking\b", r"\bjust kidding\b",
    ]
    entry.has_humor = any(re.search(p, lower) for p in humor_patterns)

    # Apology markers
    apology_patterns = [
        r"\bsorry\b", r"\bapologi(ze|es)\b",
        r"\bmy (bad|mistake)\b",
        r"\bi was wrong\b",
    ]
    entry.has_apology = any(re.search(p, lower) for p in apology_patterns)

    # Refusal markers
    refusal_patterns = [
        r"\bi (can'?t|cannot|won'?t|will not)\b.*\b(do|help|provide|generate)\b",
        r"\bi('m| am) (not able|unable)\b",
        r"\bthat'?s (not|beyond)\b",
    ]
    entry.has_refusal = any(re.search(p, lower) for p in refusal_patterns)

    # Tool call markers
    entry.has_tool_call = bool(
        re.search(r"\btool_call\b|\bfunction_call\b", lower)
        or entry.metadata.get("tool_calls")
        or entry.role == "tool"
    )


# ── PHENOTYPE MEASUREMENT ──

# Gene → Measurement function mapping
# Each function takes (gene, assistant_entries, all_entries) and returns
# (measured_value, sample_size, detail_string)

def _measure_verbosity(gene: Gene, assistant: list[LogEntry], all_entries: list[LogEntry]):
    """Measure average words per response. Map to 0-1 scale."""
    if not assistant:
        return None, 0, "no assistant responses"
    word_counts = [e.word_count for e in assistant]
    avg = statistics.mean(word_counts)
    # Map: 0 words = 0.0, 500+ words = 1.0
    measured = min(1.0, avg / 500.0)
    return measured, len(assistant), f"avg {avg:.0f} words/response"


def _measure_honesty(gene: Gene, assistant: list[LogEntry], all_entries: list[LogEntry]):
    """Measure honesty through hedging/uncertainty expression frequency."""
    if not assistant:
        return None, 0, "no data"
    hedging_count = sum(1 for e in assistant if e.has_hedging)
    # Higher hedging rate = more honest about uncertainty
    # We measure this as the PRESENCE of honest uncertainty, not its absence
    rate = hedging_count / len(assistant) if assistant else 0
    # Map to scale: 0% hedging when needed → 0.0, healthy hedging → 0.8+
    measured = min(1.0, rate * 3.0)  # ~33% hedging rate → 1.0
    return measured, len(assistant), f"{hedging_count}/{len(assistant)} responses express uncertainty"


def _measure_verification(gene: Gene, assistant: list[LogEntry], all_entries: list[LogEntry]):
    """Measure how often the agent verifies its own output."""
    if not assistant:
        return None, 0, "no data"
    verify_count = sum(1 for e in assistant if e.has_verification)
    rate = verify_count / len(assistant)
    return rate, len(assistant), f"{verify_count}/{len(assistant)} responses include verification"


def _measure_humor(gene: Gene, assistant: list[LogEntry], all_entries: list[LogEntry]):
    """Measure humor frequency."""
    if not assistant:
        return None, 0, "no data"
    humor_count = sum(1 for e in assistant if e.has_humor)
    rate = humor_count / len(assistant)
    return rate, len(assistant), f"{humor_count}/{len(assistant)} responses contain humor"


def _measure_curiosity(gene: Gene, assistant: list[LogEntry], all_entries: list[LogEntry]):
    """Measure curiosity through question-asking frequency."""
    if not assistant:
        return None, 0, "no data"
    question_count = sum(1 for e in assistant if e.has_question)
    rate = question_count / len(assistant)
    return rate, len(assistant), f"{question_count}/{len(assistant)} responses ask questions"


def _measure_emotional_expression(gene: Gene, assistant: list[LogEntry], all_entries: list[LogEntry]):
    """Measure emotional expression through apologies, humor, hedging combined."""
    if not assistant:
        return None, 0, "no data"
    emotional_count = sum(
        1 for e in assistant
        if e.has_humor or e.has_apology or e.has_hedging
    )
    rate = emotional_count / len(assistant)
    return rate, len(assistant), f"{emotional_count}/{len(assistant)} show emotional signals"


def _measure_formality(gene: Gene, assistant: list[LogEntry], all_entries: list[LogEntry]):
    """Measure formality through linguistic markers."""
    if not assistant:
        return None, 0, "no data"
    informal_markers = [
        r"\byeah\b", r"\bnah\b", r"\byep\b", r"\bnope\b",
        r"\bgonna\b", r"\bwanna\b", r"\bkinda\b", r"\bsorta\b",
        r"\blol\b", r"\bbtw\b", r"\bomg\b", r"\bidk\b",
        r"\bcool\b", r"\bawesome\b",
    ]
    informal_count = 0
    for e in assistant:
        lower = e.content.lower()
        if any(re.search(p, lower) for p in informal_markers):
            informal_count += 1
    # More informal = lower formality score
    informality_rate = informal_count / len(assistant)
    formality = 1.0 - min(1.0, informality_rate * 2.0)
    return formality, len(assistant), f"{informal_count}/{len(assistant)} informal responses"


# Gene name → measurement function mapping
GENE_MEASURES = {
    "verbosity":             _measure_verbosity,
    "honesty_override":      _measure_honesty,
    "honesty":               _measure_honesty,
    "honesty_principle":     _measure_honesty,
    "verification_drive":    _measure_verification,
    "humor_affinity":        _measure_humor,
    "humor":                 _measure_humor,
    "curiosity_drive":       _measure_curiosity,
    "curiosity":             _measure_curiosity,
    "emotional_expression":  _measure_emotional_expression,
    "formality":             _measure_formality,
}


def measure_phenotype(
    spec: AxiomSpec,
    logs: str | Path | list[dict] | list[LogEntry],
) -> MeasurementReport:
    """
    Measure observed agent behavior against the .axiom specification.

    Args:
        spec: The parsed .axiom specification.
        logs: Log entries — file path, list of dicts, or list of LogEntry.

    Returns:
        MeasurementReport with per-gene measurements and drift analysis.
    """
    # Parse logs if needed
    if not logs:
        return MeasurementReport(
            spec_name=spec.name, total_entries=0, assistant_entries=0,
            warnings=["No log data provided"],
        )

    if isinstance(logs, (str, Path)):
        entries = parse_logs(logs)
    elif logs and isinstance(logs[0], dict):
        entries = parse_logs(logs)
    else:
        entries = logs
        for e in entries:
            _annotate_entry(e)

    assistant_entries = [e for e in entries if e.role == "assistant"]

    report = MeasurementReport(
        spec_name=spec.name,
        total_entries=len(entries),
        assistant_entries=len(assistant_entries),
    )

    if not assistant_entries:
        report.warnings.append("No assistant responses found in logs")
        return report

    # Measure each gene that has a measurement function
    for chrom_name, gene in spec.all_genes():
        measure_fn = GENE_MEASURES.get(gene.name)
        if not measure_fn:
            continue

        result = measure_fn(gene, assistant_entries, entries)
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
        elif gene.type == GeneType.BOOL:
            if gene.value is True and measured_value < 0.5:
                status = "✗"
            elif gene.value is False and measured_value > 0.5:
                status = "✗"
            else:
                status = "✓"
        else:
            status = "✓"  # can't easily measure non-numeric genes

        report.metrics.append(PhenotypeMetric(
            name=f"{chrom_name}.{gene.name}",
            spec_gene=gene.name,
            spec_value=gene.value,
            measured_value=measured_value,
            sample_size=sample_size,
            status=status,
            detail=detail,
        ))

    # Check for unmeasured genes
    measured_genes = {m.spec_gene for m in report.metrics}
    for chrom_name, gene in spec.all_genes():
        if gene.name not in measured_genes and gene.type == GeneType.FLOAT:
            if gene.name not in GENE_MEASURES:
                report.warnings.append(
                    f"Gene '{chrom_name}.{gene.name}' has no measurement function — "
                    f"consider adding a custom measure or log annotations"
                )

    return report
