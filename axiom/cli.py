#!/usr/bin/env python3
"""
AXIOM CLI — The command-line interface for the Axiom agent specification format.

Commands:
    axiom validate   <file.axiom>              — Validate an axiom file
    axiom compile    <file.axiom> --target X   — Compile to model-specific prompt
    axiom measure    <file.axiom> --logs X     — Measure phenotype from logs
    axiom measure    <file.axiom> --cortex X   — Measure from CortexDB event ledger
    axiom diff       <a.axiom> <b.axiom>       — Diff two axiom files
    axiom crossover  <a.axiom> <b.axiom>       — Breed two axiom specs
    axiom info       <file.axiom>              — Show summary of an axiom file
"""

import argparse
import sys
from pathlib import Path

from .schema import parse_axiom
from .compiler import compile_axiom, TARGET_PROFILES
from .measure import measure_phenotype, parse_logs
from .diff import diff_axiom


def cmd_validate(args):
    """Validate an .axiom file against the schema."""
    try:
        spec = parse_axiom(args.file)
    except Exception as e:
        print(f"✗ Parse error: {e}", file=sys.stderr)
        return 1

    errors = spec.validate()
    if errors:
        print(f"✗ {args.file}: {len(errors)} validation error(s)\n")
        for err in errors:
            print(f"  • {err}")
        return 1

    gene_count = sum(len(c.genes) for c in spec.chromosomes.values())
    locked_count = sum(1 for c in spec.chromosomes.values() if c.locked)

    print(f"✓ {args.file}: valid")
    print(f"  Name: {spec.name}")
    print(f"  Chromosomes: {len(spec.chromosomes)} ({locked_count} locked)")
    print(f"  Genes: {gene_count}")
    print(f"  Expression rules: {len(spec.expression_rules)}")
    print(f"  Instincts: {len(spec.instincts)}")
    return 0


def cmd_compile(args):
    """Compile an .axiom file to a model-specific system prompt."""
    try:
        spec = parse_axiom(args.file)
    except Exception as e:
        print(f"✗ Parse error: {e}", file=sys.stderr)
        return 1

    errors = spec.validate()
    if errors:
        print(f"✗ Validation failed with {len(errors)} error(s):", file=sys.stderr)
        for err in errors:
            print(f"  • {err}", file=sys.stderr)
        return 1

    # Parse context if provided
    context = {}
    if args.context:
        for pair in args.context:
            key, _, val = pair.partition("=")
            # Try to parse as number
            try:
                val = float(val)
            except ValueError:
                pass
            context[key.strip()] = val

    prompt = compile_axiom(spec, target=args.target, context=context)

    if args.output:
        Path(args.output).write_text(prompt)
        print(f"✓ Compiled {args.file} → {args.output} (target: {args.target})")
        print(f"  Prompt length: {len(prompt)} chars, ~{len(prompt)//4} tokens")
    else:
        print(prompt)

    return 0


def cmd_measure(args):
    """Measure agent phenotype against axiom spec."""
    try:
        spec = parse_axiom(args.file)
    except Exception as e:
        print(f"✗ Parse error: {e}", file=sys.stderr)
        return 1

    try:
        if args.cortex:
            from .cortex_adapter import measure_from_ledger
            report = measure_from_ledger(spec, args.cortex)
        else:
            report = measure_phenotype(spec, args.logs)
    except Exception as e:
        print(f"✗ Measurement error: {e}", file=sys.stderr)
        return 1

    print(report.summary())
    return 0 if report.violation_count == 0 else 1


def cmd_crossover(args):
    """Breed two axiom files into a child."""
    try:
        spec_a = parse_axiom(args.file_a)
        spec_b = parse_axiom(args.file_b)
    except Exception as e:
        print(f"✗ Parse error: {e}", file=sys.stderr)
        return 1

    from .breed import crossover, axiom_to_yaml

    child, report = crossover(
        spec_a, spec_b,
        mutation_rate=args.mutation_rate,
        child_name=args.name,
        seed=args.seed,
    )

    print(report.summary())

    if args.output:
        yaml_text = axiom_to_yaml(child)
        Path(args.output).write_text(yaml_text)
        print(f"\n✓ Child written to {args.output}")
    else:
        print()
        print(axiom_to_yaml(child))

    return 0


def cmd_diff(args):
    """Diff two axiom files."""
    try:
        spec_a = parse_axiom(args.file_a)
        spec_b = parse_axiom(args.file_b)
    except Exception as e:
        print(f"✗ Parse error: {e}", file=sys.stderr)
        return 1

    report = diff_axiom(spec_a, spec_b)
    print(report.summary())
    return 0 if not report.violations else 1


def cmd_info(args):
    """Show summary information about an axiom file."""
    try:
        spec = parse_axiom(args.file)
    except Exception as e:
        print(f"✗ Parse error: {e}", file=sys.stderr)
        return 1

    print(f"═══ AXIOM: {spec.name} ═══")
    if spec.description:
        print(f"{spec.description}")
    print(f"Author: {spec.author or '(not set)'}")
    print(f"Version: {spec.version}")
    print(f"Substrate: {spec.substrate}")
    if spec.parent:
        print(f"Parent: {spec.parent}")
    print()

    for chrom_name, chrom in spec.chromosomes.items():
        lock_icon = "🔒" if chrom.locked else "  "
        print(f"{lock_icon} {chrom_name} ({len(chrom.genes)} genes)")
        for gene in chrom.genes:
            floor_str = f" floor={gene.floor}" if gene.floor is not None else ""
            lock_str = " [immutable]" if gene.immutable else ""
            print(f"     {gene.name}: {gene.value}{floor_str}{lock_str}")

    if spec.expression_rules:
        print(f"\nExpression rules: {len(spec.expression_rules)}")
        for rule in spec.expression_rules:
            overrides = ", ".join(f"{k}={v}" for k, v in rule.set_values.items())
            print(f"  when {rule.condition}: {overrides}")

    if spec.instincts:
        print(f"\nInstincts: {len(spec.instincts)}")
        for inst in spec.instincts:
            print(f"  {inst.trigger} → {inst.action}")

    return 0


def main():
    parser = argparse.ArgumentParser(
        prog="axiom",
        description="Axiom — A portable file format for agent minds.",
    )
    parser.add_argument("--version", action="version", version=f"axiom 0.1.0")
    sub = parser.add_subparsers(dest="command")

    # validate
    p_val = sub.add_parser("validate", help="Validate an .axiom file")
    p_val.add_argument("file", help="Path to .axiom file")
    p_val.set_defaults(func=cmd_validate)

    # compile
    p_comp = sub.add_parser("compile", help="Compile to model-specific prompt")
    p_comp.add_argument("file", help="Path to .axiom file")
    p_comp.add_argument("-t", "--target", default="generic",
                       choices=list(TARGET_PROFILES.keys()),
                       help="Target model (default: generic)")
    p_comp.add_argument("-o", "--output", help="Output file (default: stdout)")
    p_comp.add_argument("-c", "--context", nargs="*",
                       help="Context key=value pairs for expression rules")
    p_comp.set_defaults(func=cmd_compile)

    # measure
    p_meas = sub.add_parser("measure", help="Measure phenotype from logs")
    p_meas.add_argument("file", help="Path to .axiom file")
    logs_group = p_meas.add_mutually_exclusive_group(required=True)
    logs_group.add_argument("--logs", help="Path to log file (JSONL or JSON)")
    logs_group.add_argument("--cortex", help="Path to CortexDB event ledger (JSONL)")
    p_meas.set_defaults(func=cmd_measure)

    # crossover
    p_breed = sub.add_parser("crossover", help="Breed two axiom files")
    p_breed.add_argument("file_a", help="First parent .axiom file")
    p_breed.add_argument("file_b", help="Second parent .axiom file")
    p_breed.add_argument("-o", "--output", help="Output file for child (default: stdout)")
    p_breed.add_argument("-n", "--name", help="Name for the child agent")
    p_breed.add_argument("-m", "--mutation-rate", type=float, default=0.1,
                        help="Mutation rate for float genes (default: 0.1)")
    p_breed.add_argument("--seed", type=int, help="Random seed for reproducibility")
    p_breed.set_defaults(func=cmd_crossover)

    # diff
    p_diff = sub.add_parser("diff", help="Diff two axiom files")
    p_diff.add_argument("file_a", help="First .axiom file (before)")
    p_diff.add_argument("file_b", help="Second .axiom file (after)")
    p_diff.set_defaults(func=cmd_diff)

    # info
    p_info = sub.add_parser("info", help="Show axiom file summary")
    p_info.add_argument("file", help="Path to .axiom file")
    p_info.set_defaults(func=cmd_info)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 0

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
