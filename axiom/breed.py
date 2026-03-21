"""
AXIOM BREED — Crossover logic for evolving agent specifications.

Takes two parent .axiom files and produces a child by crossing over
genes at non-locked chromosomes. Locked chromosomes (identity, ethics)
are inherited from parent_a (the "mother" spec). Mutable genes are
randomly selected from either parent with optional mutation.

This closes the evolution loop: write a spec → measure phenotype →
breed the best performers → repeat.

Usage:
    from axiom.breed import crossover
    child = crossover(parent_a, parent_b, mutation_rate=0.1)
"""

from __future__ import annotations

import copy
import random
from dataclasses import dataclass, field

from .schema import AxiomSpec, Chromosome, Gene, GeneType


@dataclass
class BreedReport:
    """Summary of a crossover operation."""
    parent_a: str
    parent_b: str
    child_name: str
    inherited_from_a: list[str] = field(default_factory=list)
    inherited_from_b: list[str] = field(default_factory=list)
    mutated: list[str] = field(default_factory=list)
    locked_preserved: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"═══ AXIOM BREED: {self.parent_a} × {self.parent_b} → {self.child_name} ═══",
            f"From {self.parent_a}: {len(self.inherited_from_a)} genes",
            f"From {self.parent_b}: {len(self.inherited_from_b)} genes",
            f"Mutated: {len(self.mutated)} genes",
            f"Locked (preserved): {len(self.locked_preserved)} genes",
        ]

        if self.mutated:
            lines.append("")
            lines.append("Mutations:")
            for m in self.mutated:
                lines.append(f"  ⚡ {m}")

        return "\n".join(lines)


def crossover(
    parent_a: AxiomSpec,
    parent_b: AxiomSpec,
    mutation_rate: float = 0.1,
    child_name: str | None = None,
    seed: int | None = None,
) -> tuple[AxiomSpec, BreedReport]:
    """
    Cross two axiom specs to produce a child.

    Rules:
    1. Locked chromosomes are inherited entirely from parent_a
    2. Mutable chromosomes: each gene is randomly selected from either parent
    3. Genes only in one parent are passed through
    4. With probability mutation_rate, a float gene is slightly perturbed
    5. Floors, ceilings, and ranges are always enforced post-mutation

    Args:
        parent_a: Primary parent (locked genes come from here)
        parent_b: Secondary parent
        mutation_rate: Probability of mutating each mutable float gene (0.0-1.0)
        child_name: Name for the child spec (default: "child of A × B")
        seed: Random seed for reproducibility

    Returns:
        (child_spec, breed_report)
    """
    if seed is not None:
        random.seed(seed)

    name = child_name or f"child of {parent_a.name} × {parent_b.name}"

    report = BreedReport(
        parent_a=parent_a.name,
        parent_b=parent_b.name,
        child_name=name,
    )

    child = AxiomSpec(
        version=parent_a.version,
        name=name,
        author=f"{parent_a.author or 'unknown'} × {parent_b.author or 'unknown'}",
        substrate=parent_a.substrate,
        description=f"Bred from {parent_a.name} and {parent_b.name}",
        parent=f"{parent_a.name} × {parent_b.name}",
    )

    # Collect all chromosome names from both parents
    all_chroms = set(parent_a.chromosomes.keys()) | set(parent_b.chromosomes.keys())

    for chrom_name in sorted(all_chroms):
        chrom_a = parent_a.get_chromosome(chrom_name)
        chrom_b = parent_b.get_chromosome(chrom_name)

        # If only one parent has this chromosome, inherit it directly
        if chrom_a and not chrom_b:
            child.chromosomes[chrom_name] = copy.deepcopy(chrom_a)
            for g in chrom_a.genes:
                report.inherited_from_a.append(f"{chrom_name}.{g.name}")
            continue
        if chrom_b and not chrom_a:
            child.chromosomes[chrom_name] = copy.deepcopy(chrom_b)
            for g in chrom_b.genes:
                report.inherited_from_b.append(f"{chrom_name}.{g.name}")
            continue

        # Both parents have this chromosome
        # Locked chromosomes → inherit entirely from parent_a
        if chrom_a.locked or chrom_b.locked:
            child.chromosomes[chrom_name] = copy.deepcopy(chrom_a)
            for g in chrom_a.genes:
                report.locked_preserved.append(f"{chrom_name}.{g.name}")
            continue

        # Mutable chromosome → crossover genes
        child_chrom = Chromosome(
            name=chrom_name,
            locked=False,
            description=chrom_a.description or chrom_b.description,
        )

        genes_a = {g.name: g for g in chrom_a.genes}
        genes_b = {g.name: g for g in chrom_b.genes}
        all_gene_names = set(genes_a.keys()) | set(genes_b.keys())

        for gene_name in sorted(all_gene_names):
            ga = genes_a.get(gene_name)
            gb = genes_b.get(gene_name)

            # Only in one parent
            if ga and not gb:
                child_chrom.genes.append(copy.deepcopy(ga))
                report.inherited_from_a.append(f"{chrom_name}.{gene_name}")
                continue
            if gb and not ga:
                child_chrom.genes.append(copy.deepcopy(gb))
                report.inherited_from_b.append(f"{chrom_name}.{gene_name}")
                continue

            # Both parents have it — pick one randomly
            if ga.immutable:
                # Immutable genes always from parent_a
                child_chrom.genes.append(copy.deepcopy(ga))
                report.locked_preserved.append(f"{chrom_name}.{gene_name}")
                continue

            chosen = random.choice([ga, gb])
            child_gene = copy.deepcopy(chosen)

            if chosen is ga:
                report.inherited_from_a.append(f"{chrom_name}.{gene_name}")
            else:
                report.inherited_from_b.append(f"{chrom_name}.{gene_name}")

            # Mutation chance for float genes
            if child_gene.type == GeneType.FLOAT and random.random() < mutation_rate:
                old_val = float(child_gene.value)
                # Gaussian perturbation, σ = 0.05
                new_val = old_val + random.gauss(0, 0.05)

                # Enforce bounds
                if child_gene.range is not None:
                    lo, hi = child_gene.range
                    new_val = max(lo, min(hi, new_val))
                if child_gene.floor is not None:
                    new_val = max(child_gene.floor, new_val)
                if child_gene.ceiling is not None:
                    new_val = min(child_gene.ceiling, new_val)

                new_val = round(new_val, 3)
                child_gene.value = new_val
                report.mutated.append(
                    f"{chrom_name}.{gene_name}: {old_val} → {new_val}"
                )

            child_chrom.genes.append(child_gene)

        child.chromosomes[chrom_name] = child_chrom

    # Expression rules: union from both parents (deduplicated by condition)
    seen_conditions = set()
    for rule in parent_a.expression_rules + parent_b.expression_rules:
        if rule.condition not in seen_conditions:
            child.expression_rules.append(copy.deepcopy(rule))
            seen_conditions.add(rule.condition)

    # Instincts: union from both parents (deduplicated by trigger)
    seen_triggers = set()
    for inst in parent_a.instincts + parent_b.instincts:
        if inst.trigger not in seen_triggers:
            child.instincts.append(copy.deepcopy(inst))
            seen_triggers.add(inst.trigger)

    return child, report


def axiom_to_yaml(spec: AxiomSpec) -> str:
    """Serialize an AxiomSpec back to YAML-formatted .axiom text."""
    import yaml

    doc = {
        "axiom": spec.version,
        "name": spec.name,
        "author": spec.author,
        "substrate": spec.substrate,
        "description": spec.description,
    }
    if spec.parent:
        doc["parent"] = spec.parent

    for chrom_name, chrom in spec.chromosomes.items():
        chrom_dict: dict = {}
        if chrom.locked:
            chrom_dict["locked"] = True
        if chrom.description:
            chrom_dict["description"] = chrom.description

        genes_list = []
        for gene in chrom.genes:
            g: dict = {"name": gene.name, "type": gene.type.value, "value": gene.value}
            if gene.expression:
                g["expression"] = gene.expression
            if gene.range is not None:
                g["range"] = list(gene.range)
            if gene.floor is not None:
                g["floor"] = gene.floor
            if gene.ceiling is not None:
                g["ceiling"] = gene.ceiling
            if gene.immutable:
                g["immutable"] = True
            if gene.options:
                g["options"] = gene.options
            genes_list.append(g)

        chrom_dict["genes"] = genes_list
        doc[chrom_name] = chrom_dict

    # Expression rules
    if spec.expression_rules:
        when_list = []
        for rule in spec.expression_rules:
            when_list.append({
                "if": rule.condition,
                "set": dict(rule.set_values),
            })
        doc["when"] = when_list

    # Instincts
    if spec.instincts:
        inst_list = []
        for inst in spec.instincts:
            entry = {"on": inst.trigger, "do": inst.action}
            if inst.description:
                entry["description"] = inst.description
            inst_list.append(entry)
        doc["instincts"] = inst_list

    return yaml.dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)
