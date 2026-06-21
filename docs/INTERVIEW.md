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
| Agent talking points (read this first) | [#agent-talking-points](#agent-talking-points) |
| Template (copy for a new phase) | [#interview-template](#interview-template) |
| Phase 0 | [#interview-phase-0](#interview-phase-0) |
| Phase 1 | [#interview-phase-1](#interview-phase-1) |
| Phase 2 | [#interview-phase-2](#interview-phase-2) |
| Phase 4 | [#interview-phase-4](#interview-phase-4) |
| Phase 5 | [#interview-phase-5](#interview-phase-5) |
| Phase 6 | [#interview-phase-6](#interview-phase-6) |

---

<a id="agent-talking-points"></a>

## Agent talking points (cross-phase summary)

The take-home says it cares most about the **agentic experience**: how the agent
reasons, what tools we give it, and how we shaped its behavior to get good
results **reliably**. This section is the one-page story to tell. Each line maps
to a phase below.

### One-line pitch

We turned a blind "write HTML and hope" agent into one that **looks at the target
with real eyes, builds, measures itself against the target, and fixes the named
worst parts** — all inside a fixed, capped loop with one fidelity knob that drives
both generation and scoring.

### The 10 tools (we gave the agent eyes + a ruler)

| Tool | What it gives the agent | Phase |
|------|-------------------------|-------|
| `capture_site(url)` | Pixel-level eyes: screenshot tiles + computed styles of the target | 1 |
| `screenshot_output()` | Sees its own output to self-check | 1 |
| `compare_to_target(url)` | A ruler: four-axis score (content/structure/layout/visual), verdict, ranked `worst_sections` | 2 |
| `extract_assets(url)` | Mirrors real logo/font/SVG/background; gated by `asset_coverage` | 1 (more_faithful) |
| `extract_design_tokens(url)` | Reads brand color/type/shape into canonical tokens | 3 |
| `read_design_tokens()` | Reads current `:root` tokens from output | 3 |
| `set_design_token(name, value)` | Re-brands by patching one CSS var, no full rewrite | 3 |
| `edit_section(selector, html)` | Local replace by `data-section`, not whole-file rewrite | 4 |
| `write_html` / `read_html` | Base write/read (from scaffold) | — |

### How we shaped behavior (this is the judgment part)

- **Fixed workflow, not free-for-all**: look → build → self-check → iterate, with a
  soft cap of 2–3 rounds. The agent does not spin forever.
- **One knob drives two things**: the fidelity profile (**more_editable /
  balanced / more_faithful**) changes both the generation prompt *and* the scoring
  weights, so what we ask for and what we measure stay aligned.
- **Two-layer scoring**: per-axis hard gates catch cheap bugs (missing footer);
  a normalized weighted total ranks overall quality. No single number can fake a pass.
- **Profile-aware hard rules**: in more_faithful the agent must call
  `capture_site` → `extract_assets` → `write_html` in order and may not use
  placeholder logos.
- **`:root` as single source of truth** for tokens, so brand edits never drift
  from the HTML.
- **Graceful degrade**: `domcontentloaded` + short wait for heavy-JS sites, and a
  DOM-only fallback so capture never hard-crashes the run.

### Tradeoffs / where we pushed back (good interview answers)

- **Fidelity is not pixel-only.** Different copy/colors swing pixel diffs wildly,
  so we added content + structure axes. (Phase 2)
- **Tokens live in `:root`, not a sidecar JSON**, to avoid HTML/token drift. (Phase 3)
- **We removed the fidelity knob from the Builder toolbar** — it does not
  regenerate, so showing it there would mislead; we show the current profile
  read-only instead. (product-boundary call)
- **Local edits use bs4, not regex** — nested HTML breaks regex replaces. (Phase 4)

### What we deliberately left out (and why)

- **Snapshot / rollback / accept-reject diff UI** (IDEA Phase 5): this is editor
  product UX, not "how the agent reasons." Lower value for an agent-focused review.
- **The reliability proof that *does* matter** — a multi-site batch run that logs
  per-site similarity — is the one Phase 5 slice worth showing, on top of the
  existing `scripts/fidelity_batch.py`.

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
2. **Model config**: Switch `sonnet` / `opus` / etc. with `AGENT_MODEL` (default `haiku`) without code edits.
3. **Startup self-check**: On boot, the terminal prints the active model, Claude CLI transport source, and whether `.env` exists (no secret leak).
4. **Benchmark URL set**: `data/benchmarks.json` lists 4 fixed sites for later vision work and regression.
5. **Doc setup**: `docs/ADR.md`, [`docs/phase-1-visual-loop.md`](phase-1-visual-loop.md), and this file; we extend them each phase.

### Key tech choices

| Choice | Why | What we did not do | ADR |
|--------|-----|---------------------|-----|
| Keep Claude Agent SDK + CLI | Matches starter; MCP tools wired; CLI login is enough to run | Raw Anthropic API, Ollama | [`0001`](ADR.md#adr-0001) |
| `AGENT_MODEL` env var, default haiku | Cheap local iteration; override with `opus` for closer copy | Hard-coded model, CLI-only flag | [`0002`](ADR.md#adr-0002) |
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

#### Q2: Why default `haiku` instead of `opus`?

**Answer:** Local dev and take-home iteration are cheaper with `haiku`. For a final demo or when you need the strongest layout and copy match, set `AGENT_MODEL=opus` in `.env` and restart.

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

---

<a id="interview-phase-4"></a>

## Phase 4 — Small edits + Code + Compare (implemented)

> Maps to [`IDEA.md`](../IDEA.md) Phase 4 · Plan: [`phase-4-edits-compare.md`](phase-4-edits-compare.md)

### What we ship

1. **`edit_section(selector, html)`** — bs4 partial replace by `data-section` / `#id` / tag.
2. **Code tab** — `GET /source`, highlight, Copy, Download, Format (display-only).
3. **Compare tab** — `POST /compare` + Phase 2 four-axis report, tiles, heatmap (`GET /shots/`).
4. **`scripts/verify_phase4.py`** — section list/replace unit tests.

### Likely follow-up questions

#### Q1: Why BeautifulSoup?

**Answer:** Nested HTML breaks regex replacements. bs4 finds the first anchored block and swaps only that fragment.

#### Q2: Does Compare call the agent?

**Answer:** No. `POST /compare` runs Playwright + `fidelity_report` directly — same math as `compare_to_target`, for the UI.

### How we verify

- `python scripts/verify_phase4.py`
- Code tab copy/download on a generated page.
- Compare tab shows content/structure/layout/visual scores after Run compare.

---

<a id="interview-phase-5"></a>

## Phase 5 — Reliability and control (implemented)

> Maps to [`IDEA.md`](../IDEA.md) Phase 5 · Plan: [`phase-5-reliability.md`](phase-5-reliability.md)

### What we ship

1. **`save_output()` write funnel** — every edit snapshots the prior `index.html` under `output/.history/`.
2. **Revert last + History panel** — toolbar button, list of snapshots, unified diff, per-row rollback.
3. **History API** — `GET /history`, `GET /history/diff`, `POST /history/rollback`, `POST /history/revert-last`.
4. **`friendly_capture_error()`** — plain copy for timeout/DNS/SSL/nav failures (no stack traces in UI).
5. **`fidelity_batch.py --generate`** — agent per benchmark → `data/regression_report.json`.

### Key tech choices

| Choice | Why | What we did not do | ADR |
|--------|-----|---------------------|-----|
| Snapshot-before-write | `revert_last` = restore last pre-change bytes exactly | Snapshot-after-write | [`0011`](ADR.md#adr-0011) |
| Single write funnel | No missed snapshots from panel vs agent writes | Per-tool ad-hoc history | [`0011`](ADR.md#adr-0011) |
| Revert-last vs full accept/reject UI | Enough for agent-focused review; lighter UX | Modal on every write | [`0011`](ADR.md#adr-0011) |
| `--generate` regression batch | Proves "reliably" with per-site scores | Manual demo only | [`0011`](ADR.md#adr-0011) |

### Likely follow-up questions

#### Q1: Why snapshot *before* write?

**Answer:** The newest history entry is always "what we had right before this change." `revert_last` restores that file — one step back, exact bytes.

#### Q2: Does rollback create a new snapshot?

**Answer:** Yes. `restore()` calls `save_output()` first, so undo-of-undo is safe.

#### Q3: What does `--generate` do vs normal batch?

**Answer:** Normal batch scores an existing `output/index.html` against all benchmarks. `--generate` runs the **agent** for each benchmark URL, then scores that site's output — writes `data/regression_report.json`.

### How we verify

- `python scripts/verify_phase5.py` — snapshots, revert, diff, friendly errors.
- Make an edit in the app → History panel shows an entry → Revert last restores preview.
- `python scripts/fidelity_batch.py --generate` (optional; needs Claude CLI + API budget).

---

<a id="interview-phase-6"></a>

## Phase 6 — Self-convergence + A/B proof (implemented)

> Maps to [`IDEA.md`](../IDEA.md) Phase 6 · Plan: [`phase-6-self-convergence.md`](phase-6-self-convergence.md) · [ADR 0012](ADR.md#adr-0012)

### What we ship

1. **Convergence tracking** — every `compare_to_target` self-check appends a
   round (total, verdict, per-axis normalized, `worst_sections`, `gate_failures`)
   to the active run; persisted per session in `data/convergence.json`.
2. **Insights view** — headline **first build → final** delta, a fidelity-per-round
   curve with pass/warn threshold lines, and per-round `worst_sections` chips
   (struck = resolved next round). Live-updates over a new SSE `convergence` event.
3. **A/B baseline** — `POST /ab` runs a tool-restricted ("`capture_site` +
   `write_html`, one shot, no self-check") agent for the same URL, scores it, and
   overlays it as the one-shot baseline — then restores the user's loop result.
4. **`scripts/verify_phase6.py`** — round ordering, per-session persistence, live
   active run, baseline store, empty-run guard.

### Key tech choices

| Choice | Why | What we did not do | ADR |
|--------|-----|---------------------|-----|
| Per-round record keyed by session | Live curve + free first→final delta | Scores only in chat text | [`0012`](ADR.md#adr-0012) |
| Active-run module global | Agent lock serializes runs | Thread/session plumbing | [`0012`](ADR.md#adr-0012) |
| Opt-in A/B via restricted one-shot | True "naked vs loop" without doubling every build | Always run A/B | [`0012`](ADR.md#adr-0012) |
| Restore output after A/B | Non-destructive demo | Leave naked build in place | [`0012`](ADR.md#adr-0012) |

### Likely follow-up questions

#### Q1: Is the "first build → final" delta real or staged?

**Answer:** Real. Round 1 is the agent's first self-check (first build, pre-fix);
the last round is post-iteration. Both come from actual `compare_to_target` calls
in the run — no synthetic numbers.

#### Q2: How is the A/B baseline a fair "naked AI"?

**Answer:** We run the same model with only `capture_site` + `write_html` and a
prompt that forbids self-check/iteration — that *is* "minimal guidance." We score
that output, then restore the loop result so the demo isn't clobbered.

#### Q3: Why per-session global state instead of a run id?

**Answer:** The agent lock guarantees one run at a time, so a single active-run
global is correct and simpler; it's tagged with the session id once detected and
persisted under that key.

### How we verify

- `python scripts/verify_phase6.py` passes.
- After a real build, Insights shows a rising curve and a positive first→final
  delta; clicking **Run A/B baseline** overlays the one-shot line and the gap.
