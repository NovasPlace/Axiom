"""
AXIOM SCHEMA — Data models and YAML parser for .axiom files.

This is the foundation everything else depends on.
Defines: AxiomSpec, Chromosome, Gene, GeneType, ExpressionRule, Instinct.
Parses .axiom (YAML) files into validated Python objects.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

import yaml


class GeneType(enum.Enum):
    FLOAT = "float"
    INT = "int"
    BOOL = "bool"
    STRING = "string"
    ENUM = "enum"

    @classmethod
    def from_str(cls, s: str) -> GeneType:
        mapping = {
            "float": cls.FLOAT,
            "int": cls.INT,
            "bool": cls.BOOL,
            "string": cls.STRING,
            "str": cls.STRING,
            "enum": cls.ENUM,
        }
        return mapping.get(s.lower(), cls.STRING)


@dataclass
class Gene:
    name: str
    type: GeneType = GeneType.STRING
    value: Any = None
    expression: str = ""
    range: tuple[float, float] | None = None
    floor: float | None = None
    ceiling: float | None = None
    immutable: bool = False
    options: list[str] | None = None  # for enum type

    def validate(self) -> list[str]:
        """Return a list of validation errors for this gene."""
        errors = []
        if not self.name:
            errors.append("Gene has no name")

        if self.type == GeneType.FLOAT:
            try:
                v = float(self.value)
            except (TypeError, ValueError):
                errors.append(f"Gene '{self.name}': value '{self.value}' is not a valid float")
                return errors

            if self.floor is not None and v < self.floor:
                errors.append(f"Gene '{self.name}': value {v} is below floor {self.floor}")
            if self.ceiling is not None and v > self.ceiling:
                errors.append(f"Gene '{self.name}': value {v} is above ceiling {self.ceiling}")
            if self.range is not None:
                lo, hi = self.range
                if v < lo or v > hi:
                    errors.append(f"Gene '{self.name}': value {v} outside range [{lo}, {hi}]")

        if self.type == GeneType.ENUM:
            if self.options and self.value not in self.options:
                errors.append(
                    f"Gene '{self.name}': value '{self.value}' not in options {self.options}"
                )

        if self.type == GeneType.INT:
            try:
                int(self.value)
            except (TypeError, ValueError):
                errors.append(f"Gene '{self.name}': value '{self.value}' is not a valid int")

        return errors


@dataclass
class Chromosome:
    name: str
    locked: bool = False
    description: str = ""
    genes: list[Gene] = field(default_factory=list)

    def get_gene(self, name: str) -> Gene | None:
        for g in self.genes:
            if g.name == name:
                return g
        return None


@dataclass
class ExpressionRule:
    condition: str
    set_values: dict[str, Any] = field(default_factory=dict)


@dataclass
class Instinct:
    trigger: str
    action: str
    description: str = ""


@dataclass
class AxiomSpec:
    version: str = "1.0"
    name: str = ""
    author: str = ""
    substrate: str = "any"
    description: str = ""
    parent: str = ""  # for spec inheritance

    chromosomes: dict[str, Chromosome] = field(default_factory=dict)
    expression_rules: list[ExpressionRule] = field(default_factory=list)
    instincts: list[Instinct] = field(default_factory=list)

    def get_chromosome(self, name: str) -> Chromosome | None:
        return self.chromosomes.get(name)

    def all_genes(self) -> Iterator[tuple[str, Gene]]:
        """Yield (chromosome_name, gene) for every gene in the spec."""
        for chrom_name, chrom in self.chromosomes.items():
            for gene in chrom.genes:
                yield chrom_name, gene

    def find_gene(self, name: str) -> Gene | None:
        """Find a gene by name across all chromosomes."""
        for _, gene in self.all_genes():
            if gene.name == name:
                return gene
        return None

    def validate(self) -> list[str]:
        """Validate the entire spec. Returns list of error strings."""
        errors = []

        if not self.name:
            errors.append("Spec has no 'name'")
        if not self.version:
            errors.append("Spec has no 'axiom' version")

        # Validate all genes
        for chrom_name, gene in self.all_genes():
            for err in gene.validate():
                errors.append(f"[{chrom_name}] {err}")

        # Validate expression rules reference real genes
        all_gene_names = {g.name for _, g in self.all_genes()}
        for rule in self.expression_rules:
            for gene_name in rule.set_values:
                if gene_name not in all_gene_names:
                    errors.append(
                        f"Expression rule '{rule.condition}' references unknown gene '{gene_name}'"
                    )

            # Check that overrides respect immutable / locked
            for gene_name, val in rule.set_values.items():
                gene = self.find_gene(gene_name)
                if gene and gene.immutable:
                    errors.append(
                        f"Expression rule '{rule.condition}' tries to override "
                        f"immutable gene '{gene_name}'"
                    )
                # Check chromosome lock
                for cn, ch in self.chromosomes.items():
                    if ch.locked and ch.get_gene(gene_name):
                        errors.append(
                            f"Expression rule '{rule.condition}' tries to override "
                            f"gene '{gene_name}' in locked chromosome '{cn}'"
                        )

        return errors


# ── YAML PARSER ──

# Known chromosome names. Any top-level key matching these is parsed as a chromosome.
# Custom chromosomes are also supported — anything with a 'genes' list.
KNOWN_CHROMOSOMES = {
    "identity", "cognition", "communication", "emotion",
    "memory", "ethics", "relationship", "autonomy",
}

# Top-level keys that are NOT chromosomes
META_KEYS = {"axiom", "name", "author", "substrate", "description", "parent", "when", "instincts"}


def parse_axiom(source: str | Path) -> AxiomSpec:
    """
    Parse a .axiom file (YAML) into an AxiomSpec.

    Args:
        source: file path as string or Path.

    Returns:
        Parsed AxiomSpec object.
    """
    path = Path(source)
    if not path.exists():
        raise FileNotFoundError(f"Axiom file not found: {path}")

    text = path.read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError(f"Expected YAML mapping at top level, got {type(raw).__name__}")

    return _build_spec(raw)


def _build_spec(raw: dict) -> AxiomSpec:
    """Build an AxiomSpec from parsed YAML dict."""
    spec = AxiomSpec(
        version=str(raw.get("axiom", "1.0")),
        name=str(raw.get("name", "")),
        author=str(raw.get("author", "")),
        substrate=str(raw.get("substrate", "any")),
        description=str(raw.get("description", "")),
        parent=str(raw.get("parent", "") or ""),
    )

    # Parse chromosomes — any top-level key with a 'genes' list or in KNOWN_CHROMOSOMES
    for key, val in raw.items():
        if key in META_KEYS:
            continue
        if isinstance(val, dict) and "genes" in val:
            spec.chromosomes[key] = _parse_chromosome(key, val)
        elif key in KNOWN_CHROMOSOMES and isinstance(val, dict):
            # Chromosome without genes (empty or description-only)
            spec.chromosomes[key] = _parse_chromosome(key, val)

    # Parse expression rules
    for rule_raw in raw.get("when", []) or []:
        spec.expression_rules.append(_parse_expression_rule(rule_raw))

    # Parse instincts
    for inst_raw in raw.get("instincts", []) or []:
        spec.instincts.append(_parse_instinct(inst_raw))

    return spec


def _parse_chromosome(name: str, raw: dict) -> Chromosome:
    chrom = Chromosome(
        name=name,
        locked=bool(raw.get("locked", False)),
        description=str(raw.get("description", "")),
    )
    for gene_raw in raw.get("genes", []) or []:
        chrom.genes.append(_parse_gene(gene_raw))
    return chrom


def _parse_gene(raw: dict) -> Gene:
    gene_type = GeneType.from_str(str(raw.get("type", "string")))

    # Parse value with type awareness
    value = raw.get("value")
    if gene_type == GeneType.FLOAT and value is not None:
        value = float(value)
    elif gene_type == GeneType.INT and value is not None:
        value = int(value)
    elif gene_type == GeneType.BOOL and value is not None:
        value = bool(value)

    # Parse range
    range_val = None
    if "range" in raw and raw["range"]:
        r = raw["range"]
        if isinstance(r, (list, tuple)) and len(r) == 2:
            range_val = (float(r[0]), float(r[1]))

    return Gene(
        name=str(raw.get("name", "")),
        type=gene_type,
        value=value,
        expression=str(raw.get("expression", "")),
        range=range_val,
        floor=float(raw["floor"]) if "floor" in raw and raw["floor"] is not None else None,
        ceiling=float(raw["ceiling"]) if "ceiling" in raw and raw["ceiling"] is not None else None,
        immutable=bool(raw.get("immutable", False)),
        options=raw.get("options"),
    )


def _parse_expression_rule(raw: dict) -> ExpressionRule:
    return ExpressionRule(
        condition=str(raw.get("if", "")),
        set_values=dict(raw.get("set", {})),
    )


def _parse_instinct(raw: dict) -> Instinct:
    return Instinct(
        trigger=str(raw.get("on", "")),
        action=str(raw.get("do", "")),
        description=str(raw.get("description", "")),
    )
