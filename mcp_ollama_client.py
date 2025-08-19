#!/usr/bin/env python3
import json
import subprocess
import sys
import os


def send_msg(proc, obj):
    data = json.dumps(obj).encode("utf-8")
    header = f"Content-Length: {len(data)}\r\n\r\n".encode("utf-8")
    proc.stdin.write(header + data)
    proc.stdin.flush()
    print(f"\n>>> SENT: {obj}")


def read_msg(proc):
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


def main():
    if len(sys.argv) < 4:
        print(
            "Usage: python mcp_ollama_client.py <tool> <file_path> <repo_path> [months]"
        )
        sys.exit(1)

    tool = sys.argv[1]
    file_path = sys.argv[2]
    repo_path = sys.argv[3]
    months = int(sys.argv[4]) if len(sys.argv) > 4 else 6

    # Launch the MCP server using a path relative to this file so the script
    # works outside the original developer's environment.
    server_path = os.path.join(os.path.dirname(__file__), "who_to_ask_server.py")
    server_cmd = [sys.executable, server_path]
    proc = subprocess.Popen(
        server_cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        bufsize=0,
    )

    # Initialize
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

    # Tool call
    send_msg(
        proc,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": tool,
                "arguments": {
                    "file_path": file_path,
                    "repo_path": repo_path,
                    "months": months,
                },
            },
        },
    )
    read_msg(proc)

    # Shutdown
    send_msg(proc, {"jsonrpc": "2.0", "id": 3, "method": "shutdown", "params": {}})
    read_msg(proc)

    proc.terminate()


if __name__ == "__main__":
    main()
