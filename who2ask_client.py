#!/usr/bin/env python3
import argparse
import asyncio
import json
import os
import shlex
import sys
from typing import Any, Dict, List, Optional, Tuple

import requests

# --- MCP client (official SDK) ---
from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client  # command + args
from rich.console import Console
from rich.table import Table

console = Console()


# ---------------------------
# Ollama chat with tools
# ---------------------------
def ollama_chat(
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    base_url: str = "http://localhost:11434",
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"model": model, "messages": messages, "stream": False}
    if tools:
        payload["tools"] = tools
    r = requests.post(f"{base_url}/api/chat", json=payload, timeout=600)
    r.raise_for_status()
    return r.json()


def extract_tool_calls(resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    msg = resp.get("message", {})
    tcs = msg.get("tool_calls") or []
    for i, c in enumerate(tcs):
        c.setdefault("id", f"call_{i}")
    return tcs


# ---------------------------
# MCP wrapper (stdio)
# ---------------------------
class McpWrapper:
    def __init__(self, command: str, args: List[str]):
        self.params = StdioServerParameters(command=command, args=args)
        self._ctx = None
        self.session: Optional[ClientSession] = None

    async def __aenter__(self):
        self._ctx = stdio_client(self.params)
        read, write = await self._ctx.__aenter__()
        self.session = ClientSession(read, write)
        await self.session.__aenter__()
        await self.session.initialize()
        return self

    async def __aexit__(self, et, ev, tb):
        if self.session:
            await self.session.__aexit__(et, ev, tb)
        if self._ctx:
            await self._ctx.__aexit__(et, ev, tb)

    async def list_tools(self) -> List[Dict[str, Any]]:
        resp = await self.session.list_tools()
        tools = []
        for t in resp.tools:
            schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema", None)
            if not isinstance(schema, dict):
                try:
                    schema = json.loads(json.dumps(schema))
                except Exception:
                    schema = {"type": "object"}
            tools.append(
                {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": schema or {"type": "object"},
                }
            )
        return tools

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        result = await self.session.call_tool(name, arguments)
        # Normalize common FastMCP return shapes
        if hasattr(result, "content") and isinstance(result.content, list):
            texts = []
            for c in result.content:
                text = getattr(c, "text", None) or (
                    c.get("text") if isinstance(c, dict) else None
                )
                if text:
                    texts.append(text)
            joined = "\n".join(texts)
            try:
                return json.loads(joined)
            except Exception:
                return joined
        if hasattr(result, "model_dump"):
            return result.model_dump()
        try:
            return json.loads(json.dumps(result, default=str))
        except Exception:
            return str(result)


# ---------------------------
# Convert MCP tools -> Ollama tools (OpenAI-style)
# ---------------------------
def as_ollama_tools(mcp_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object"}),
            },
        }
        for t in mcp_tools
    ]


def ensure_json(x: Any) -> str:
    try:
        return json.dumps(x, ensure_ascii=False)
    except Exception:
        return str(x)


# ---------------------------
# Agent loop: tools ↔ MCP
# ---------------------------
async def run_turn_with_tools(
    model: str,
    mcp: McpWrapper,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    timeout_s: int,
    max_loops: int = 6,
) -> Tuple[str, List[Dict[str, Any]]]:
    seen = set()  # dedupe identical tool calls within a turn

    for _ in range(max_loops):
        resp = ollama_chat(model, messages, tools)
        msg = resp.get("message", {})
        content = msg.get("content") or ""
        tool_calls = extract_tool_calls(resp)

        if tool_calls:
            for call in tool_calls:
                fn = (call.get("function") or {}).get("name")
                raw = (call.get("function") or {}).get("arguments")

                # Accept dict OR JSON string
                if isinstance(raw, dict):
                    args = raw
                elif isinstance(raw, str):
                    try:
                        args = json.loads(raw)
                    except Exception:
                        args = {}
                else:
                    args = {}

                # Deduplicate
                key = (fn, json.dumps(args, sort_keys=True))
                if key in seen:
                    console.print(
                        f"[yellow]↻ skipping duplicate call {fn}({args})[/yellow]"
                    )
                    continue
                seen.add(key)

                console.print(f"[bold cyan]→ tool:[/bold cyan] {fn}({args})")
                try:
                    result = await asyncio.wait_for(
                        mcp.call_tool(fn, args), timeout=timeout_s
                    )
                except asyncio.TimeoutError:
                    result = {"error": "timeout", "hint": f"tool exceeded {timeout_s}s"}
                except Exception as e:
                    result = {"error": f"{type(e).__name__}: {e}"}

                messages.append(
                    {
                        "role": "tool",
                        "name": fn,
                        "tool_call_id": call.get("id"),
                        "content": ensure_json(result),
                    }
                )
            continue

        if content.strip():
            messages.append({"role": "assistant", "content": content})
            return content, messages

        break

    messages.append({"role": "assistant", "content": "(no response)"})
    return "(no response)", messages


# ---------------------------
# Pretty table if JSON ranked list comes back
# ---------------------------
def maybe_render_people(text: str):
    try:
        data = json.loads(text)
        if (
            isinstance(data, list)
            and data
            and isinstance(data[0], dict)
            and "author" in data[0]
        ):
            table = Table(title="Top People to Ask")
            table.add_column("#", justify="right")
            table.add_column("Author")
            table.add_column("Score", justify="right")
            table.add_column("Target", justify="right")
            table.add_column("Recent", justify="right")
            for i, item in enumerate(data[:5], 1):
                bd = item.get("breakdown", {})
                table.add_row(
                    str(i),
                    item.get("author", "?"),
                    str(item.get("score", "")),
                    str(bd.get("target_lines", "")),
                    str(bd.get("target_recent", "")),
                )
            console.print(table)
            return
    except Exception:
        pass
    console.print(text)


SYSTEM_PROMPT = (
    "You are Who-to-Ask, a local-first repo helper. "
    "You have callable tools via MCP (usage_based_contributors, top_contributors, search_importers). "
    "When the user mentions a file path, prefer calling tools to gather evidence (contributors, importers) "
    "before answering. If using usage_based_contributors and the repo is large, pass max_importers=200. "
    "Return a concise answer with names plus why (files/lines/recency)."
)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=os.getenv("OLLAMA_MODEL", "qwen3:4b"))
    ap.add_argument(
        "--server-cmd",
        required=True,
        help='Command to launch the MCP server, e.g. "python who_to_ask_server.py"',
    )
    ap.add_argument("--timeout", type=int, default=120, help="Per-tool timeout seconds")
    args = ap.parse_args()

    parts = shlex.split(args.server_cmd)
    cmd, cmd_args = parts[0], parts[1:]

    async with McpWrapper(command=cmd, args=cmd_args) as mcp:
        mcp_tools = await mcp.list_tools()
        tools = as_ollama_tools(mcp_tools)
        console.print(
            f"[green]Connected. {len(tools)} tools available from MCP server.[/green]"
        )
        console.print("[dim]Type 'exit' to quit.[/dim]\n")

        messages: List[Dict[str, Any]] = [{"role": "system", "content": SYSTEM_PROMPT}]

        while True:
            try:
                user = input("you> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if user.lower() in {"exit", "quit"}:
                break

            messages.append({"role": "user", "content": user})
            final, messages = await run_turn_with_tools(
                args.model, mcp, messages, tools, timeout_s=args.timeout
            )
            maybe_render_people(final)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
