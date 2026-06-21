# Architecture Decision Records (ADR)

All architecture decisions for this project live in this single file. Older numbers stay stable when you add new sections at the bottom.

| ID | Title | Phase |
|----|--------|-------|
| [0001](#adr-0001) | Model stack: keep Claude Agent SDK + CLI transport | Phase 0 |
| [0002](#adr-0002) | Model config: `AGENT_MODEL` env var | Phase 0 |
| [0003](#adr-0003) | Observability: startup self-check logs (stderr) | Phase 0 |
| [0004](#adr-0004) | Benchmark URL set: `data/benchmarks.json` | Phase 0 |
| [0005](#adr-0005) | Phase 1 visual loop: Playwright + MCP image blocks | Phase 1 |
| [0006](#adr-0006) | Phase 2 fidelity: four-axis scoring + two-layer thresholds | Phase 2 |
| [0007](#adr-0007) | Fidelity knob: more_editable / balanced / more_faithful profiles | Phase 2 |
| [0008](#adr-0008) | Asset mirroring + asset_coverage (more_faithful only) | Phase 2 |
| [0009](#adr-0009) | Design tokens: `:root` as source of truth + live edit | Phase 3 |
| [0010](#adr-0010) | Partial edits + Code/Compare UI (Phase 4) | Phase 4 |
| [0011](#adr-0011) | Output history: single write funnel + snapshot-before-write | Phase 5 |
| [0012](#adr-0012) | Self-convergence tracking + A/B baseline via tool-restricted one-shot | Phase 6 |

---

<a id="adr-0001"></a>

## 0001 — Model stack: keep Claude Agent SDK + CLI transport

- **Status**: Accepted
- **Date**: 2026-06-19
- **Phase**: Phase 0

### Context

The starter uses `ClaudeSDKClient` from `claude-agent-sdk`. By default it uses `SubprocessCLITransport` to run the Claude Code CLI on this machine (or the bundled `claude` from the SDK). It does **not** call the Anthropic HTTP API from Python. On a dev machine you may have no `ANTHROPIC_API_KEY`, but you are logged in through the CLI.

### Decision

**Keep Claude Agent SDK + CLI transport as the only model stack.** We do not add a bare API-key client or local Ollama as the default path.

### Rationale

- Matches the official starter. MCP tools (`write_html` / `read_html`), `WebFetch` / `WebSearch`, and the rest are already wired.
- CLI login is enough to run locally. Less setup friction.
- The README asks for an agentic flow and tool design, not a new LLM vendor under the hood.

### Alternatives

| Option | Pros | Cons | Outcome |
|--------|------|------|---------|
| Anthropic Python SDK, direct HTTP | No CLI needed | You must build the agent loop and tool protocol yourself; drifts from the starter | Not chosen |
| Local Ollama | Free, can work offline | Does not fit `claude-agent-sdk`; large effort | Not chosen |
| Claude Agent SDK + CLI | No rewrite, full tools | Needs CLI install and login; model names come from the CLI | **Chosen** |

### Consequences and risks

- **Impact**: `server.py` keeps `ClaudeSDKClient`. Auth issues mean checking the CLI, not only `.env`.
- **Risk**: CI or deploy has no CLI → Phase 7 needs docs or an image with the CLI pre-installed.

---

<a id="adr-0002"></a>

## 0002 — Model config: `AGENT_MODEL` env var

- **Status**: Accepted
- **Date**: 2026-06-19
- **Phase**: Phase 0

### Context

`ClaudeAgentOptions.model` used to be hard-coded (e.g. `haiku` / `opus`). That made it slow to try cost vs quality tradeoffs. The README example also did not pick one default model.

### Decision

Set the model alias with env var **`AGENT_MODEL`**. **Default is `haiku`** (lowest cost for local iteration). Support SDK aliases like `sonnet`, `opus`, `inherit`. Put `AGENT_MODEL=haiku` in `.env.example`; use `opus` when you need a closer visual copy.

```python
model=os.environ.get("AGENT_MODEL", "haiku"),
```

### Rationale

- You can switch quality, speed, and cost for dev or demo without code edits.
- `load_dotenv()` already runs at startup in `server.py`, same pattern as `.env`.
- Default `haiku` keeps day-to-day dev cheap; final demos can set `AGENT_MODEL=opus`.

### Alternatives

| Option | Pros | Cons | Outcome |
|--------|------|------|---------|
| Hard-code in code | Simple | Every switch needs a code edit; easy to commit by mistake | Not chosen |
| CLI flag `--model` | Very clear | Annoying with uvicorn reload and many processes | Not chosen |
| Env var `AGENT_MODEL` | Matches `.env`, easy to document | Must restart the server | **Chosen** |

### Consequences and risks

- **Impact**: `agent_loop.py` `_build_agent_options`; startup self-check logs the active model.
- **Risk**: Bad alias → error from CLI; startup log shows `AGENT_MODEL` to help debug.

---

<a id="adr-0003"></a>

## 0003 — Observability: startup self-check logs (stderr)

- **Status**: Accepted
- **Date**: 2026-06-19
- **Phase**: Phase 0

### Context

Developers were confused: “Why does the model work with no `.env`?” Auth actually comes from the Claude CLI. Without a clear print of runtime settings at boot, debugging cost time.

### Decision

In FastAPI `lifespan` startup, call **`_startup_selfcheck()`** and print to **stderr** (never print secrets):

- Current `AGENT_MODEL`
- **transport**: whether `claude` on PATH or the SDK bundled CLI exists
- **Whether `.env` exists** (boolean only; do not read or print key values)

Later phases keep using the existing SSE `_push_chat` for agent progress. This ADR does not extend that.

### Rationale

- Small change: only `server.py`, no new deps.
- stderr matches uvicorn logs; works locally and in containers.
- Makes clear: “CLI login” vs “API key in `.env`” are two different paths.

### Alternatives

| Option | Pros | Cons | Outcome |
|--------|------|------|---------|
| `/health` returns config JSON | Can check from afar | May leak deploy details; too much design | Not chosen |
| Docs only | No code | Still invisible at runtime | Not chosen |
| stderr self-check in lifespan | Fast, no secret leak | Not structured JSON | **Chosen** |

### Consequences and risks

- **Impact**: Each server boot adds 3–4 log lines.
- **Risk**: If we add more transports later, we must extend the self-check output.

---

<a id="adr-0004"></a>

## 0004 — Benchmark URL set: `data/benchmarks.json`

- **Status**: Accepted
- **Date**: 2026-06-19
- **Phase**: Phase 0

### Context

Later phases (vision loop, similarity scores, regression) need a fixed set of target sites. We should not type a new URL every time; that makes results hard to compare.

### Decision

Keep **3–5** benchmark sites in **`data/benchmarks.json`**. Format: JSON array. Each item:

```json
{
  "id": "stripe",
  "url": "https://stripe.com",
  "note": "Complex SaaS landing page, many gradients and components"
}
```

Track the file in git (`data/` exists; only `data/.session_id` is gitignored).

### Rationale

- Same folder as `data/sessions.json`, fits project data layout.
- Humans can read it; scripts can `json.load`; Phase 5 batch runs can reuse it.
- Stable `id` helps reports and links into this file.

### Alternatives

| Option | Pros | Cons | Outcome |
|--------|------|------|---------|
| Hard-code in Python | No extra file | URL changes need code edits | Not chosen |
| YAML | Readable | Extra format / dep | Not chosen |
| `data/benchmarks.json` | Simple, matches `data/` | List is manual | **Chosen** |

### Consequences and risks

- **Impact**: Phase 1+ test scripts read this file; add sites by editing JSON.
- **Risk**: Remote sites change layout → drift. Use `note` for what matters; keep screenshot archives for evals.

---

<a id="adr-0005"></a>

## 0005 — Phase 1 visual loop: Playwright + MCP image blocks

- **Status**: Accepted
- **Date**: 2026-06-20
- **Phase**: Phase 1

### Context

The agent could only use `WebFetch` (text) plus `write_html` / `read_html`. It never saw the target site or its own output as pixels, so copies were guess-based. We needed a production-style **visual loop** without rewriting the whole agent transport.

### Decision

1. Add **`playwright`** (pinned) and **`browser.py`**: headless Chromium, shared browser, `asyncio.Lock`, navigation timeout, tiled PNG captures to `output/.shots/`, plus a compact **computed-style JSON** via `page.evaluate`.
2. Add MCP tools **`capture_site(url)`** and **`screenshot_output()`** in [`tools/handlers_capture.py`](../tools/handlers_capture.py): return MCP `content` with **text + `image` blocks** (base64 PNG, `mimeType: image/png`) plus the styles JSON text block.
3. Extend **`_make_handler`** so tool results that already look like `{"content": [...]}` pass through unchanged; plain strings still become a single text block.
4. Update **`SYSTEM_PROMPT`** in [`prompts.py`](../prompts.py): look (`capture_site`) → build (`write_html`) → self-check (`screenshot_output`) → fix; cap iterations in prose; on nav failure use DOM-only fallback (no images).
5. Call **`close_browser()`** from FastAPI **`lifespan`** shutdown so Playwright does not leak on reload.

Full step checklist and diagram: [`phase-1-visual-loop.md`](phase-1-visual-loop.md).

### Rationale

- `claude-agent-sdk` already maps tool output image dicts to `ImageContent` for the CLI — no separate multimodal `query()` API was needed.
- Tiled screenshots keep each image within a useful size for vision models.
- Style JSON gives structured signals when screenshots fail (DOM-only path).

### Alternatives

| Option | Pros | Cons | Outcome |
|--------|------|------|---------|
| Return only file paths in text; model reads files elsewhere | Small payloads | Not supported as a built-in second hop in this MCP surface | Not chosen |
| Push images via `client.query` multimodal | Full control | Tighter coupling to SDK message types; more code in `server.py` | Not chosen |
| MCP tools return image blocks + JSON text | Uses existing tool path; works with CLI transport | Larger RPC payloads; needs Playwright in deploy | **Chosen** |

### Consequences and risks

- **Impact**: New dependency and disk under `output/.shots/`; CI / Docker must run `playwright install chromium` (see Phase 7 in `IDEA.md`).
- **Risk**: Some sites block automation or never reach `networkidle` — mitigated by timeout + DOM-only fallback.
- **Docs**: Plan persisted in [`phase-1-visual-loop.md`](phase-1-visual-loop.md); interview notes in [`INTERVIEW.md`](INTERVIEW.md#interview-phase-1).

---

<a id="adr-0006"></a>

## 0006 — Phase 2 fidelity: four-axis scoring + two-layer thresholds

- **Status**: Accepted
- **Date**: 2026-06-20
- **Phase**: Phase 2

### Context

Phase 1 let the agent see pixels and self-check in prose, but "looks close" was subjective. We needed measurable scores on content, structure, layout, and visual fidelity — with thresholds the loop and batch scripts can gate on — without rewriting the MCP transport.

### Decision

1. Add the **`compare/`** package (pure Python, no Playwright): `score_content`, `score_structure`, `score_layout`, `score_visual` (local windowed SSIM + pHash via Pillow/numpy; no scikit-image), `fidelity_report`, optional `diff_heatmap`.
2. Extend **`browser.py`** with `_EXTRACT_COMPARE_JS` and **`capture_compare()`** returning text blocks, skeleton, section boxes, and tiles.
3. Add MCP tool **`compare_to_target(url)`** with per-URL target cache in [`tools/handlers_fidelity.py`](../tools/handlers_fidelity.py).
4. **Two-layer thresholds** in [`data/fidelity.json`](../data/fidelity.json): per-axis hard gates (content coverage, landmark order, min block IoU) plus normalized weighted total with pass/warn bands. Floors/ceilings calibrated via `scripts/fidelity_batch.py --calibrate`.
5. Update **`SYSTEM_PROMPT`**: self-check calls `compare_to_target`, fixes `worst_sections`, stops on pass or iteration cap.

Full plan: [`phase-2-fidelity.md`](phase-2-fidelity.md).

### Rationale

- Four axes catch different failure modes (missing copy vs misplaced blocks vs pixel drift).
- Normalizing each axis to `[floor, ceil]` makes a single weighted total meaningful.
- Hard gates prevent high visual scores from masking missing sections.
- Pure `compare/` package is unit-testable without a browser.

### Alternatives

| Option | Pros | Cons | Outcome |
|--------|------|------|---------|
| Visual-only (SSIM / pixel diff) | Simple | Misses text/structure errors | Not chosen alone |
| scikit-image SSIM | Battle-tested | Extra dep | Not chosen; local numpy SSIM |
| One global threshold | Easy | False pass when one axis fails badly | Not chosen |
| Two-layer per-axis + normalized total | Tunable, explainable | More config | **Chosen** |

### Consequences and risks

- **Impact**: New deps (`Pillow`, `numpy`); `data/fidelity.json` must be tuned per benchmark set.
- **Risk**: Remote `networkidle` hangs slow batch runs — use local HTML for quick checks; timeouts unchanged from Phase 1.
- **Docs**: [`phase-2-fidelity.md`](phase-2-fidelity.md); interview in [`INTERVIEW.md`](INTERVIEW.md#interview-phase-2).

---

<a id="adr-0007"></a>

## 0007 — Fidelity knob: more_editable / balanced / more_faithful profiles

- **Status**: Accepted
- **Date**: 2026-06-20
- **Phase**: Phase 2

### Context

Phase 2 scoring exposed a product tension: **semantic, editable HTML** scores low on **structure** vs div-heavy production DOM on many target sites. Users and reviewers need to see this as an intentional tradeoff, not a bug — and power users may want more visual fidelity at the cost of slightly messier markup.

### Decision

Add a **3-position fidelity knob** wired through one field, `fidelity_profile`:

1. **UI** (`viewer.html`): segmented control on landing + builder toolbar; default **balanced**; persisted in `localStorage`.
2. **Prompt** (`prompts.py`): `_PROFILE_BUILD_RULES` appended to system prompt per profile (how to `write_html`).
3. **Scoring** (`data/fidelity.json` → `compare.load_config(profile=...)`): per-profile weights, thresholds, and hard gates. **Editable** sets structure weight to 0 and drops structure from `worst_sections`.
4. **Tool** (`compare_to_target(url, profile=...)`): report includes `profile`; server sets session default via `set_fidelity_profile()` before each agent run.

We did **not** add a separate "1:1 DOM clone" engine — all profiles share the same capture/compare pipeline.

### Rationale

- **Prompt alone** would change generation but leave scoring misaligned (false fails on structure).
- **Scoring alone** would not change what the agent builds.
- Three tiers express the editable↔faithful spectrum; **balanced** matches the take-home product goal.

### Alternatives

| Option | Pros | Cons | Outcome |
|--------|------|------|---------|
| Two modes only (editable vs 1:1) | Simple UI | Hides the default "sweet spot"; 1:1 fights product goal | Not chosen |
| Prompt-only knob | Tiny diff | Scores disagree with intent | Not chosen |
| Prompt + profile-scoped config | Aligned behavior and metrics | More JSON config | **Chosen** |
| Full second capture pipeline for 1:1 | True clone | Huge scope; off-mission | Not chosen |

### Consequences and risks

- **Impact**: `data/fidelity.json` grows `profiles` block; `/chat` accepts `fidelity_profile`.
- **Risk**: User changes profile mid-session — later compares should pass the same profile explicitly (session default + tool arg).
- **Docs**: [`phase-2-fidelity.md`](phase-2-fidelity.md#fidelity-knob-3-profiles).

---

<a id="adr-0008"></a>

## 0008 — Asset mirroring + asset_coverage (more_faithful only)

- **Status**: Accepted
- **Date**: 2026-06-20
- **Phase**: Phase 2

### Context

**More faithful** mode still used logo placeholders because prompts forbade real assets and there was no download pipeline. Users expect mirrored logos and heroes while keeping semantic HTML.

### Decision

1. Add [`assets.py`](../assets.py) + MCP tool **`extract_assets(url)`**: Playwright collects:
   - `<img>` (including lazy `data-src`, `srcset`)
   - favicon / font preload links
   - **computed** `background-image` URLs (not only inline `style`)
   - inline `<svg>` serialized to local `.svg` files
   - `@font-face` URLs downloaded to `output/assets/fonts/`
   Writes `manifest.json` with `preview_path` (`/assets/...`), `fonts`, and `hints.font_faces`.
2. Serve files via **`GET /assets/{path}`** in [`routes/site.py`](../routes/site.py) so preview uses same-origin paths.
3. **`more_faithful` prompt**: mandatory `extract_assets` after `capture_site`; use manifest paths for img/background/SVG/fonts; forbid wordmark placeholders when mirrored logo exists.
4. **`asset_coverage`** in [`compare/axes.py`](../compare/axes.py) `score_assets`: share of mirrored role assets (logo, favicon, hero, **font** when present) referenced in output HTML.
5. **Enforcement scope**: `asset_coverage` hard gate + weighted axis + `worst_sections` **only when `profile == more_faithful`**. Other profiles report `assets.enforced: false` (informational if manifest exists).
6. Rename profiles: `editable` → **`more_editable`**, `faithful` → **`more_faithful`** (legacy aliases accepted).

### Rationale

- Local mirror beats hotlinking: works offline, improves visual SSIM, fits export story.
- Scoring asset coverage only in **more_faithful** avoids punishing placeholder logos in **more_editable** / **balanced**.

### Consequences

- **Impact**: `output/assets/` on disk; agent must call `extract_assets` before compare in more_faithful.
- **Limit**: Cross-origin stylesheets may hide some `@font-face` rules; sprite sheets and canvas logos still out of scope.

---

<a id="adr-0009"></a>

## 0009 — Design tokens: `:root` as source of truth + live edit

- **Status**: Accepted
- **Date**: 2026-06-20
- **Phase**: Phase 3

### Context

Generation hard-codes colors/fonts, so "re-brand" means a full-file rewrite — slow, regression-prone, and not a real customization story. We need editable design tokens (Builder.io pattern: keep tokens, change token = rebrand) without a heavy design-system setup.

### Decision

1. The **`:root { --token: value }` block inside `output/index.html` is the single source of truth.** No sidecar `tokens.json` to drift.
2. Add [`tokens.py`](../tokens.py): a **canonical token vocabulary** (`--color-brand`, `--font-base`, `--radius`, …) plus `extract_tokens_from_styles`, `parse_root_vars`, `patch_root_vars`, `categorize`, `rgb_to_hex`. Shared by tools and server.
3. Tools: **`extract_design_tokens(url)`** (seed from capture), **`read_design_tokens()`**, **`set_design_token(name, value)`** (one-var patch, no rewrite).
4. Endpoints **`GET /tokens`** / **`POST /tokens`** let the panel edit tokens **without the LLM** (string patch + `html_updated` reload).
5. Prompt (all profiles): author one `:root` with canonical names and use `var(--…)` everywhere; seed via `extract_design_tokens`.
6. UI: collapsible **Design Tokens panel** with color pickers; debounced write-back.

### Rationale

- One source of truth avoids HTML/JSON desync.
- Panel edits skip the LLM → instant, deterministic, cheap; agent reserved for semantic edits.
- Canonical names keep prompt, panel, and tools in agreement.

### Alternatives

| Option | Pros | Cons | Outcome |
|--------|------|------|---------|
| Sidecar `tokens.json` + inject at render | Structured, queryable | Desyncs from edited HTML; extra build step | Not chosen |
| Agent handles every token edit | No new endpoints | Slow, costly, non-deterministic for a color tweak | Not chosen |
| `:root` source of truth + parse/patch | Minimal diff, instant panel edits, reusable by agent | Regex must edit one `:root` carefully | **Chosen** |

### Consequences and risks

- **Impact**: new `tokens.py`, two endpoints, three tools, a viewer panel; prompt requires `:root` + `var(--…)`.
- **Risk**: `patch_root_vars` must target the first `:root` only and preserve the rest of the file; covered by `scripts/verify_phase3.py` round-trip tests.
- **Limit**: single `:root` (no per-component themes / light-dark); spacing/shadow extraction is best-effort.

---

<a id="adr-0010"></a>

## 0010 — Partial edits + Code/Compare UI (Phase 4)

- **Status**: Accepted
- **Date**: 2026-06-20
- **Phase**: Phase 4

### Context

`write_html` replaces the entire document each turn — slow, regression-prone, and poor for chat edits like "change the hero." Reviewers also need to see clean source code and a visual fidelity breakdown, not only agent tool JSON.

### Decision

1. **`data-section` anchors** in generation prompt (`nav`, `hero`, `features`, `cta`, `footer`, …).
2. [`sections.py`](../sections.py) + **`edit_section(selector, html)`** using BeautifulSoup4; prefer partial edits over full rewrites in follow-ups.
3. **Code view**: `GET /source`, offline syntax highlight, Copy / Download / Format (display-only).
4. **Compare view**: `run_fidelity_comparison()` shared by tool + **`POST /compare`**; **`GET /shots/{path}`** serves tiles/heatmap; UI shows four-axis scores + worst sections.
5. No multi-file tree (single `index.html`).

### Rationale

- bs4 gives reliable fragment replacement vs regex on nested HTML.
- Compare reuses Phase 2 scoring — no third similarity metric.
- Panel/API compare bypasses the LLM for deterministic reviewer demos.

### Alternatives

| Option | Pros | Cons | Outcome |
|--------|------|------|---------|
| Regex section replace | No new dep | Breaks on nesting | Not chosen |
| BeautifulSoup replace | Robust | Normalizes HTML slightly | **Chosen** |
| Embed Monaco | Rich editor | Heavy, CDN | Not chosen |
| New similarity score | Custom | Duplicates Phase 2 | Not chosen |

### Consequences and risks

- **Impact**: `sections.py`, `edit_section` tool, three view tabs, `/source` `/compare` `/shots`.
- **Risk**: bs4 may reformat HTML on save; mitigated by surgical single-block replace.
- **Limit**: no file tree / rollback (Phase 5).

---

<a id="adr-0011"></a>

## 0011 — Output history: single write funnel + snapshot-before-write

- **Status**: Accepted
- **Date**: 2026-06-21
- **Phase**: Phase 5

### Context

Edits can come from the agent (`write_html`, `edit_section`, `set_design_token`) or the tokens panel (`POST /tokens`). A bad hero edit or token tweak should be undoable without re-running the agent. Reviewers also need proof the agent works reliably across benchmark sites.

### Decision

1. **`history.py`** with `save_output(html, label)` — snapshot current `index.html` *before* every overwrite.
2. **All four write paths** funnel through `save_output` (tools + `POST /tokens`).
3. **API**: `GET /history`, `GET /history/diff`, `POST /history/rollback`, `POST /history/revert-last`.
4. **Viewer**: History panel + Revert last toolbar button; unified diff with +/- coloring.
5. **`friendly_capture_error()`** in `browser.py` for user-facing capture failures.
6. **`fidelity_batch.py --generate`** runs agent per benchmark and writes `data/regression_report.json`.

### Rationale

- One funnel avoids missing a write path and skipping snapshots.
- Snapshot-before-write makes `revert_last` always restore the exact prior bytes.
- Rollback snapshots current first, so undo-of-undo is safe.
- Friendly errors keep the agent loop alive without stack traces in chat/UI.
- Regression batch is the reliability proof for interview/APPROACH.

### Alternatives

| Option | Pros | Cons | Outcome |
|--------|------|------|---------|
| Git-based history | Familiar | Overkill; needs git in output | Not chosen |
| Snapshot-after-write | Simple | Revert needs "previous" pointer | Not chosen |
| Snapshot-before-write | Revert = last entry | First write has no snapshot | **Chosen** |
| Full diff accept/reject modal | Rich UX | Heavy; agent-focused review cares less | Deferred (revert-last enough) |

### Consequences and risks

- **Impact**: `history.py`, four write call sites, four endpoints, History panel, `--generate` batch.
- **Risk**: History grows; capped at 50 entries with oldest file deletion.
- **Limit**: single-file history only; no branching.

---

<a id="adr-0012"></a>

## ADR 0012 — Self-convergence tracking + A/B baseline

- **Status**: Accepted
- **Date**: 2026-06-21
- **Phase**: Phase 6

### Context

The README's bar is "better than what an AI would produce on its own with
minimal guidance." We already run a look → measure → fix loop, but the value was
invisible: scores lived only in chat text. We needed to *show* the agent
correcting itself, and to *quantify* the loop vs a naked one-shot.

### Decision

- **Record every `compare_to_target` as a round** of an active run, keyed per
  session in `data/convergence.json`. The agent lock serializes runs, so a
  module-global active run is safe.
- **Insights view** draws the score curve, first→final delta, and per-round
  `worst_sections` (struck when resolved next round); refreshes live over a new
  SSE `convergence` event.
- **A/B baseline** (`POST /ab`) reuses the agent with a **restricted tool set**
  (`capture_site` + `write_html`) and a "one shot, no self-check" prompt, scores
  it, stores it as baseline, then **restores** the user's loop output.

### Rationale

- The first round of the real run is the honest "first build" number; the last
  round is post-iteration — the delta is free, real evidence (no extra cost).
- A true A/B (separate naked run) is opt-in because it costs an extra agent run;
  restoring output afterward keeps it non-destructive.
- Reusing `_build_agent_options` with a tool subset avoids a second code path.

### Alternatives

| Option | Pros | Cons | Outcome |
|--------|------|------|---------|
| Show scores in chat only | No new code | Invisible, not persuasive | Superseded |
| Reconstruct rounds from history snapshots | No live hook | Needs re-capture/scoring per snapshot | Not chosen |
| Always run naked A/B every build | Strongest proof | Doubles API cost/time | Made opt-in |
| Per-round record + opt-in A/B | Cheap, live, honest | Active-run global state | **Chosen** |

### Consequences and risks

- **Impact**: new `convergence.py`, `compare_to_target` hook, `agent_loop.run_agent`
  begin/end, `/convergence` + `/ab` endpoints (`routes/insights.py`), `_build_agent_options` tool
  subset, Insights view, [`docs/phase-6-self-convergence.md`](phase-6-self-convergence.md), `scripts/verify_phase6.py`.
- **Risk**: active-run global assumes one run at a time (true under the agent
  lock). A/B baseline depends on a live Claude run; failures return a friendly
  error and never clobber the saved output.

---

## Adding a new ADR

Use the next free number (0009, 0010, …). Append a new section at the bottom of this file with the same shape:

- **Status**: Proposed | Accepted | Superseded by NNNN  
- **Date**: YYYY-MM-DD  
- **Phase**: Phase N  

Then subsections: **Context**, **Decision**, **Rationale**, **Alternatives** (table), **Consequences and risks**.

Add a row to the table at the top and an `<a id="adr-NNNN"></a>` anchor before the new `##` heading.

For the same phase, add or update the matching section in [`INTERVIEW.md`](INTERVIEW.md) and link ADR rows to `ADR.md#adr-NNNN`.
