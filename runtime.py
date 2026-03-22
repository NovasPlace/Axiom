"""
AXIOM RUNTIME — Live genome evaluation, mutation ledger, and context integration.

Extends the static axiom toolkit with runtime capabilities:
  - Evaluate an .axiom file with live context → ActiveGenome
  - Record gene mutations with timestamp and reason
  - Auto-detect context from environment signals

This is the bridge between "what the spec says" and "how the agent
actually behaves right now." The compiler produces a static prompt.
The runtime produces a living, context-sensitive genome.

Usage:
    from axiom.runtime import AxiomRuntime

    runtime = AxiomRuntime("agent.axiom")
    genome = runtime.evaluate({"task_type": "debugging"})
    genome.get("cognition.verification_drive")  # → 0.98 (adjusted)

    # Mutate a gene
    runtime.apply_mutation("humor_affinity", 0.6, reason="user prefers playful")

    # View mutation history
    for m in runtime.get_mutations():
        print(m)
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from .schema import parse_axiom, AxiomSpec, Gene, GeneType


# ── Active Genome ─────────────────────────────────────────────────────────────

@dataclass
class ActiveGenome:
    """A resolved genome — all genes evaluated against a specific context."""
    name: str
    genes: dict[str, Any] = field(default_factory=dict)           # "section.gene" → value
    expressions: dict[str, str] = field(default_factory=dict)     # "section.gene" → expression text
    immutables: set[str] = field(default_factory=set)             # set of immutable gene keys
    instincts: list[dict[str, str]] = field(default_factory=list)
    fired_rules: list[str] = field(default_factory=list)          # which when: rules activated

    def get(self, key: str, default: Any = None) -> Any:
        return self.genes.get(key, default)

    def render(self) -> str:
        """Render this genome as a human-readable block for prompt injection."""
        lines = [f"## ACTIVE GENOME — {self.name}"]
        if self.fired_rules:
            lines.append(f"> Context rules applied: {', '.join(self.fired_rules)}")
        lines.append("")

        current_section = None
        for key in sorted(self.genes.keys()):
            section, gene_name = key.split(".", 1) if "." in key else ("", key)
            if section != current_section:
                current_section = section
                lines.append(f"### {section.title()}")

            val = self.genes[key]
            expr = self.expressions.get(key, "")
            immutable_tag = " [IMMUTABLE]" if key in self.immutables else ""
            expr_suffix = f"  — {expr[:80]}" if expr else ""
            lines.append(f"  {gene_name}: {val}{immutable_tag}{expr_suffix}")
            lines.append("")

        if self.instincts:
            lines.append("### Instincts")
            for inst in self.instincts:
                lines.append(f"  {inst.get('on', '?')} → {inst.get('do', '?')}")
            lines.append("")

        return "\n".join(lines)


# ── Runtime ───────────────────────────────────────────────────────────────────

class AxiomRuntime:
    """Runtime evaluator for .axiom files.

    Wraps the axiom schema + compiler with runtime features:
    mutation tracking, context evaluation, and active genome generation.
    """

    def __init__(self, axiom_path: str | Path):
        self.path = Path(axiom_path)
        self.spec = parse_axiom(self.path)
        self._mutation_file = self.path.with_suffix(".mutations.jsonl")

    def evaluate(self, context: dict | None = None) -> ActiveGenome:
        """Evaluate the axiom with optional context, returning an ActiveGenome."""
        ctx = context or {}
        genes: dict[str, Any] = {}
        expressions: dict[str, str] = {}
        immutables: set[str] = set()

        # 1. Load all base gene values
        for chrom_name, chrom in self.spec.chromosomes.items():
            for gene in chrom.genes:
                key = f"{chrom_name}.{gene.name}"
                genes[key] = gene.value
                expressions[key] = gene.expression
                if gene.immutable or chrom.locked:
                    immutables.add(key)

        # 2. Apply when: expression rules
        fired_rules: list[str] = []
        for rule in self.spec.expression_rules:
            if self._eval_condition(rule.condition, ctx):
                fired_rules.append(rule.condition)
                for gene_name, override_val in rule.set_values.items():
                    # Find the full key
                    for full_key in genes:
                        if full_key.endswith(f".{gene_name}"):
                            if full_key not in immutables:
                                genes[full_key] = override_val
                            break

        # 3. Clamp values within defined ranges
        for chrom_name, chrom in self.spec.chromosomes.items():
            for gene in chrom.genes:
                key = f"{chrom_name}.{gene.name}"
                val = genes.get(key)
                if isinstance(val, (int, float)):
                    if gene.floor is not None:
                        val = max(gene.floor, val)
                    if gene.ceiling is not None:
                        val = min(gene.ceiling, val)
                    if gene.range is not None:
                        lo, hi = gene.range
                        val = max(lo, min(hi, val))
                    genes[key] = val

        # 4. Instincts
        instincts = [
            {"on": inst.trigger, "do": inst.action, "description": inst.description}
            for inst in self.spec.instincts
        ]

        return ActiveGenome(
            name=self.spec.name,
            genes=genes,
            expressions=expressions,
            immutables=immutables,
            instincts=instincts,
            fired_rules=fired_rules,
        )

    def _eval_condition(self, condition: str, ctx: dict) -> bool:
        """Evaluate a simple condition string against context."""
        condition = condition.strip()
        for op, fn in [
            (">=", lambda a, b: float(a) >= float(b)),
            ("<=", lambda a, b: float(a) <= float(b)),
            ("!=", lambda a, b: str(a).strip("'\"") != str(b).strip("'\"")),
            ("==", lambda a, b: str(a).strip("'\"") == str(b).strip("'\"")),
            (">",  lambda a, b: float(a) > float(b)),
            ("<",  lambda a, b: float(a) < float(b)),
        ]:
            if op in condition:
                parts = condition.split(op, 1)
                if len(parts) == 2:
                    key = parts[0].strip()
                    expected = parts[1].strip().strip("'\"")
                    actual = ctx.get(key)
                    if actual is None:
                        return False
                    try:
                        return fn(actual, expected)
                    except (ValueError, TypeError):
                        return False
        return False

    # ── Mutation Ledger ───────────────────────────────────────────────────────

    def apply_mutation(self, gene_name: str, new_value: Any,
                       reason: str = "", source: str = "manual") -> bool:
        """Mutate a gene value. Records to ledger and updates the .axiom file.

        Returns False if the gene is immutable or doesn't exist.
        """
        # Find the gene
        gene = self.spec.find_gene(gene_name)
        if gene is None:
            return False

        if gene.immutable:
            print(f"Gene '{gene_name}' is immutable — cannot mutate.")
            return False

        # Check chromosome lock
        for chrom in self.spec.chromosomes.values():
            if chrom.locked and chrom.get_gene(gene_name):
                print(f"Gene '{gene_name}' is in locked chromosome '{chrom.name}'.")
                return False

        old_value = gene.value

        # Write mutation record
        record = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "gene": gene_name,
            "old": old_value,
            "new": new_value,
            "reason": reason,
            "source": source,
        }
        with open(self._mutation_file, "a") as f:
            f.write(json.dumps(record) + "\n")

        # Patch the .axiom file
        self._patch_axiom_file(gene_name, old_value, new_value)

        # Reload spec
        self.spec = parse_axiom(self.path)
        return True

    def get_mutations(self, limit: int = 50) -> list[dict]:
        """Read mutation history from the ledger."""
        if not self._mutation_file.exists():
            return []
        records = []
        for line in self._mutation_file.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        return records[-limit:]

    def _patch_axiom_file(self, gene_name: str, old_value: Any, new_value: Any) -> None:
        """Surgically update a gene value in the .axiom file."""
        text = self.path.read_text()
        if isinstance(old_value, str):
            old_repr = f'"{old_value}"'
            new_repr = f'"{new_value}"'
        else:
            old_repr = str(old_value)
            new_repr = str(new_value)

        # Match: "value: <old>" within 5 lines of "name: <gene_name>"
        lines = text.split("\n")
        in_gene = False
        patched = False
        for i, line in enumerate(lines):
            if f"name: {gene_name}" in line:
                in_gene = True
                continue
            if in_gene:
                stripped = line.strip()
                if stripped.startswith("- name:") or (stripped.startswith("- ") and "name:" in stripped):
                    in_gene = False
                    continue
                if stripped.startswith("value:"):
                    # Replace value
                    indent = len(line) - len(line.lstrip())
                    lines[i] = " " * indent + f"value: {new_repr}"
                    patched = True
                    break

        if patched:
            self.path.write_text("\n".join(lines))

    # ── Context Auto-Detection ────────────────────────────────────────────────

    @staticmethod
    def detect_context() -> dict:
        """Auto-detect runtime context from environment signals.

        Checks:
        - Pressure daemon socket
        - Session freshness
        - Environment variables
        """
        ctx: dict[str, Any] = {}

        # Pressure from daemon socket
        try:
            import socket
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            _state_dir = os.environ.get("AXIOM_STATE_DIR", os.path.expanduser("~/.axiom"))
            sock.connect(os.path.join(_state_dir, ".pressure.sock"))
            sock.sendall(b'{"action":"status"}\n')
            data = sock.recv(4096)
            sock.close()
            resp = json.loads(data)
            if "pressure" in resp:
                ctx["pressure"] = resp["pressure"]
        except Exception:
            ctx["pressure"] = 0.0

        # Session freshness (new vs bonded)
        _state_dir = os.environ.get("AXIOM_STATE_DIR", os.path.expanduser("~/.axiom"))
        session_file = Path(_state_dir) / "session.md"
        if session_file.exists():
            import time
            age = time.time() - session_file.stat().st_mtime
            ctx["relationship"] = "bonded" if age < 86400 else "new"
        else:
            ctx["relationship"] = "new"

        return ctx
