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
| Phase 1 | [#interview-phase-1](#interview-phase-1) |
| Phase 2 | [#interview-phase-2](#interview-phase-2) |

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
5. **Doc setup**: `docs/ADR.md`, [`docs/phase-1-visual-loop.md`](phase-1-visual-loop.md), and this file; we extend them each phase.

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

- Programmatic fidelity scoring (`compare_to_target`, Phase 2 in `IDEA.md`).
- Design-token panel and big UI rewrites beyond the starter (Phase 3+ in `IDEA.md`).
- Structured agent progress over SSE (Phase 4+ in `IDEA.md`; not Phase 1).
- Auto batch test scripts (Phase 5).

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

---

<a id="interview-phase-1"></a>

## Phase 1 — Visual loop (implemented)

> Maps to [`IDEA.md`](../IDEA.md) Phase 1 · Plan: [`phase-1-visual-loop.md`](phase-1-visual-loop.md)

### What we ship in this phase (product)

1. **Screenshots on disk**: `output/.shots/*.png` when the agent calls `capture_site` or `screenshot_output`.
2. **Two new MCP tools**: `capture_site(url)` (target page) and `screenshot_output()` (current `output/index.html`).
3. **Multimodal tool results**: PNG tiles plus a text block of extracted styles JSON go back to the model through the existing MCP path.
4. **Self-check instructions**: `SYSTEM_PROMPT` tells the agent to look first, build, screenshot output, compare, and iterate (soft cap in prose).
5. **Fidelity knob (3 profiles)**: UI → `fidelity_profile` on `/chat` → prompt + `compare_to_target(url, profile=...)`. Names: **more_editable / balanced / more_faithful**. See ADR [`0007`](ADR.md#adr-0007), [`0008`](ADR.md#adr-0008).
6. **`extract_assets(url)`** (more_faithful): mirror img/lazy-src/computed backgrounds/inline SVG/fonts to `output/assets/`; `asset_coverage` enforced only in more_faithful.

### Key tech choices

| Choice | Why | What we did not do | ADR |
|--------|-----|---------------------|-----|
| Playwright + tiled PNGs | Real pixels; tiles keep each image usable for vision | Single full-page screenshot only | [`0005`](ADR.md#adr-0005) |
| Image blocks in MCP tool `content` | Works with CLI transport; no custom `query()` multimodal wiring | Return only paths and hope the model opens files | [`0005`](ADR.md#adr-0005) |
| DOM-only fallback on nav errors | Agent still gets JSON + text outline | Fail hard with empty tool result | [`0005`](ADR.md#adr-0005) |
| `close_browser()` in `lifespan` | Avoid leaked Chromium on reload / shutdown | Leave browser running forever | [`0005`](ADR.md#adr-0005) |
| Fidelity knob: prompt + profile config | Generation and scoring stay aligned | Prompt-only or full 1:1 clone engine | [`0007`](ADR.md#adr-0007) |
| Asset mirror + asset_coverage | Real logos in more_faithful; gate only there | Hotlink CDN URLs | [`0008`](ADR.md#adr-0008) |

### Scope and boundaries

**We chose to do:**

- Headless capture, style extraction, and prompt-driven self-check loop.
- Persist the plan in-repo as [`phase-1-visual-loop.md`](phase-1-visual-loop.md).

**We chose not to do in this phase:**

- Programmatic fidelity scores / `compare_to_target` (Phase 2 in `IDEA.md`).
- Compare UI with per-axis charts (Phase 4 in `IDEA.md`).
- Dedicated SSE timeline for capture steps (still stderr + chat text).

### Likely follow-up questions

#### Q1: Where do screenshots go?

**Answer:** Under `output/.shots/` (gitignored with `output/`). Filenames include host slug and timestamp.

#### Q2: How do images reach the model?

**Answer:** The MCP tool handler returns `content` blocks with `type: image` and base64 PNG data. The SDK maps that to `ImageContent` for the Claude CLI.

#### Q3: What if the site never reaches `networkidle`?

**Answer:** Navigation uses `domcontentloaded` + a short wait (not `networkidle`), so heavy-JS sites do not hang. On failure we try DOM-only extraction.

#### Q4: Why is structure score low on some sites but visual is fine?

**Answer:** Structure compares DOM skeletons. Many marketing sites use div-heavy DOM; we use semantic HTML on purpose. Pick **more_editable** or **balanced** — structure is informational or zero-weight; fix content/layout/visual instead.

#### Q5: What does the fidelity knob do?

**Answer:** Three profiles (**more_editable / balanced / more_faithful**) change **both** how the agent writes HTML (prompt) and how `compare_to_target` weights axes (config). Default **balanced**.

#### Q6: When does asset_coverage matter?

**Answer:** Only in **more_faithful**. Agent calls `extract_assets(url)`, uses `/assets/...` paths in HTML, and compare enforces ≥75% role asset coverage. Other modes show assets as informational only.

### How we verify

- `pip install -r requirements.txt` includes `playwright==1.60.0`; `python -m playwright install chromium` has been run once on the machine.
- Paste a URL in the app; confirm new files under `output/.shots/` after a run.
- Agent follows the prompt order: `capture_site` before a full `write_html` rewrite when given a new URL.
- `screenshot_output()` returns images when `output/index.html` exists.

---

<a id="interview-phase-2"></a>

## Phase 2 — Fidelity verification (implemented)

> Maps to [`IDEA.md`](../IDEA.md) Phase 2 · Plan: [`phase-2-fidelity.md`](phase-2-fidelity.md)

### What we ship in this phase (product)

1. **`compare_to_target(url)`** — JSON fidelity report with content / structure / layout / visual scores, weighted total, verdict, gate failures, and ranked `worst_sections`.
2. **Two-layer thresholds** — per-axis hard gates plus normalized weighted pass/warn/fail; tunable in `data/fidelity.json`.
3. **Diff heatmap** — optional PNG under `output/.shots/` returned with the tool result.
4. **Batch + verify scripts** — `scripts/fidelity_batch.py` (table + `--calibrate`), `scripts/verify_phase2.py`.

### Key tech choices

| Choice | Why | What we did not do | ADR |
|--------|-----|---------------------|-----|
| Four axes (not visual-only) | Catches missing copy/sections pixels miss | Single SSIM number | [`0006`](ADR.md#adr-0006) |
| Pure `compare.py` | Unit-testable without browser | Mix metrics into `browser.py` | [`0006`](ADR.md#adr-0006) |
| Local numpy SSIM + pHash | Light deps | scikit-image | [`0006`](ADR.md#adr-0006) |
| Hard gates + normalized total | Prevents false pass | One global threshold | [`0006`](ADR.md#adr-0006) |
| Target cache per URL | Avoid re-fetching target each compare round | Re-capture every call | [`0006`](ADR.md#adr-0006) |

### Scope and boundaries

**We chose to do:**

- Programmatic scoring and prompt-driven fix loop using `worst_sections`.
- Calibration hook via batch `--calibrate`.

**We chose not to do in this phase:**

- Compare UI with charts (Phase 4 in `IDEA.md`).
- Design tokens (Phase 3).
- Full agent batch generation per benchmark (Phase 5).

### Likely follow-up questions

#### Q1: Why two threshold layers?

**Answer:** Raw scores live on different scales. Hard gates catch cheap correctness bugs (missing footer). The weighted total ranks overall quality after normalizing each axis to its calibrated band.

#### Q2: How do I tune thresholds?

**Answer:** Edit `data/fidelity.json` or run `python scripts/fidelity_batch.py output/index.html --calibrate` and paste the suggested `bands` / `thresholds`.

#### Q3: What if compare fails hard gates but looks fine?

**Answer:** The agent must fix named sections (e.g. restore footer text). After max iterations it accepts the best version and lists remaining gaps — it does not fake a pass.

### How we verify

- `python scripts/verify_phase2.py` — footer regression, heading-only drop, deterministic visual.
- `compare_to_target(url)` returns four axes + non-empty `worst_sections` on a real run.
- Self-compare of `output/index.html` yields `verdict: pass`, `total: 1.0`.
