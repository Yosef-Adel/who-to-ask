import asyncio
import os
import shlex
import logging
from typing import List, Tuple

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


def build_messages(history: List[Tuple[str, str]], user_input: str):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for user, assistant in history:
        messages.append({"role": "user", "content": user})
        messages.append({"role": "assistant", "content": assistant})
    messages.append({"role": "user", "content": user_input})
    return messages


def respond(user_input, history):
    async def _ask():
        parts = shlex.split(SERVER_CMD)
        cmd, args = parts[0], parts[1:]
        async with McpWrapper(command=cmd, args=args) as mcp:
            mcp_tools = await mcp.list_tools()
            tools = as_ollama_tools(mcp_tools)
            msgs = build_messages(history, user_input)
            final, _ = await run_turn_with_tools(
                MODEL, mcp, msgs, tools, timeout_s=TIMEOUT
            )
            return final
    try:
        return asyncio.run(_ask())
    except Exception as e:
        logging.exception("Error during respond")
        return f"Error: {e}"


def main():
    chat = gr.ChatInterface(respond, title="Who To Ask")
    chat.launch()


if __name__ == "__main__":
    main()
