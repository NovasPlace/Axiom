"""
AXIOM DIFF — Gene-level diffing between two .axiom specifications.

Compares chromosomes, genes, expression rules, and instincts.
Reports additions, removals, changes, and integrity violations
(e.g. mutating a locked gene).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .schema import AxiomSpec


@dataclass
class GeneDiff:
    chromosome: str
    gene_name: str
    kind: str  # "changed", "added", "removed"
    field_name: str = ""  # which field changed (value, floor, etc.)
    old_value: Any = None
    new_value: Any = None

    def __str__(self) -> str:
        if self.kind == "added":
            return f"  + {self.chromosome}.{self.gene_name} = {self.new_value}"
        elif self.kind == "removed":
            return f"  - {self.chromosome}.{self.gene_name} (was {self.old_value})"
        else:
            f = f".{self.field_name}" if self.field_name != "value" else ""
            return f"  ~ {self.chromosome}.{self.gene_name}{f}: {self.old_value} → {self.new_value}"


@dataclass
class DiffReport:
    name_a: str
    name_b: str
    changes: list[GeneDiff] = field(default_factory=list)
    added_chromosomes: list[str] = field(default_factory=list)
    removed_chromosomes: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)  # integrity violations

    @property
    def change_count(self) -> int:
        return sum(1 for d in self.changes if d.kind == "changed")

    @property
    def added_count(self) -> int:
        return (
            sum(1 for d in self.changes if d.kind == "added")
            + len(self.added_chromosomes)
        )

    @property
    def removed_count(self) -> int:
        return (
            sum(1 for d in self.changes if d.kind == "removed")
            + len(self.removed_chromosomes)
        )

    def summary(self) -> str:
        lines = [
            f"═══ AXIOM DIFF: {self.name_a} → {self.name_b} ═══",
            f"Changes: {self.change_count}  Added: {self.added_count}  "
            f"Removed: {self.removed_count}  Violations: {len(self.violations)}",
        ]

        if self.added_chromosomes:
            lines.append("")
            lines.append("Added chromosomes:")
            for c in self.added_chromosomes:
                lines.append(f"  + {c}")

        if self.removed_chromosomes:
            lines.append("")
            lines.append("Removed chromosomes:")
            for c in self.removed_chromosomes:
                lines.append(f"  - {c}")

        gene_changes = [d for d in self.changes if d.kind == "changed"]
        if gene_changes:
            lines.append("")
            lines.append("Gene changes:")
            for d in gene_changes:
                lines.append(str(d))

        gene_added = [d for d in self.changes if d.kind == "added"]
        if gene_added:
            lines.append("")
            lines.append("Added genes:")
            for d in gene_added:
                lines.append(str(d))

        gene_removed = [d for d in self.changes if d.kind == "removed"]
        if gene_removed:
            lines.append("")
            lines.append("Removed genes:")
            for d in gene_removed:
                lines.append(str(d))

        if self.violations:
            lines.append("")
            lines.append("⚠ INTEGRITY VIOLATIONS:")
            for v in self.violations:
                lines.append(f"  ✗ {v}")

        if not self.changes and not self.added_chromosomes and not self.removed_chromosomes:
            lines.append("")
            lines.append("No differences found.")

        return "\n".join(lines)


def diff_axiom(spec_a: AxiomSpec, spec_b: AxiomSpec) -> DiffReport:
    """
    Compute a gene-level diff between two AxiomSpecs.

    Detects:
    - Added/removed chromosomes
    - Added/removed genes
    - Changed gene values, floors, ceilings, ranges
    - Integrity violations (mutating locked/immutable genes)
    """
    report = DiffReport(
        name_a=spec_a.name or "A",
        name_b=spec_b.name or "B",
    )

    chroms_a = set(spec_a.chromosomes.keys())
    chroms_b = set(spec_b.chromosomes.keys())

    report.added_chromosomes = sorted(chroms_b - chroms_a)
    report.removed_chromosomes = sorted(chroms_a - chroms_b)

    # Check removed locked chromosomes
    for name in report.removed_chromosomes:
        chrom = spec_a.chromosomes[name]
        if chrom.locked:
            report.violations.append(f"Locked chromosome '{name}' was removed")

    # Diff shared chromosomes
    for cname in sorted(chroms_a & chroms_b):
        chrom_a = spec_a.chromosomes[cname]
        chrom_b = spec_b.chromosomes[cname]

        genes_a = {g.name: g for g in chrom_a.genes}
        genes_b = {g.name: g for g in chrom_b.genes}

        names_a = set(genes_a.keys())
        names_b = set(genes_b.keys())

        # Added genes
        for gname in sorted(names_b - names_a):
            report.changes.append(GeneDiff(
                chromosome=cname, gene_name=gname,
                kind="added", new_value=genes_b[gname].value,
            ))

        # Removed genes
        for gname in sorted(names_a - names_b):
            gene = genes_a[gname]
            if gene.immutable or chrom_a.locked:
                report.violations.append(
                    f"Immutable gene '{cname}.{gname}' was removed"
                )
            report.changes.append(GeneDiff(
                chromosome=cname, gene_name=gname,
                kind="removed", old_value=gene.value,
            ))

        # Changed genes
        for gname in sorted(names_a & names_b):
            ga = genes_a[gname]
            gb = genes_b[gname]

            # Value change
            if ga.value != gb.value:
                if ga.immutable or chrom_a.locked:
                    report.violations.append(
                        f"{'Immutable' if ga.immutable else 'Locked'} "
                        f"gene '{cname}.{gname}' was mutated: "
                        f"{ga.value} → {gb.value}"
                    )
                report.changes.append(GeneDiff(
                    chromosome=cname, gene_name=gname,
                    kind="changed", field_name="value",
                    old_value=ga.value, new_value=gb.value,
                ))

            # Floor change
            if ga.floor != gb.floor:
                report.changes.append(GeneDiff(
                    chromosome=cname, gene_name=gname,
                    kind="changed", field_name="floor",
                    old_value=ga.floor, new_value=gb.floor,
                ))

            # Ceiling change
            if ga.ceiling != gb.ceiling:
                report.changes.append(GeneDiff(
                    chromosome=cname, gene_name=gname,
                    kind="changed", field_name="ceiling",
                    old_value=ga.ceiling, new_value=gb.ceiling,
                ))

            # Range change
            if ga.range != gb.range:
                report.changes.append(GeneDiff(
                    chromosome=cname, gene_name=gname,
                    kind="changed", field_name="range",
                    old_value=ga.range, new_value=gb.range,
                ))

    return report
