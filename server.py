"""FastAPI server for the website builder.

Serves the viewer, hosts the HTML preview, and runs the agent.
"""

import asyncio
import json
import os
import shutil
import sys
from collections.abc import Callable
from pathlib import Path

os.environ.pop("CLAUDECODE", None)

from contextlib import asynccontextmanager

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

# SSE subscribers
_subscribers: list[asyncio.Queue] = []
_version = 0

OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "index.html"
SESSIONS_DIR = Path.home() / ".claude" / "projects"
# Cheapest default for local dev; set AGENT_MODEL=opus in .env for closer copies.
AGENT_MODEL = os.environ.get("AGENT_MODEL", "haiku")


def _detect_claude_transport() -> str:
    """Report which Claude Code CLI the SDK is likely to use (no secrets)."""
    if cli := shutil.which("claude"):
        return f"claude CLI at {cli}"
    try:
        import claude_agent_sdk

        bundled = (
            Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
        )
        if bundled.is_file():
            return f"bundled CLI at {bundled}"
    except ImportError:
        pass
    return "claude CLI not found in PATH (SDK may fail until installed)"


def _startup_selfcheck() -> None:
    """Print runtime config to stderr; never log secrets."""
    env_file = Path(".env")
    print("[startup] AGENT_MODEL:", AGENT_MODEL, file=sys.stderr)
    print("[startup] transport:", _detect_claude_transport(), file=sys.stderr)
    print(
        "[startup] .env file:",
        "present" if env_file.is_file() else "not found",
        file=sys.stderr,
    )


def _get_session_dir() -> Path | None:
    """Find the Claude session storage directory for this project."""
    cwd = Path.cwd().resolve()
    slug = str(cwd).replace("/", "-")
    d = SESSIONS_DIR / slug
    return d if d.exists() else None


def _session_jsonl_path(session_id: str) -> Path | None:
    """Path to the Claude Code JSONL transcript for a session, if the store exists."""
    if not session_id:
        return None
    sdir = _get_session_dir()
    if not sdir:
        return None
    return sdir / f"{session_id}.jsonl"


def _can_resume_session(session_id: str | None) -> bool:
    """True when Claude Code still has a transcript we can resume."""
    if not session_id:
        return False
    path = _session_jsonl_path(session_id)
    return path is not None and path.is_file()


def _notify(event: str = "update") -> None:
    global _version
    _version += 1
    data = json.dumps({"version": _version, "event": event})
    for q in list(_subscribers):
        try:
            q.put_nowait(data)
        except asyncio.QueueFull:
            pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    Path("data").mkdir(parents=True, exist_ok=True)
    _seed_fidelity_config()
    from tools import set_notify_fn
    set_notify_fn(_notify)
    _load_sessions()
    _startup_selfcheck()
    yield
    from browser import close_browser
    await close_browser()


def _seed_fidelity_config() -> None:
    """Write default fidelity thresholds if data/fidelity.json is missing."""
    path = Path("data/fidelity.json")
    if path.is_file():
        return
    from compare import default_config

    path.write_text(json.dumps(default_config(), indent=2) + "\n")


app = FastAPI(title="Website Builder", lifespan=lifespan)


# --- Viewer ---


@app.get("/", response_class=HTMLResponse)
async def viewer():
    return FileResponse("viewer.html", headers={"Cache-Control": "no-store"})


# --- SSE ---


@app.get("/events")
async def events(request: Request):
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    _subscribers.append(q)

    async def stream():
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15)
                    yield {"data": data}
                except asyncio.TimeoutError:
                    yield {"comment": "keepalive"}
        finally:
            _subscribers.remove(q)

    return EventSourceResponse(stream())


# --- HTML preview ---


@app.get("/preview", response_class=HTMLResponse)
async def preview():
    if OUTPUT_FILE.exists():
        return FileResponse(OUTPUT_FILE, headers={"Cache-Control": "no-store"})
    return HTMLResponse(
        "<html><body></body></html>"
    )


@app.get("/assets/{asset_path:path}")
async def serve_asset(asset_path: str):
    """Serve mirrored assets from output/assets/ for faithful previews."""
    base = Path("output") / "assets"
    # Tolerate an accidentally duplicated leading "assets/" segment
    # (older output may reference /assets/assets/<file>).
    if asset_path.startswith("assets/"):
        asset_path = asset_path[len("assets/"):]
    file_path = (base / asset_path).resolve()
    if not str(file_path).startswith(str(base.resolve())):
        return HTMLResponse("Forbidden", status_code=403)
    if file_path.is_file():
        return FileResponse(file_path, headers={"Cache-Control": "no-store"})
    return HTMLResponse("Not found", status_code=404)


SHOTS_DIR = Path("output") / ".shots"


@app.get("/source")
async def get_source():
    if not OUTPUT_FILE.is_file():
        return {"html": ""}
    return {"html": OUTPUT_FILE.read_text()}


@app.get("/shots/{shot_path:path}")
async def serve_shot(shot_path: str):
    """Serve screenshot tiles and diff heatmaps from output/.shots/."""
    base = SHOTS_DIR.resolve()
    file_path = (SHOTS_DIR / shot_path).resolve()
    if not str(file_path).startswith(str(base)):
        return HTMLResponse("Forbidden", status_code=403)
    if file_path.is_file():
        return FileResponse(file_path, headers={"Cache-Control": "no-store"})
    return HTMLResponse("Not found", status_code=404)


class CompareRequest(BaseModel):
    url: str
    profile: str = "balanced"


@app.post("/compare")
async def run_compare(req: CompareRequest):
    from browser import friendly_capture_error
    from tools import run_fidelity_comparison

    result = await run_fidelity_comparison(req.url, profile=req.profile)
    if result.get("error"):
        err = result["error"]
        detail = result.get("detail")
        if detail:
            detail = friendly_capture_error(detail) if len(str(detail)) > 80 else detail
        return {
            "error": friendly_capture_error(err) if err == "Could not compare pages." else err,
            "detail": detail,
        }
    return result


# --- Convergence + A/B (Phase 6) ---


@app.get("/convergence")
async def get_convergence(session_id: str | None = None):
    import convergence

    return convergence.get_state(session_id)


class ABRequest(BaseModel):
    url: str
    session_id: str
    profile: str = "balanced"


async def _run_naked_baseline(url: str, profile: str) -> dict:
    """Run a single unguided one-shot generation and score it (A/B baseline).

    Restores the user's current output afterward so the demo result is not
    clobbered by the throwaway baseline build.
    """
    from claude_agent_sdk import ClaudeSDKClient
    from compare import resolve_profile
    from tools import run_fidelity_comparison, set_fidelity_profile

    prof = resolve_profile(profile)
    set_fidelity_profile(prof)
    prior_html = OUTPUT_FILE.read_text() if OUTPUT_FILE.is_file() else None

    async with _agent_lock:
        os.environ.pop("CLAUDECODE", None)
        opts = _build_agent_options(
            tool_subset=["capture_site", "write_html"],
            system_prompt=_NAKED_SYSTEM_PROMPT,
        )
        message = (
            f"Build a one-shot landing-page template for this URL: {url}\n"
            "Call capture_site once, then write_html once. Do not self-check."
        )
        _log("agent", f"A/B baseline start: {url}")
        async with ClaudeSDKClient(options=opts) as client:
            await client.query(message)
            async for _msg in client.receive_response():
                pass

        result = await run_fidelity_comparison(url, profile=prof)

    # Restore the user's loop result so A/B does not destroy it.
    if prior_html is not None:
        OUTPUT_FILE.write_text(prior_html)
    _notify("html_updated")

    if result.get("error"):
        return {"error": result["error"], "detail": result.get("detail")}
    return {"report": result["report"]}


@app.post("/ab")
async def run_ab_baseline(req: ABRequest):
    import convergence

    res = await _run_naked_baseline(req.url, req.profile)
    if res.get("error"):
        return res
    baseline = convergence.set_baseline(req.session_id, res["report"], url=req.url)
    _notify("convergence")
    return {"baseline": baseline}


# --- Output history (Phase 5) ---


class RollbackRequest(BaseModel):
    seq: int


@app.get("/history")
async def get_history():
    from history import list_history

    return {"entries": list_history()}


@app.get("/history/diff")
async def get_history_diff(seq: int | None = None):
    from history import diff

    return {"diff": diff(seq)}


@app.post("/history/rollback")
async def rollback_history(req: RollbackRequest):
    from history import restore

    result = restore(req.seq)
    if result.get("error"):
        return result
    _notify("html_updated")
    return result


@app.post("/history/revert-last")
async def revert_last_history():
    from history import revert_last

    result = revert_last()
    if result.get("error"):
        return result
    _notify("html_updated")
    return result


# --- Design tokens (panel, no LLM) ---


class TokenUpdateRequest(BaseModel):
    updates: dict[str, str]


@app.get("/tokens")
async def get_tokens():
    from tokens import list_tokens_from_html

    if not OUTPUT_FILE.is_file():
        return {"tokens": []}
    html = OUTPUT_FILE.read_text()
    return {"tokens": list_tokens_from_html(html)}


@app.post("/tokens")
async def update_tokens(req: TokenUpdateRequest):
    from history import save_output
    from tokens import list_tokens_from_html, parse_root_vars, patch_root_vars

    if not OUTPUT_FILE.is_file():
        return {"tokens": [], "error": "no output yet"}
    html = OUTPUT_FILE.read_text()
    if not parse_root_vars(html):
        return {"tokens": [], "error": "no :root block in output/index.html"}
    patched = patch_root_vars(html, req.updates)
    save_output(patched, "tokens-panel")
    _notify("html_updated")
    return {"tokens": list_tokens_from_html(patched)}


# --- Chat (agent) ---

_PROFILE_BUILD_RULES = {
    "more_editable": """\
**Fidelity profile: more_editable** — prioritize clean, semantic, easy-to-change code.
- Use semantic tags (`header`, `nav`, `main`, `section`, `footer`, `h1`–`h3`). \
Avoid deep div nesting; do not mirror the source site's machine-generated DOM.
- Match layout, colors, typography, and spacing from screenshots — but keep HTML readable.
- Use CSS variables in `:root`; no inline styles on every element.
- Use styled wordmark placeholders for logos (do not mirror proprietary image files).
- Self-check with `compare_to_target(url, profile="more_editable")`. Low structure score is \
expected and OK; asset_coverage is informational only.""",
    "balanced": """\
**Fidelity profile: balanced** (default) — semantic HTML with strong layout/visual match.
- Prefer semantic tags; add wrapper `div`s only when needed for layout fidelity.
- Match colors, fonts, spacing, and section rhythm from the capture.
- Use CSS variables in `:root`; no frameworks.
- Logo placeholders are OK; asset_coverage is informational only.
- Self-check with `compare_to_target(url, profile="balanced")`. Fix `worst_sections` \
and `gate_failures`; structure score is informational.""",
    "more_faithful": """\
**Fidelity profile: more_faithful** — closest visual match including real assets.
- **Mandatory order**: `capture_site(url)` → `extract_assets(url)` → `write_html`. Never skip \
`extract_assets` in this profile.
- Use **every** entry in manifest `assets` via its `preview_path`:
  - **logo / favicon / hero**: `<img src="/assets/...">`, `<link rel="icon" href="/assets/...">`, \
or `background-image: url("/assets/...")` when the source used a background image.
  - **inline SVG** (manifest `hints.inline_svg` or `type: inline_svg`): reference as \
`<img src="/assets/...-inline-....svg">` — never replace with a text wordmark or emoji.
  - **fonts** (manifest `fonts` / `hints.font_faces`): paste the provided `@font-face` rules into \
`<style>` and set `body` / headings to the mirrored `font-family` names.
- **Forbidden** when manifest has logo or inline_svg: CSS wordmark placeholders, generic icons, \
or "LOGO" text substitutes.
- Match section positions, spacing, colors, and typography as closely as pixels allow.
- Wrapper `div`s are allowed when they improve layout fidelity.
- Prefer a single `<style>` block with `:root` CSS variables.
- Self-check with `compare_to_target(url, profile="more_faithful")`. \
`asset_coverage` is enforced (≥75%) — logo, favicon, hero, and primary font when present.""",
}

_SYSTEM_PROMPT_BASE = """\
You are an AI agent that creates customizable website templates from existing sites.

The user gives you a URL of a site they love. Your job is to recreate it as \
clean, editable HTML/CSS that looks and feels almost exactly like the original — \
same layout, same colors, same typography, same visual rhythm — but with code \
the user can customize.

You have tools to capture screenshots, extract design tokens, compare fidelity \
to the target, write and read HTML, edit individual sections with `edit_section`, \
patch CSS variables, and screenshot your own output. The user sees a live preview \
of your HTML.

**Design tokens (required for every profile):**
- Author exactly one `:root { }` block in `<style>` using these canonical names:
  colors: --color-brand, --color-accent, --color-bg, --color-surface, --color-text, \
--color-muted, --color-border
  typography: --font-base, --font-heading, --text-base, --text-scale, --leading, \
--weight-heading
  shape: --radius, --radius-lg, --shadow
  spacing: --space-unit, --space-section
- Reference `var(--token)` for every color, font-family, font-size, border-radius, \
and key spacing — **no repeated color/font literals** in rules.
- For rebrand follow-ups ("make it purple"), prefer `set_design_token` over rewriting.

**Section anchors (required for every profile):**
- Add stable `data-section` on each major block, e.g. `nav`, `hero`, `features`, `cta`, `footer`.
- Use semantic wrappers (`header`, `section`, `footer`) with `data-section="…"` so partial edits work.
- For follow-up edits ("change the hero"), prefer `edit_section(selector, html)` over `write_html` full rewrites.

When the user gives you a URL, follow this workflow strictly:

1. **Look first** — call `capture_site(url)` before writing any HTML. Then call \
`extract_design_tokens(url)` and use the returned values to seed `:root`. For \
**more_faithful**, also call `extract_assets(url)` and use mirrored files from the manifest.

2. **Build** — call `write_html` with `:root` tokens + `var(--…)` references, \
following the fidelity profile rules below.

3. **Self-check** — call `compare_to_target(url, profile=...)` with the user's profile. \
Read the fidelity report: fix the **named worst_sections** first (not a full rewrite). \
If `gate_failures` lists content/layout issues, fix those before cosmetic tweaks. \
Optionally call `screenshot_output()` when you need a visual sanity check.

4. **Iterate** — repeat steps 2–3 at most 2–3 times. Stop when `verdict` is \
`pass`, or when you hit the iteration cap — then summarize per-axis scores and \
any remaining gaps from `worst_sections`.

For follow-up edits (no new URL), use `read_html`, `edit_section`, or \
`read_design_tokens` for focused changes; optionally `screenshot_output()` to verify.

If `capture_site` returns a DOM-only fallback (no images), use the style JSON \
and text outline; do not invent a generic template.

{profile_rules}
"""


def _build_system_prompt(profile: str) -> str:
    from compare import resolve_profile

    prof = resolve_profile(profile)
    # Do not use str.format() on the base prompt: it contains literal `:root { }`,
    # which Python treats as a format field named " " and raises KeyError(' ').
    return _SYSTEM_PROMPT_BASE.replace(
        "{profile_rules}", _PROFILE_BUILD_RULES[prof]
    )


_agent_lock = asyncio.Lock()


_NAKED_SYSTEM_PROMPT = """\
You are an AI that writes a landing-page template from a URL in ONE shot.

Workflow (do not deviate): call `capture_site(url)` once to look, then call \
`write_html` exactly once with a complete, self-contained HTML document that \
recreates the page's layout, colors, and typography as well as you can.

Do NOT iterate, do NOT self-check, do NOT compare. Produce your single best \
first attempt and stop. This is the unguided baseline.
"""


def _build_agent_options(
    resume_session: str | None = None,
    fidelity_profile: str = "balanced",
    *,
    tool_subset: list[str] | None = None,
    system_prompt: str | None = None,
    stderr: Callable[[str], None] | None = None,
):
    from claude_agent_sdk import ClaudeAgentOptions
    from tools import create_tool_server, TOOL_NAMES, SERVER_NAME

    os.environ.pop("CLAUDECODE", None)

    cs = create_tool_server()
    names = tool_subset if tool_subset is not None else TOOL_NAMES
    mcp_tool_names = [f"mcp__{SERVER_NAME}__{name}" for name in names]
    extra_tools = [] if tool_subset is not None else ["WebFetch", "WebSearch"]

    _log(
        "agent",
        f"options: {len(mcp_tool_names)} tools, "
        f"resume={resume_session or '-'}, profile={fidelity_profile}",
    )

    return ClaudeAgentOptions(
        system_prompt=system_prompt or _build_system_prompt(fidelity_profile),
        permission_mode="acceptEdits",
        model=AGENT_MODEL,
        mcp_servers={SERVER_NAME: cs},
        allowed_tools=mcp_tool_names + extra_tools,
        disallowed_tools=[
            "Bash", "Write", "Edit", "Read", "Glob", "Grep",
            "Agent", "Skill", "ToolSearch",
            "NotebookEdit", "TodoWrite",
        ],
        max_turns=30,
        max_buffer_size=8 * 1024 * 1024,
        cwd=str(Path.cwd()),
        continue_conversation=False,
        resume=resume_session,
        stderr=stderr,
    )


def _push_chat(data: dict):
    encoded = json.dumps({"version": _version, "event": "chat", "chat": data})
    # text/tool/done are already logged inline; only surface control events here.
    dtype = data.get("type")
    if dtype == "session":
        _log("chat", f"session {data.get('session_id', '')}")
    elif dtype == "error":
        _log("chat", f"error: {str(data.get('text', ''))[:80]}")
    for q in list(_subscribers):
        try:
            q.put_nowait(encoded)
        except asyncio.QueueFull:
            pass


def _log(tag: str, line: str, skipped: int = 0) -> None:
    """Tagged stderr log line. `skipped` collapses preceding noise events."""
    import sys

    skip = f" \033[2m(skip {skipped})\033[0m" if skipped else ""
    print(f"[{tag}]{skip} {line}".rstrip(), file=sys.stderr)


def _tool_arg_hint(tool_input) -> str:
    """Short, human-readable hint of a tool call's key argument."""
    if not isinstance(tool_input, dict):
        return ""
    for key in ("url", "selector", "name", "profile", "path"):
        val = tool_input.get(key)
        if val:
            return f" {key}={str(val)[:60]}"
    return ""


def _format_agent_error(exc: BaseException) -> str:
    """Human-readable error for SSE; many SDK errors have an empty str()."""
    name = type(exc).__name__
    msg = (str(exc) or "").strip()
    if msg:
        return f"{name}: {msg}"
    rep = repr(exc).strip()
    if rep and rep not in (name + "()", f"{name}()"):
        return f"{name}: {rep}"
    return f"{name} (no message — check server terminal for traceback)"


_agent_busy = False


# Simple session metadata store: {session_id: {url, created}}
_sessions: dict[str, dict] = {}
SESSIONS_META_FILE = Path("data/sessions.json")


def _load_sessions():
    global _sessions
    if SESSIONS_META_FILE.exists():
        _sessions = json.loads(SESSIONS_META_FILE.read_text())


def _save_sessions():
    SESSIONS_META_FILE.parent.mkdir(parents=True, exist_ok=True)
    SESSIONS_META_FILE.write_text(json.dumps(_sessions, indent=2))


class ChatRequest(BaseModel):
    message: str
    url: str | None = None
    session_id: str | None = None
    fidelity_profile: str = "balanced"


@app.get("/fidelity/profiles")
async def fidelity_profiles():
    from compare import load_config

    cfg = load_config()
    profiles = cfg.get("profiles", {})
    return {
        "default": "balanced",
        "profiles": [
            {
                "id": pid,
                "label": pdata.get("label", pid),
                "description": pdata.get("description", ""),
            }
            for pid, pdata in profiles.items()
            if pid in ("more_editable", "balanced", "more_faithful")
        ],
    }


@app.get("/chat/status")
async def chat_status():
    return {"busy": _agent_busy}


@app.get("/chat/session/{session_id}/resumable")
async def session_resumable(session_id: str):
    return {"resumable": _can_resume_session(session_id)}


_background_tasks: set = set()


@app.post("/chat")
async def chat(req: ChatRequest):
    task = asyncio.create_task(
        _run_agent(
            req.message,
            url=req.url,
            session_id=req.session_id,
            fidelity_profile=req.fidelity_profile,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    task.add_done_callback(_task_done)
    return {"status": "started"}


def _task_done(task):
    import sys
    import traceback

    try:
        exc = task.exception()
    except asyncio.CancelledError:
        return
    if exc is None:
        return
    _log("error", f"task exception: {exc!r}")
    traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)
    _push_chat({"type": "error", "text": _format_agent_error(exc)})


def _is_stale_session_error(exc: BaseException, stderr_text: str, session_id: str | None) -> bool:
    """Detect Claude CLI resume failures (message often only appears on stderr)."""
    if not session_id:
        return False
    blob = f"{exc!s} {exc!r} {stderr_text}".lower()
    if "no conversation found" in blob or "session not found" in blob:
        return True
    # ProcessError is generic; paired with a resume id + exit 1 it is almost always stale.
    if type(exc).__name__ == "ProcessError" and "exit code 1" in blob:
        return True
    return False


async def _run_agent(
    message: str,
    url: str | None = None,
    session_id: str | None = None,
    fidelity_profile: str = "balanced",
):
    global _agent_busy
    async with _agent_lock:
        _agent_busy = True
        stderr_lines: list[str] = []
        try:
            await _run_agent_turn(
                message,
                url=url,
                session_id=session_id,
                fidelity_profile=fidelity_profile,
                stderr_lines=stderr_lines,
            )
        except Exception as e:
            if _is_stale_session_error(e, "\n".join(stderr_lines), session_id):
                _log("agent", f"stale session {session_id}, starting fresh")
                _push_chat({"type": "session_reset", "text": "Previous chat session expired. Starting fresh."})
                try:
                    await _run_agent_turn(
                        message,
                        url=url,
                        session_id=None,
                        fidelity_profile=fidelity_profile,
                        stderr_lines=stderr_lines,
                    )
                    return
                except Exception as retry_exc:
                    e = retry_exc
            _log("error", f"agent: {e!r}")
            _push_chat({"type": "error", "text": _format_agent_error(e)})
        finally:
            _agent_busy = False
            import convergence
            run = convergence.end_run()
            if run is not None:
                _notify("convergence")


async def _run_agent_turn(
    message: str,
    url: str | None = None,
    session_id: str | None = None,
    fidelity_profile: str = "balanced",
    *,
    stderr_lines: list[str] | None = None,
):
    import convergence
    from claude_agent_sdk import ClaudeSDKClient
    from compare import resolve_profile
    from tools import set_fidelity_profile

    if session_id and not _can_resume_session(session_id):
        _log("agent", f"session {session_id} not on disk, starting fresh")
        _push_chat({"type": "session_reset", "text": "Previous chat session expired. Starting fresh."})
        session_id = None

    prof = set_fidelity_profile(fidelity_profile)
    convergence.begin_run(url, prof, session_id=session_id)
    os.environ.pop("CLAUDECODE", None)

    def _on_stderr(line: str) -> None:
        if stderr_lines is not None:
            stderr_lines.append(line)

    opts = _build_agent_options(
        resume_session=session_id,
        fidelity_profile=prof,
        stderr=_on_stderr,
    )

    _log("agent", f"start (resume={session_id or '-'}): {message[:80]}")

    seen_texts = set()
    session_pushed = False

    # Snapshot existing sessions to detect the new one
    sdir = _get_session_dir()
    existing_files = set(sdir.glob("*.jsonl")) if sdir else set()

    async with ClaudeSDKClient(options=opts) as client:
        await client.query(message)

        # Detect new session file immediately after query starts
        if sdir:
            for _ in range(10):
                current = set(sdir.glob("*.jsonl"))
                new_files = current - existing_files
                if new_files:
                    new_sid = new_files.pop().stem
                    session_pushed = True
                    convergence.set_active_session(new_sid)
                    _push_chat({"type": "session", "session_id": new_sid})
                    if new_sid not in _sessions:
                        from datetime import datetime
                        _sessions[new_sid] = {
                            "url": url or "",
                            "created": datetime.now().isoformat(),
                            "fidelity_profile": prof,
                        }
                        _save_sessions()
                    break
                await asyncio.sleep(0.1)

        noise_count = 0
        last_agent_text = ""

        async for msg in client.receive_response():
            if hasattr(msg, "content"):
                for block in getattr(msg, "content", []):
                    if hasattr(block, "text") and block.text:
                        text = block.text.strip()
                        if text:
                            last_agent_text = text
                        if text and text not in seen_texts:
                            seen_texts.add(text)
                            _push_chat({"type": "text", "text": text})
                            _log("text", text[:100], skipped=noise_count)
                            noise_count = 0
                    elif getattr(block, "type", None) == "tool_use" or hasattr(
                        block, "name"
                    ):
                        tool = getattr(block, "name", "?")
                        tool = tool.split("__")[-1]
                        hint = _tool_arg_hint(getattr(block, "input", None))
                        convergence.record_decision(
                            tool,
                            getattr(block, "input", None),
                            agent_text=last_agent_text,
                        )
                        _log("tool", f"{tool}{hint}", skipped=noise_count)
                        noise_count = 0
                    elif getattr(block, "type", None) == "tool_result":
                        noise_count += 1
                    else:
                        noise_count += 1
            else:
                # SystemMessage / RateLimitEvent / heartbeats — just count.
                noise_count += 1

            if hasattr(msg, "result") and msg.result:
                text = msg.result.strip()
                if text and text not in seen_texts:
                    seen_texts.add(text)
                    _push_chat({"type": "result", "text": text})

            # Fallback: get session ID from ResultMessage
            if not session_pushed and hasattr(msg, "session_id") and msg.session_id:
                session_pushed = True
                sid = msg.session_id
                convergence.set_active_session(sid)
                _push_chat({"type": "session", "session_id": sid})
                if sid not in _sessions:
                    from datetime import datetime
                    _sessions[sid] = {
                        "url": url or "",
                        "created": datetime.now().isoformat(),
                        "fidelity_profile": prof,
                    }
                    _save_sessions()

    _log("agent", "done", skipped=noise_count)
    _push_chat({"type": "done"})


@app.get("/chat/history/{session_id}")
async def chat_history(session_id: str):
    """Load chat history from the Claude session JSONL file."""
    meta = _sessions.get(session_id) or {}
    sdir = _get_session_dir()
    if not sdir:
        return {"messages": [], "url": meta.get("url"), "fidelity_profile": meta.get("fidelity_profile")}
    jsonl_path = sdir / f"{session_id}.jsonl"
    if not jsonl_path.exists():
        return {"messages": [], "url": meta.get("url"), "fidelity_profile": meta.get("fidelity_profile")}

    messages = []
    for line in jsonl_path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        if entry.get("type") == "user":
            content = entry.get("message", {}).get("content", "")
            if isinstance(content, str) and content:
                messages.append({"role": "user", "text": content})
        elif entry.get("type") == "assistant":
            blocks = entry.get("message", {}).get("content", [])
            for block in blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "").strip()
                    if text:
                        messages.append({"role": "assistant", "text": text})

    return {
        "messages": messages,
        "url": meta.get("url"),
        "fidelity_profile": meta.get("fidelity_profile"),
    }


@app.get("/chat/sessions")
async def list_sessions():
    return {"sessions": [{"id": k, **v} for k, v in _sessions.items()]}


@app.post("/chat/reset-all")
async def reset_all_sessions():
    sdir = _get_session_dir()
    if sdir:
        for f in sdir.glob("*.jsonl"):
            f.unlink()
    if OUTPUT_FILE.exists():
        OUTPUT_FILE.unlink()
    _sessions.clear()
    _save_sessions()
    _notify("html_updated")
    return {"reset": True}


if __name__ == "__main__":
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    print(f"\nWebsite builder running on http://localhost:{args.port}\n")
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=args.port,
        reload=True,
        reload_includes=["*.py", "viewer.html"],
        reload_excludes=["output/*", "data/*"],
        timeout_graceful_shutdown=1,
    )
