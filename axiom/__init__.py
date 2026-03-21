"""
axiom — A portable file format for agent minds.

Docker gave applications a portable container.
Axiom gives agents a portable mind.
"""

__version__ = "0.1.0"

from .schema import AxiomSpec, Chromosome, Gene, GeneType, ExpressionRule, Instinct, parse_axiom
from .compiler import compile_axiom, TARGET_PROFILES
from .diff import diff_axiom

__all__ = [
    "AxiomSpec",
    "Chromosome",
    "Gene",
    "GeneType",
    "ExpressionRule",
    "Instinct",
    "parse_axiom",
    "compile_axiom",
    "TARGET_PROFILES",
    "diff_axiom",
]
