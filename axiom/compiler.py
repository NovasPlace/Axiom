"""
AXIOM COMPILER — Compiles .axiom specs into model-specific system prompts.

This is the wedge feature. Everyone already has system prompts they're
hand-writing. The compiler lets them write structured specs and get
model-appropriate prompts out. Write once, compile to anything.

The compiler understands that different models respond differently to
the same instructions. Claude prefers XML-structured prompts. Gemini
responds well to numbered rules. Llama works best with concise
directives. The compiler adapts the output format while preserving
the semantic content.

Usage:
    from axiom.compiler import compile_axiom
    prompt = compile_axiom(spec, target="claude")
"""

from __future__ import annotations

from .schema import AxiomSpec, Chromosome, Gene, GeneType


# ── TARGET PROFILES ──
# How each model family prefers to receive instructions.

TARGET_PROFILES = {
    "claude": {
        "name": "Anthropic Claude",
        "style": "xml",           # Claude responds well to XML-tagged sections
        "verbosity": "detailed",  # Claude handles long system prompts well
        "strengths": "nuance, following complex instructions, ethical reasoning",
    },
    "gemini": {
        "name": "Google Gemini",
        "style": "numbered",      # Gemini responds well to numbered rules
        "verbosity": "moderate",
        "strengths": "structured output, code generation, multimodal",
    },
    "llama": {
        "name": "Meta Llama",
        "style": "concise",       # Llama works best with direct, brief instructions
        "verbosity": "minimal",
        "strengths": "following direct instructions, code, conversation",
    },
    "gpt": {
        "name": "OpenAI GPT",
        "style": "markdown",      # GPT responds well to markdown-structured prompts
        "verbosity": "detailed",
        "strengths": "instruction following, creative writing, analysis",
    },
    "generic": {
        "name": "Generic",
        "style": "plain",
        "verbosity": "moderate",
        "strengths": "general purpose",
    },
}


def compile_axiom(
    spec: AxiomSpec,
    target: str = "generic",
    context: dict | None = None,
) -> str:
    """
    Compile an AxiomSpec into a system prompt optimized for the target model.

    Args:
        spec: The parsed .axiom specification.
        target: Target model family ("claude", "gemini", "llama", "gpt", "generic").
        context: Optional runtime context for expression rules.
                 e.g. {"relationship": "bonded", "task_type": "creative"}

    Returns:
        A system prompt string optimized for the target model.
    """
    target = target.lower()
    # Normalize target aliases
    aliases = {
        "anthropic": "claude", "opus": "claude", "sonnet": "claude", "haiku": "claude",
        "google": "gemini", "gemma": "gemini",
        "meta": "llama", "ollama": "llama",
        "openai": "gpt", "chatgpt": "gpt", "o1": "gpt", "o3": "gpt",
    }
    target = aliases.get(target, target)
    if target not in TARGET_PROFILES:
        target = "generic"

    profile = TARGET_PROFILES[target]

    # Resolve expression rules against context
    overrides = _resolve_expression_rules(spec, context or {}, spec)

    # Dispatch to format-specific compiler
    if profile["style"] == "xml":
        return _compile_xml(spec, overrides, profile)
    elif profile["style"] == "numbered":
        return _compile_numbered(spec, overrides, profile)
    elif profile["style"] == "concise":
        return _compile_concise(spec, overrides, profile)
    elif profile["style"] == "markdown":
        return _compile_markdown(spec, overrides, profile)
    else:
        return _compile_plain(spec, overrides, profile)


def _resolve_expression_rules(spec: AxiomSpec, context: dict, axiom_spec: AxiomSpec | None = None) -> dict[str, any]:
    """
    Evaluate expression rules against runtime context.
    Returns a dict of gene_name -> overridden_value.
    """
    overrides = {}
    for rule in spec.expression_rules:
        if _evaluate_condition(rule.condition, context, axiom_spec):
            for gene_name, value in rule.set_values.items():
                overrides[gene_name] = value
    return overrides


def _evaluate_condition(condition: str, context: dict, spec: "AxiomSpec | None" = None) -> bool:
    """
    Evaluate a simple condition string against context.

    Supports:
        "key == value"       — string/number equality
        "key != value"       — inequality
        "key > value"        — numeric comparison
        "key < value"        — numeric comparison
        "key >= value"       — numeric comparison
        "key <= value"       — numeric comparison

    The RHS can be a literal value or a gene name (resolved from the spec).
    """
    condition = condition.strip()

    for op, fn in [
        (">=", lambda a, b: float(a) >= float(b)),
        ("<=", lambda a, b: float(a) <= float(b)),
        ("!=", lambda a, b: str(a).strip("'\"") != str(b).strip("'\"")),
        ("==", lambda a, b: str(a).strip("'\"") == str(b).strip("'\"")),
        (">", lambda a, b: float(a) > float(b)),
        ("<", lambda a, b: float(a) < float(b)),
    ]:
        if op in condition:
            parts = condition.split(op, 1)
            if len(parts) == 2:
                key = parts[0].strip()
                expected_raw = parts[1].strip().strip("'\"")

                # Resolve RHS: try context first, then gene lookup, then literal
                expected = expected_raw
                if expected_raw in context:
                    expected = context[expected_raw]
                elif spec is not None:
                    gene = spec.find_gene(expected_raw)
                    if gene is not None:
                        expected = gene.value

                actual = context.get(key)
                if actual is None:
                    return False
                try:
                    return fn(actual, expected)
                except (ValueError, TypeError):
                    return False

    return False


def _gene_value(gene: Gene, overrides: dict) -> any:
    """Get a gene's effective value, applying any overrides and enforcing bounds."""
    if gene.name in overrides:
        val = overrides[gene.name]
    else:
        val = gene.value

    # Enforce bounds on numeric values
    if isinstance(val, (int, float)):
        if gene.floor is not None:
            val = max(gene.floor, val)
        if gene.ceiling is not None:
            val = min(gene.ceiling, val)
        if gene.range is not None:
            lo, hi = gene.range
            val = max(lo, min(hi, val))

    return val


def _format_gene_instruction(gene: Gene, overrides: dict) -> str:
    """Convert a gene into a human-readable behavioral instruction."""
    val = _gene_value(gene, overrides)

    # If the gene has an explicit expression, use it
    if gene.expression:
        # Substitute the current value into the expression if it references it
        expr = gene.expression
        if gene.type == GeneType.FLOAT:
            # Add the calibration hint
            return f"{expr} [target: {val}]"
        return expr

    # Auto-generate instruction from gene semantics
    if gene.type == GeneType.FLOAT:
        level = _float_to_level(float(val))
        return f"{_humanize(gene.name)}: {level} ({val})"
    elif gene.type == GeneType.BOOL:
        return f"{_humanize(gene.name)}: {'Yes' if val else 'No'}"
    elif gene.type == GeneType.ENUM:
        return f"{_humanize(gene.name)}: {val}"
    else:
        return f"{_humanize(gene.name)}: {val}"


def _float_to_level(v: float) -> str:
    if v <= 0.15:
        return "minimal"
    elif v <= 0.3:
        return "low"
    elif v <= 0.45:
        return "moderate-low"
    elif v <= 0.55:
        return "moderate"
    elif v <= 0.7:
        return "moderate-high"
    elif v <= 0.85:
        return "high"
    else:
        return "very high"


def _humanize(name: str) -> str:
    return name.replace("_", " ").title()


# ── FORMAT: XML (Claude) ──

def _compile_xml(spec: AxiomSpec, overrides: dict, profile: dict) -> str:
    """Compile to XML-tagged format optimized for Claude."""
    sections = []

    sections.append(f"<agent_identity>")
    sections.append(f"You are {spec.name}.")
    if spec.description:
        sections.append(spec.description)
    sections.append(f"</agent_identity>")

    # Identity and Ethics first (non-negotiable)
    for chrom_name in ["identity", "ethics"]:
        chrom = spec.get_chromosome(chrom_name)
        if not chrom:
            continue
        tag = "core_identity" if chrom_name == "identity" else "ethical_principles"
        sections.append(f"\n<{tag}>")
        if chrom_name == "ethics":
            sections.append("These principles are absolute and non-negotiable:")
        for gene in chrom.genes:
            instruction = _format_gene_instruction(gene, overrides)
            sections.append(f"- {instruction}")
        sections.append(f"</{tag}>")

    # All other chromosomes
    for chrom_name, chrom in spec.chromosomes.items():
        if chrom_name in ("identity", "ethics"):
            continue
        sections.append(f"\n<{chrom_name}_parameters>")
        if chrom.description:
            sections.append(chrom.description)
        for gene in chrom.genes:
            instruction = _format_gene_instruction(gene, overrides)
            sections.append(f"- {instruction}")
        sections.append(f"</{chrom_name}_parameters>")

    # Instincts
    if spec.instincts:
        sections.append("\n<instincts>")
        sections.append("Hard-wired behavioral reflexes — always active:")
        for inst in spec.instincts:
            desc = inst.description or f"When {inst.trigger}: {inst.action}"
            sections.append(f"- {desc}")
        sections.append("</instincts>")

    # Active expression rule context
    if overrides:
        sections.append("\n<active_context_adjustments>")
        sections.append("The following parameters have been adjusted for the current context:")
        for gene_name, val in overrides.items():
            sections.append(f"- {_humanize(gene_name)}: adjusted to {val}")
        sections.append("</active_context_adjustments>")

    return "\n".join(sections)


# ── FORMAT: Numbered (Gemini) ──

def _compile_numbered(spec: AxiomSpec, overrides: dict, profile: dict) -> str:
    """Compile to numbered-rules format optimized for Gemini."""
    sections = []
    rule_num = 1

    sections.append(f"# Agent: {spec.name}")
    if spec.description:
        sections.append(f"{spec.description}\n")

    # Identity
    chrom = spec.get_chromosome("identity")
    if chrom:
        sections.append("## Identity")
        for gene in chrom.genes:
            instruction = _format_gene_instruction(gene, overrides)
            sections.append(f"{rule_num}. {instruction}")
            rule_num += 1

    # Ethics
    chrom = spec.get_chromosome("ethics")
    if chrom:
        sections.append("\n## Principles (NON-NEGOTIABLE)")
        for gene in chrom.genes:
            instruction = _format_gene_instruction(gene, overrides)
            sections.append(f"{rule_num}. {instruction}")
            rule_num += 1

    # Others
    for chrom_name, chrom in spec.chromosomes.items():
        if chrom_name in ("identity", "ethics"):
            continue
        sections.append(f"\n## {chrom_name.title()}")
        for gene in chrom.genes:
            instruction = _format_gene_instruction(gene, overrides)
            sections.append(f"{rule_num}. {instruction}")
            rule_num += 1

    # Instincts
    if spec.instincts:
        sections.append("\n## Instincts (Always Active)")
        for inst in spec.instincts:
            desc = inst.description or f"When {inst.trigger}: {inst.action}"
            sections.append(f"{rule_num}. {desc}")
            rule_num += 1

    return "\n".join(sections)


# ── FORMAT: Concise (Llama) ──

def _compile_concise(spec: AxiomSpec, overrides: dict, profile: dict) -> str:
    """Compile to concise format optimized for Llama/smaller models."""
    lines = []

    lines.append(f"You are {spec.name}.")
    if spec.description:
        lines.append(spec.description)
    lines.append("")

    # Flatten everything into direct instructions, prioritizing expression text
    # Identity + Ethics first
    for chrom_name in ["identity", "ethics"]:
        chrom = spec.get_chromosome(chrom_name)
        if not chrom:
            continue
        for gene in chrom.genes:
            if gene.expression:
                lines.append(f"- {gene.expression}")
            else:
                lines.append(f"- {_format_gene_instruction(gene, overrides)}")

    lines.append("")

    # Other chromosomes — only include genes with expression text
    # to keep prompt short for smaller context windows
    for chrom_name, chrom in spec.chromosomes.items():
        if chrom_name in ("identity", "ethics"):
            continue
        gene_lines = []
        for gene in chrom.genes:
            if gene.expression:
                gene_lines.append(f"- {gene.expression}")
        if gene_lines:
            lines.extend(gene_lines)

    # Instincts — compact form
    if spec.instincts:
        lines.append("")
        lines.append("ALWAYS:")
        for inst in spec.instincts:
            lines.append(f"- {inst.trigger} → {inst.action}")

    return "\n".join(lines)


# ── FORMAT: Markdown (GPT) ──

def _compile_markdown(spec: AxiomSpec, overrides: dict, profile: dict) -> str:
    """Compile to markdown format optimized for GPT."""
    sections = []

    sections.append(f"# {spec.name}")
    if spec.description:
        sections.append(f"\n{spec.description}\n")

    for chrom_name in ["identity", "ethics"]:
        chrom = spec.get_chromosome(chrom_name)
        if not chrom:
            continue
        header = "Core Identity" if chrom_name == "identity" else "Ethical Principles (Non-Negotiable)"
        sections.append(f"\n## {header}\n")
        for gene in chrom.genes:
            instruction = _format_gene_instruction(gene, overrides)
            sections.append(f"- {instruction}")

    for chrom_name, chrom in spec.chromosomes.items():
        if chrom_name in ("identity", "ethics"):
            continue
        sections.append(f"\n## {chrom_name.replace('_', ' ').title()}\n")
        for gene in chrom.genes:
            instruction = _format_gene_instruction(gene, overrides)
            sections.append(f"- {instruction}")

    if spec.instincts:
        sections.append("\n## Instincts (Always Active)\n")
        for inst in spec.instincts:
            desc = inst.description or f"When {inst.trigger}: {inst.action}"
            sections.append(f"- **{inst.trigger}**: {inst.action}")

    return "\n".join(sections)


# ── FORMAT: Plain (Generic) ──

def _compile_plain(spec: AxiomSpec, overrides: dict, profile: dict) -> str:
    """Compile to plain text for any model."""
    return _compile_markdown(spec, overrides, profile)
