import asyncio
import os
import shlex
from typing import List, Dict

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


def build_messages(history: List[Dict[str, str]]):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    return messages


def respond(user_input, history):
    async def _ask():
        parts = shlex.split(SERVER_CMD)
        cmd, args = parts[0], parts[1:]
        async with McpWrapper(command=cmd, args=args) as mcp:
            mcp_tools = await mcp.list_tools()
            tools = as_ollama_tools(mcp_tools)
            history.append({"role": "user", "content": user_input})
            msgs = build_messages(history)
            final, _ = await run_turn_with_tools(
                MODEL, mcp, msgs, tools, timeout_s=TIMEOUT
            )
            history.append({"role": "assistant", "content": final})
            return history

    return asyncio.run(_ask())


def main():
    with gr.Blocks(title="Who To Ask") as demo:
        chatbot = gr.Chatbot(type="messages")
        msg = gr.Textbox()
        msg.submit(respond, [msg, chatbot], chatbot)
        msg.submit(lambda: "", None, msg)
    demo.launch()


if __name__ == "__main__":
    main()
