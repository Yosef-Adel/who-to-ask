import asyncio
import os
import shlex
import logging
from typing import Any, Dict, List, Optional, Tuple  # keep all imports

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

logging.basicConfig(level=logging.INFO)

# --- Persistent loop + MCP/tools (initialize at startup) ---
LOOP = asyncio.new_event_loop()
asyncio.set_event_loop(LOOP)

MCP: Optional[McpWrapper] = None
TOOLS: List[Dict[str, Any]] = []


def build_messages(history: List[Dict[str, str]]):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history)
    return messages


def respond(user_input: str, history: List[Dict[str, str]]):
    async def _ask():
        # history already includes previous turns; append user turn for this request
        history.append({"role": "user", "content": user_input})

        msgs = build_messages(history)
        final, _ = await run_turn_with_tools(
            MODEL, MCP, msgs, TOOLS, timeout_s=TIMEOUT
        )

        # append assistant turn and return updated history for Chatbot(type="messages")
        history.append({"role": "assistant", "content": final})
        return history

    try:
        return LOOP.run_until_complete(_ask())
    except Exception as e:
        logging.exception("Error during respond")
        history.append({"role": "assistant", "content": f"Error: {e}"})
        return history


async def init_mcp():
    global MCP, TOOLS
    parts = shlex.split(SERVER_CMD)
    cmd, args = parts[0], parts[1:]
    MCP = McpWrapper(command=cmd, args=args)
    await MCP.__aenter__()
    mcp_tools = await MCP.list_tools()
    TOOLS = as_ollama_tools(mcp_tools)
    logging.info("MCP initialized and tools loaded: %s", [t.get("name") for t in TOOLS])


async def shutdown_mcp():
    global MCP
    if MCP is not None:
        await MCP.__aexit__(None, None, None)
        MCP = None
        logging.info("MCP shut down")


def main():
    # Initialize MCP once at startup
    LOOP.run_until_complete(init_mcp())

    with gr.Blocks(title="Who To Ask") as demo:
        chatbot = gr.Chatbot(type="messages")
        msg = gr.Textbox(placeholder="Ask about a file, commit, or owner...")
        msg.submit(respond, [msg, chatbot], chatbot)
        msg.submit(lambda: "", None, msg)

    try:
        demo.launch()
    finally:
        # Ensure clean shutdown
        LOOP.run_until_complete(shutdown_mcp())
        LOOP.close()


if __name__ == "__main__":
    main()
