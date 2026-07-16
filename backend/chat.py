"""Portfolio AI chat — Claude Agent SDK glue.

The SDK drives the local Claude Code CLI, which authenticates with the
machine's Claude subscription login. No API key is used or needed; a stray
ANTHROPIC_API_KEY would silently switch billing to the pay-per-token API,
so the env passed to the CLI is explicitly scrubbed. This feature only
works on a machine where Claude Code is logged in.
"""

import os
import tempfile
from pathlib import Path

from claude_agent_sdk import (
    query,
    ClaudeAgentOptions,
    AssistantMessage,
    TextBlock,
    ResultMessage,
)

PERSONA = (
    "You are a portfolio analysis assistant inside StocksDetails, a personal "
    "portfolio tracker. The user's portfolio snapshot, taken when this chat "
    "session started, is provided in <portfolio_snapshot>. Interpret the data, "
    "surface notable patterns and risks (concentration, holdings lagging their "
    "benchmarks, tax implications), and answer follow-up questions "
    "conversationally. Be direct and quantitative — cite the numbers you use. "
    "In real_returns, real_annualized_pct is the holding's annualized return "
    "after CPI inflation; spy_annualized_pct is what SPY returned over the same "
    "period; symbols in needs_date have no purchase date and are excluded. "
    "This is educational analysis, not licensed financial advice — say so when "
    "your answer verges on buy/sell guidance. If data looks missing or stale, "
    "point it out rather than guessing."
)

# Run the CLI outside the repo so it never picks up project files or CLAUDE.md
_SCRATCH = Path(tempfile.gettempdir()) / "stocksdetails-chat"
_SCRATCH.mkdir(exist_ok=True)


def _clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    return env


def _friendly_error(e: Exception) -> str:
    text = str(e).lower()
    if any(s in text for s in ("login", "logged", "auth", "credential", "api key")):
        return ("Claude Code doesn't appear to be logged in on this machine — "
                "run `claude` in a terminal and sign in, then try again.")
    if "not found" in text or "no such file" in text:
        return ("Claude Code CLI not found — the chat feature needs Claude Code "
                "installed and logged in on this machine.")
    return f"Chat failed: {e}"


async def stream_chat(message: str, session_id: str | None, context: str | None):
    """Yield {"text": ...} chunks, then {"done": True, "session_id": ...}.

    `context` (the portfolio snapshot JSON) is re-sent as system prompt on
    every turn of the session, so resumed turns keep the original snapshot.
    """
    system_prompt = PERSONA
    if context:
        system_prompt += "\n\n<portfolio_snapshot>\n" + context + "\n</portfolio_snapshot>"

    options = ClaudeAgentOptions(
        system_prompt=system_prompt,
        allowed_tools=[],       # tool-less: the agent only reads the snapshot
        max_turns=1,            # no tools -> one assistant turn per request
        setting_sources=[],     # don't load any CLAUDE.md / user settings
        cwd=str(_SCRATCH),
        resume=session_id,
        env=_clean_env(),
    )

    try:
        result_session = None
        async for msg in query(prompt=message, options=options):
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock):
                        yield {"text": block.text}
            elif isinstance(msg, ResultMessage):
                result_session = msg.session_id
        yield {"done": True, "session_id": result_session}
    except Exception as e:
        yield {"error": _friendly_error(e), "done": True}
