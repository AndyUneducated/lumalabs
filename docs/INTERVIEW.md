# Interview prep notes

All per-phase “what we ship / why / how we verify” notes live in **this one file**. Use **Simple English**, same as `README.md`, `IDEA.md`, `video.md`, and the rest of `docs/`.

**After each Phase** (see [`IDEA.md`](../IDEA.md), section 12):

1. Append a new `## Phase N` block using the [template](#interview-template). Add `<a id="interview-phase-N"></a>` right above the heading.
2. In `IDEA.md`, in that Phase subsection, link here: `docs/INTERVIEW.md#interview-phase-N`.
3. Log big tech choices in [`ADR.md`](ADR.md). In the phase’s “Key tech choices” table, link ADR rows to `ADR.md#adr-NNNN`.

---

## Contents

| Section | Anchor |
|---------|--------|
| Template (copy for a new phase) | [#interview-template](#interview-template) |
| Phase 0 | [#interview-phase-0](#interview-phase-0) |

---

<a id="interview-template"></a>

## Template (for new phases)

Use this shape when you add **Phase N**. Put the anchor line immediately before `## Phase N`.

> Maps to [`IDEA.md`](../IDEA.md) Phase N

### What we ship in this phase (product)

What can a user or interviewer see? List 3–5 bullets.

### Key tech choices

| Choice | Why | What we did not do | ADR |
|--------|-----|---------------------|-----|
| | | | [`NNNN`](ADR.md#adr-NNNN) (add matching section + `adr-NNNN` anchor in `ADR.md`) |

### Scope and boundaries

**We chose to do:**

**We chose not to do in this phase:**

### Likely follow-up questions

#### Q1: …

**Answer:**

#### Q2: …

**Answer:**

### How we verify

How do we prove this phase’s definition of done?

---

<a id="interview-phase-0"></a>

## Phase 0 — Product scope and tech choices

> Maps to [`IDEA.md`](../IDEA.md) Phase 0

### What we ship in this phase (product)

1. **Repro env**: `requirements.txt` pins main deps so `pip install -r requirements.txt` gives the same result on a new machine.
2. **Model config**: Switch `sonnet` / `haiku` / etc. with `AGENT_MODEL` (default `opus`) without code edits.
3. **Startup self-check**: On boot, the terminal prints the active model, Claude CLI transport source, and whether `.env` exists (no secret leak).
4. **Benchmark URL set**: `data/benchmarks.json` lists 4 fixed sites for later vision work and regression.
5. **Doc setup**: `docs/ADR.md` + this file; we extend them each phase.

### Key tech choices

| Choice | Why | What we did not do | ADR |
|--------|-----|---------------------|-----|
| Keep Claude Agent SDK + CLI | Matches starter; MCP tools wired; CLI login is enough to run | Raw Anthropic API, Ollama | [`0001`](ADR.md#adr-0001) |
| `AGENT_MODEL` env var, default opus | Easy cost vs quality switch; fits close copy goal | Hard-coded model, CLI-only flag | [`0002`](ADR.md#adr-0002) |
| stderr self-check in lifespan | Fixes “why no `.env` still works”; zero secret leak | `/health` exposing config | [`0003`](ADR.md#adr-0003) |
| `data/benchmarks.json` | Matches `data/` layout; easy for scripts | Hard-coded URLs in code | [`0004`](ADR.md#adr-0004) |

### Scope and boundaries

**We chose to do:**

- Small baseline hardening before Phase 1 (vision loop).
- ADR + interview notes in one place to show engineering judgment.

**We chose not to do in this phase:**

- Playwright screenshots, design-token tools, big UI rewrites.
- Structured agent progress over SSE (Phase 1).
- Auto batch test scripts (Phase 4).

### Likely follow-up questions

#### Q1: Why does the model work with no `.env`?

**Answer:** Auth uses **Claude Code CLI login**, not `ANTHROPIC_API_KEY` in this project. The self-check prints the transport path; `.env` only shows if the file exists, not the key.

#### Q2: Why default `opus` instead of `haiku`?

**Answer:** The README wants output **very close** to the target site. `opus` fits that. For dev cost, use `AGENT_MODEL=haiku`.

#### Q3: Why these four benchmark sites?

**Answer:** They mix complexity and style (Stripe SaaS, Linear minimal, Vercel dev marketing, Resend YC-style). That helps later similarity and regression tests, not just one site.

#### Q4: Why pin `requirements.txt` versions?

**Answer:** The take-home must reproduce in review. `>=` can install different minor versions over time and drift SDK/CLI behavior.

### How we verify

- `pip install -r requirements.txt` succeeds.
- Set `AGENT_MODEL=sonnet`, restart; terminal shows `[startup] AGENT_MODEL: sonnet`.
- Boot logs include transport and `.env file: present|not found`, no keys.
- `python3 -c "import json; json.load(open('data/benchmarks.json'))"` loads 4 entries.
- S0.1: paste a benchmark URL, get `output/index.html` and see it in preview.
