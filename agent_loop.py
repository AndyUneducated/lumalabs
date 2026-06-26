"""Claude agent run loop and SDK options (extracted from server.py)."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from pathlib import Path

from builder_config import AGENT_MODEL, OUTPUT_FILE, use_cli_oauth_auth
from prompts import NAKED_SYSTEM_PROMPT, build_system_prompt


def format_agent_error(exc: BaseException) -> str:
    name = type(exc).__name__
    msg = (str(exc) or "").strip()
    if msg:
        return f"{name}: {msg}"
    rep = repr(exc).strip()
    if rep and rep not in (name + "()", f"{name}()"):
        return f"{name}: {rep}"
    return f"{name} (no message — check server terminal for traceback)"


def _tool_arg_hint(tool_input) -> str:
    if not isinstance(tool_input, dict):
        return ""
    for key in ("url", "selector", "name", "profile", "path"):
        val = tool_input.get(key)
        if val:
            return f" {key}={str(val)[:60]}"
    return ""


def _is_stale_session_error(exc: BaseException, stderr_text: str, session_id: str | None) -> bool:
    if not session_id:
        return False
    blob = f"{exc!s} {exc!r} {stderr_text}".lower()
    if "no conversation found" in blob or "session not found" in blob:
        return True
    if type(exc).__name__ == "ProcessError" and "exit code 1" in blob:
        return True
    return False


def _build_agent_options(
    resume_session: str | None = None,
    fidelity_profile: str = "balanced",
    *,
    tool_subset: list[str] | None = None,
    system_prompt: str | None = None,
    stderr: Callable[[str], None] | None = None,
):
    from claude_agent_sdk import ClaudeAgentOptions
    from tools import TOOL_NAMES, SERVER_NAME, create_tool_server

    import server_state as st

    use_cli_oauth_auth()

    cs = create_tool_server()
    names = tool_subset if tool_subset is not None else TOOL_NAMES
    mcp_tool_names = [f"mcp__{SERVER_NAME}__{name}" for name in names]
    extra_tools = [] if tool_subset is not None else ["WebFetch", "WebSearch"]

    st.log(
        "agent",
        f"options: {len(mcp_tool_names)} tools, "
        f"resume={resume_session or '-'}, profile={fidelity_profile}",
    )

    return ClaudeAgentOptions(
        system_prompt=system_prompt or build_system_prompt(fidelity_profile),
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


async def run_naked_baseline(url: str, profile: str) -> dict:
    """Unguided one-shot build + score for A/B; restores output/index.html after."""
    from claude_agent_sdk import ClaudeSDKClient
    from compare import resolve_profile
    from tools import run_fidelity_comparison, set_fidelity_profile

    import server_state as st

    prof = resolve_profile(profile)
    set_fidelity_profile(prof)
    prior_html = OUTPUT_FILE.read_text() if OUTPUT_FILE.is_file() else None

    async with st.agent_lock:
        use_cli_oauth_auth()
        opts = _build_agent_options(
            tool_subset=["capture_site", "write_html"],
            system_prompt=NAKED_SYSTEM_PROMPT,
        )
        message = (
            f"Build a one-shot landing-page template for this URL: {url}\n"
            "Call capture_site once, then write_html once. Do not self-check."
        )
        st.log("agent", f"A/B baseline start: {url}")
        async with ClaudeSDKClient(options=opts) as client:
            await client.query(message)
            async for _msg in client.receive_response():
                pass

        result = await run_fidelity_comparison(url, profile=prof)

    if prior_html is not None:
        OUTPUT_FILE.write_text(prior_html)
    st.notify("html_updated")

    if result.get("error"):
        return {"error": result["error"], "detail": result.get("detail")}
    return {"report": result["report"]}


async def run_agent_turn(
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

    import server_state as st

    if session_id and not st.can_resume_session(session_id):
        st.log("agent", f"session {session_id} not on disk, starting fresh")
        st.push_chat({"type": "session_reset", "text": "Previous chat session expired. Starting fresh."})
        session_id = None

    prof = set_fidelity_profile(fidelity_profile)
    convergence.begin_run(url, prof, session_id=session_id)
    use_cli_oauth_auth()

    def _on_stderr(line: str) -> None:
        if stderr_lines is not None:
            stderr_lines.append(line)

    opts = _build_agent_options(
        resume_session=session_id,
        fidelity_profile=prof,
        stderr=_on_stderr,
    )

    st.log("agent", f"start (resume={session_id or '-'}): {message[:80]}")

    seen_texts = set()
    session_pushed = False

    sdir = st.get_session_dir()
    existing_files = set(sdir.glob("*.jsonl")) if sdir else set()

    async with ClaudeSDKClient(options=opts) as client:
        await client.query(message)

        if sdir:
            for _ in range(10):
                current = set(sdir.glob("*.jsonl"))
                new_files = current - existing_files
                if new_files:
                    new_sid = new_files.pop().stem
                    session_pushed = True
                    convergence.set_active_session(new_sid)
                    st.push_chat({"type": "session", "session_id": new_sid})
                    if new_sid not in st.session_store:
                        from datetime import datetime

                        st.session_store[new_sid] = {
                            "url": url or "",
                            "created": datetime.now().isoformat(),
                            "fidelity_profile": prof,
                        }
                        st.save_sessions()
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
                            st.push_chat({"type": "text", "text": text})
                            st.log("text", text[:100], skipped=noise_count)
                            noise_count = 0
                    elif getattr(block, "type", None) == "tool_use" or hasattr(block, "name"):
                        tool = getattr(block, "name", "?")
                        tool = tool.split("__")[-1]
                        hint = _tool_arg_hint(getattr(block, "input", None))
                        convergence.record_decision(
                            tool,
                            getattr(block, "input", None),
                            agent_text=last_agent_text,
                        )
                        st.log("tool", f"{tool}{hint}", skipped=noise_count)
                        noise_count = 0
                    elif getattr(block, "type", None) == "tool_result":
                        noise_count += 1
                    else:
                        noise_count += 1
            else:
                noise_count += 1

            if hasattr(msg, "result") and msg.result:
                text = msg.result.strip()
                if text and text not in seen_texts:
                    seen_texts.add(text)
                    st.push_chat({"type": "result", "text": text})

            if not session_pushed and hasattr(msg, "session_id") and msg.session_id:
                session_pushed = True
                sid = msg.session_id
                convergence.set_active_session(sid)
                st.push_chat({"type": "session", "session_id": sid})
                if sid not in st.session_store:
                    from datetime import datetime

                    st.session_store[sid] = {
                        "url": url or "",
                        "created": datetime.now().isoformat(),
                        "fidelity_profile": prof,
                    }
                    st.save_sessions()

    st.log("agent", "done", skipped=noise_count)
    st.push_chat({"type": "done"})


async def run_agent(
    message: str,
    url: str | None = None,
    session_id: str | None = None,
    fidelity_profile: str = "balanced",
):
    import convergence

    import server_state as st

    async with st.agent_lock:
        st.agent_busy = True
        stderr_lines: list[str] = []
        try:
            await run_agent_turn(
                message,
                url=url,
                session_id=session_id,
                fidelity_profile=fidelity_profile,
                stderr_lines=stderr_lines,
            )
        except Exception as e:
            if _is_stale_session_error(e, "\n".join(stderr_lines), session_id):
                st.log("agent", f"stale session {session_id}, starting fresh")
                st.push_chat({"type": "session_reset", "text": "Previous chat session expired. Starting fresh."})
                try:
                    await run_agent_turn(
                        message,
                        url=url,
                        session_id=None,
                        fidelity_profile=fidelity_profile,
                        stderr_lines=stderr_lines,
                    )
                    return
                except Exception as retry_exc:
                    e = retry_exc
            st.log("error", f"agent: {e!r}")
            st.push_chat({"type": "error", "text": format_agent_error(e)})
        finally:
            st.agent_busy = False
            run = convergence.end_run()
            if run is not None:
                st.notify("convergence")
