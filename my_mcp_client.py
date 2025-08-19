import json
import subprocess
import sys

import ollama
import os


def send_msg(proc, obj):
    """Send JSON-RPC message to MCP server."""
    data = json.dumps(obj).encode("utf-8")
    header = f"Content-Length: {len(data)}\r\n\r\n".encode("utf-8")
    proc.stdin.write(header + data)
    proc.stdin.flush()
    print(f"\n>>> SENT: {obj}")


def read_msg(proc):
    """Read JSON-RPC message from MCP server."""
    headers = {}
    while True:
        line = proc.stdout.readline().decode("utf-8")
        if not line:
            return None  # process ended
        if line in ("\r\n", "\n", ""):
            break
        k, v = line.split(":", 1)
        headers[k.strip().lower()] = v.strip()
    length = int(headers.get("content-length", "0"))
    if length == 0:
        return None
    body = proc.stdout.read(length).decode("utf-8")
    msg = json.loads(body)
    print(f"<<< RECEIVED: {msg}\n")
    return msg


# ---- Launch MCP server ----
# Use the current interpreter and resolve the server path relative to this file
server_path = os.path.join(os.path.dirname(__file__), "who_to_ask_server.py")
server_cmd = [sys.executable, server_path]
proc = subprocess.Popen(
    server_cmd,
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=sys.stderr,  # MCP logs visible in terminal
    bufsize=0,
)

# ---- Initialize ----
send_msg(
    proc,
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2024-11-05", "capabilities": {}},
    },
)
read_msg(proc)

# ---- List tools ----
send_msg(proc, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
tools_msg = read_msg(proc)
tools = tools_msg.get("result", {}).get("tools", [])
print("\nAvailable tools:", json.dumps(tools, indent=2))

# ---- Ask user ----
user_question = input("\nAsk your question: ")

# ---- Ask Ollama model to choose tool + args ----
prompt = f"""
You are connected to an MCP server with these tools:

{json.dumps(tools, indent=2)}

The user says: {user_question}

Pick the best tool and respond ONLY with JSON:
{{
  "tool": "<tool name>",
  "arguments": {{ ... arguments ... }}
}}
"""

model_name = "llama3"  # change to any Ollama model you have
resp = ollama.chat(
    model=model_name,
    messages=[{"role": "user", "content": prompt}],
    stream=False,  # prevent freezing
)

model_output = resp["message"]["content"].strip()
print("\n[LLM Output]", model_output)

# ---- Parse model output ----
try:
    choice = json.loads(model_output)
except Exception as e:
    print("Could not parse LLM output:", e)
    proc.terminate()
    sys.exit(1)

# ---- Call the chosen tool ----
send_msg(
    proc,
    {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": choice["tool"],
            "arguments": choice["arguments"],
        },
    },
)
read_msg(proc)

# ---- Shutdown ----
send_msg(proc, {"jsonrpc": "2.0", "id": 4, "method": "shutdown", "params": {}})
read_msg(proc)

proc.terminate()
