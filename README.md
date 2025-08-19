# Who To Ask

This project provides a simple MCP server and client for ranking repository contributors.

## Setup

1. Install Python dependencies:

```bash
pip install -r requirements.txt
```

2. Install [Ollama](https://ollama.com/) and make sure an MCP-compatible model is available. This project uses `qwen3:4b`:

```bash
ollama pull qwen3:4b
```

## Usage

Start the MCP server in one terminal:

```bash
python who_to_ask_server.py
```

In another terminal, launch the interactive client. Specify the model and how to start the server:

```bash
python who2ask_client.py --model qwen3:4b --server-cmd "python who_to_ask_server.py"
```

The client will connect to the server and allow you to ask questions that leverage repository history.
