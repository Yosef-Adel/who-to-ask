import asyncio
import os
import shlex
from typing import Any, Dict, List, Optional, Tuple

import gradio as gr

from who2ask_client import (
    McpWrapper,
    as_ollama_tools,
    run_turn_with_tools,
    SYSTEM_PROMPT,
)

MODEL = os.getenv("OLLAMA_MODEL", "qwen3:4b")
SERVER_CMD = os.getenv("WHO2ASK_SERVER_CMD", "python who_to_ask_server.py")
TIMEOUT = int(os.getenv("WHO2ASK_TIMEOUT", "120"))


LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)

MCP: Optional[McpWrapper] = None
TOOLS: List[Dict[str, Any]] = []


def build_messages(history: List[Tuple[str, str]], user_input: str):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for user, assistant in history:
        messages.append({"role": "user", "content": user})
        messages.append({"role": "assistant", "content": assistant})
    messages.append({"role": "user", "content": user_input})
    return messages


def respond(user_input, history):
    async def _ask():
        msgs = build_messages(history, user_input)
        final, _ = await run_turn_with_tools(
            MODEL, MCP, msgs, TOOLS, timeout_s=TIMEOUT
        )
        return final

    return LOOP.run_until_complete(_ask())


async def init_mcp():
    global MCP, TOOLS
    parts = shlex.split(SERVER_CMD)
    cmd, args = parts[0], parts[1:]
    MCP = McpWrapper(command=cmd, args=args)
    await MCP.__aenter__()
    mcp_tools = await MCP.list_tools()
    TOOLS = as_ollama_tools(mcp_tools)


async def shutdown_mcp():
    global MCP
    if MCP is not None:
        await MCP.__aexit__(None, None, None)
        MCP = None


def main():
    LOOP.run_until_complete(init_mcp())
    chat = gr.ChatInterface(respond, title="Who To Ask")
    try:
        chat.launch()
    finally:
        LOOP.run_until_complete(shutdown_mcp())
        LOOP.close()


if __name__ == "__main__":
    main()
