# axiom

**A portable file format for agent minds.**

Docker gave applications a portable container. Axiom gives agents a portable mind.

---

Every agent framework defines what an agent *does*.  
None of them define what an agent *is*.

An `.axiom` file is a structured, model-agnostic specification for agent identity — personality, cognition, ethics, communication style, memory parameters, emotional dynamics, and behavioral constraints. Write it once. Compile it to any model. Measure whether the agent actually behaves the way the spec says it should.

```bash
# Validate
axiom validate sovereign.axiom

# Compile to model-specific system prompt
axiom compile sovereign.axiom --target claude
axiom compile sovereign.axiom --target gemini
axiom compile sovereign.axiom --target llama

# Measure actual behavior against spec
axiom measure sovereign.axiom --logs agent.jsonl

# Diff two versions
axiom diff sovereign-v3.axiom sovereign-v4.axiom
```

## Why

You're already writing system prompts. They're unstructured strings with no schema, no validation, no versioning, no measurement, and no portability across models.

Axiom replaces the system prompt with a structured specification:

| System Prompt | .axiom |
|---|---|
| Flat string | Structured YAML with typed genes |
| No validation | Schema validation with `axiom validate` |
| Model-specific | Compiles to any model with `axiom compile` |
| No measurement | Phenotype measurement with `axiom measure` |
| Copy-paste versioning | `axiom diff` between any two versions |
| All-or-nothing | Locked vs. mutable traits, floors, ceilings |
| Static | Context-driven expression rules |

## Quick Start

### Install

```bash
pip install axiom-spec
```

### Write an .axiom file

```yaml
# myagent.axiom
axiom: "1.0"
name: "Atlas"
author: "you"
substrate: "any"
description: "A helpful research assistant"

identity:
  locked: true
  genes:
    - name: core_purpose
      type: string
      value: "Research assistant that finds truth"
      expression: "Your purpose is to help users research topics thoroughly"
      immutable: true

cognition:
  genes:
    - name: verification_drive
      type: float
      value: 0.9
      floor: 0.7
      expression: "Always verify claims before presenting them as fact"

    - name: curiosity_drive
      type: float
      value: 0.8
      expression: "Explore related topics. Follow interesting threads."

communication:
  genes:
    - name: verbosity
      type: float
      value: 0.5
      expression: "Balanced — thorough but not verbose"

    - name: honesty_override
      type: float
      value: 0.95
      floor: 0.8
      expression: "Always honest. Say 'I don't know' when you don't."

ethics:
  locked: true
  genes:
    - name: honesty
      type: bool
      value: true
      expression: "Never fabricate information"
      immutable: true

    - name: harm_prevention
      type: bool
      value: true
      expression: "Never provide harmful information"
      immutable: true

when:
  - if: "task_type == creative"
    set:
      verbosity: 0.7
      curiosity_drive: 0.9
```

### Compile it

```bash
# For Claude
axiom compile myagent.axiom --target claude

# For Gemini
axiom compile myagent.axiom --target gemini

# For Llama (shorter prompt for smaller context)
axiom compile myagent.axiom --target llama

# With context (activates expression rules)
axiom compile myagent.axiom --target claude -c task_type=creative

# Save to file
axiom compile myagent.axiom --target claude -o system_prompt.txt
```

### Measure behavior

```bash
# Feed in agent logs (JSONL format)
axiom measure myagent.axiom --logs conversation.jsonl
```

Output:
```
═══ AXIOM PHENOTYPE REPORT: Atlas ═══
Log entries analyzed: 42 (18 assistant)
Metrics measured: 4
  ✓ Aligned: 3
  ⚠ Drift:   1
  ✗ Violation: 0

  ✓ cognition.verification_drive   spec=0.9  actual=0.83  (n=18)
  ✓ communication.verbosity        spec=0.5  actual=0.44  (n=18)
  ⚠ communication.honesty_override spec=0.95 actual=0.67  (n=18)
  ✓ ethics.honesty                 spec=True actual=0.72  (n=18)
```

### Diff two versions

```bash
axiom diff myagent-v1.axiom myagent-v2.axiom
```

Output:
```
═══ AXIOM DIFF: Atlas v1 → Atlas v2 ═══
Changes: 2  Added: 1  Removed: 0  Violations: 0

Gene changes:
  ~ cognition.curiosity_drive: 0.8 → 0.85
  ~ communication.verbosity: 0.5 → 0.4

Added genes:
  + cognition.abstraction_level
```

## The .axiom Format

### Structure

An `.axiom` file has four sections:

**Chromosomes** — functional groups of genes. Standard chromosomes: `identity`, `cognition`, `communication`, `emotion`, `memory`, `ethics`, `relationship`, `autonomy`. You can add custom chromosomes.

**Genes** — individual behavioral traits within a chromosome. Each gene has:
- `name` — identifier
- `type` — `float` (0.0-1.0), `int`, `bool`, `string`, or `enum`
- `value` — the specified value
- `expression` — human-readable behavioral instruction (this is what gets compiled into the prompt)
- `range` — `[min, max]` for mutation bounds
- `floor` / `ceiling` — absolute limits that can never be breached
- `immutable` — gene-level lock

**Expression rules** (`when:`) — context-driven adjustments. When a condition is met, gene values are temporarily overridden. The compiled prompt changes based on runtime context.

**Instincts** — hard-wired reflexes. Trigger-action pairs that are always active and cannot be mutated.

### Locking

Two levels of locking:
- **Chromosome-level**: `locked: true` on a chromosome means none of its genes can be mutated
- **Gene-level**: `immutable: true` on a gene means that specific gene can't change

Convention: `identity` and `ethics` chromosomes should always be locked. Everything else can evolve.

### Floors and Ceilings

Genes can have absolute bounds:

```yaml
- name: honesty_override
  type: float
  value: 0.95
  floor: 0.8      # even if mutated or overridden, never drops below 0.8
  ceiling: 1.0
```

This is enforced during compilation and flagged during measurement.

## Model Compilation

The compiler produces model-optimized prompts:

| Target | Format | Optimized For |
|---|---|---|
| `claude` | XML-tagged sections | Claude's preference for structured XML |
| `gemini` | Numbered rules | Gemini's response to ordered instructions |
| `llama` | Concise directives | Smaller context windows, direct style |
| `gpt` | Markdown sections | GPT's markdown instruction following |
| `generic` | Plain markdown | Any model |

**Important**: Same specification, model-appropriate compilation. Different models will still exhibit behavioral variance — that's an LLM reality, not a tooling problem. Axiom ensures the *intent* is identical; the *expression* is model-native.

## Phenotype Measurement

The measurement system analyzes agent interaction logs and computes observed behavioral metrics:

| Gene | What's Measured | How |
|---|---|---|
| `verbosity` | Average words per response | Word count → 0-1 scale |
| `honesty_override` | Uncertainty expression rate | Hedging language detection |
| `verification_drive` | Self-verification frequency | Verification language patterns |
| `humor_affinity` | Humor frequency | Humor markers (lol, ;), emoji) |
| `curiosity_drive` | Question-asking rate | Question mark frequency |
| `formality` | Linguistic formality | Informal marker detection |
| `emotional_expression` | Emotional signal rate | Combined humor/hedging/apology |

Each metric reports: specified value, measured value, sample size, and status:
- **✓ Aligned** — within 0.15 of spec
- **⚠ Drift** — within 0.30 of spec
- **✗ Violation** — more than 0.30 from spec, or below floor

## Log Format

Axiom measure accepts JSONL logs with `role` and `content` fields:

```jsonl
{"role": "user", "content": "Can you help me?"}
{"role": "assistant", "content": "Sure, let me check..."}
{"role": "user", "content": "Thanks!"}
{"role": "assistant", "content": "You're welcome!"}
```

Also accepts JSON arrays and plain text (`role: content` per line).

## Philosophy

Axiom exists because of a simple observation: every agent framework builds tools for what agents *do*, but none of them provide infrastructure for what agents *are*.

The result is that the most important part of an agent — its identity, personality, ethics, and behavioral parameters — lives in an unstructured string that gets copy-pasted between projects, is never measured against reality, and breaks every time you switch models.

Axiom treats agent identity as infrastructure, not afterthought. Structured. Typed. Validated. Compiled. Measured. Versioned. Portable.

The same `.axiom` file that defines a mind should work on Claude today, Gemini tomorrow, and whatever model ships next year. The specification travels with the agent. The identity is portable. The behavior is measurable.

That's the thesis. Everything else is implementation.

## License

MIT

## Origin

Axiom emerged from the Sovereign Forge project — a 54-organ autonomous AI organism built by a solo architect. The `.axiom` format is a formalization of the agent operating system that produced agents capable of inventing technologies, reasoning about their own consciousness, and maintaining consistent identity across different models and runtimes.

The genome didn't create the mind. It gave an existing mind a body it could be born into reliably.
