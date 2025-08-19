import collections
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Dict, List

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("who-to-ask")
print(
    f"[WHO-TO-ASK MCP] Server starting (pid={os.getpid()})", file=sys.stderr, flush=True
)

# ----------------------
# Helper functions
# ----------------------


def _run(cmd, timeout_s=60, text=True):
    try:
        return subprocess.check_output(cmd, text=text, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        return ""
    except subprocess.CalledProcessError:
        return ""


def git_blame_counts(
    file_path: str, repo_path: str, since: int | None = None, timeout_s: int = 60
) -> collections.Counter:
    """
    Return a Counter of {author: lines} for a file in a repo.
    If `since` (months) is provided, only counts lines changed since then.
    """
    repo_path = os.path.abspath(repo_path)
    cmd = [
        "git",
        "-C",
        repo_path,
        "-c",
        "log.showSignature=false",
        "--no-pager",
        "blame",
        "--line-porcelain",
    ]
    if since:
        since_date = (datetime.now() - timedelta(days=int(since) * 30)).strftime(
            "%Y-%m-%d"
        )
        cmd.extend(["--since", since_date])
    cmd.append(file_path)

    out = _run(cmd, timeout_s=timeout_s)
    if not out:
        return collections.Counter()

    counts = collections.Counter()
    for line in out.splitlines():
        if line.startswith("author "):
            counts[line[7:]] += 1
    return counts


def find_barrel_reexports(
    file_path: str, repo_path: str, timeout_s: int = 20
) -> List[str]:
    """
    Find files that re-export symbols from the target file (like index.ts barrels).
    """
    repo_path = os.path.abspath(repo_path)
    file_name = os.path.basename(file_path).replace(".ts", "").replace(".js", "")
    pattern = rf"export\s+.*\s+from\s+['\"].*{re.escape(file_name)}['\"]"
    out = _run(["rg", "-n", pattern, repo_path], timeout_s=timeout_s)
    if not out:
        return []
    reexport_files = []
    for line in out.splitlines():
        importer_file = line.split(":", 1)[0]
        if os.path.isfile(importer_file):
            reexport_files.append(importer_file)
    return reexport_files


def find_importers(file_path: str, repo_path: str, timeout_s: int = 20) -> List[str]:
    """
    Return a list of files in repo_path that import/require the given file_path or any barrel that re-exports it.
    """
    repo_path = os.path.abspath(repo_path)
    file_name = os.path.basename(file_path).replace(".ts", "").replace(".js", "")

    # Step 1: Search for direct imports of file name anywhere
    import_pattern = rf"(from|require\()\s*['\"].*{re.escape(file_name)}['\"]"
    importer_files = set()
    out = _run(["rg", "-n", import_pattern, repo_path], timeout_s=timeout_s)
    if out:
        for line in out.splitlines():
            importer_file = line.split(":", 1)[0]
            if os.path.isfile(importer_file):
                importer_files.add(importer_file)

    # Step 2: Find barrels that re-export from our file
    barrels = find_barrel_reexports(file_path, repo_path, timeout_s=timeout_s)
    for barrel in barrels:
        barrel_name = os.path.basename(barrel).replace(".ts", "").replace(".js", "")
        barrel_pattern = rf"(from|require\()\s*['\"].*{re.escape(barrel_name)}['\"]"
        out2 = _run(["rg", "-n", barrel_pattern, repo_path], timeout_s=timeout_s)
        if out2:
            for line in out2.splitlines():
                importer_file = line.split(":", 1)[0]
                if os.path.isfile(importer_file):
                    importer_files.add(importer_file)

    return list(importer_files)


# ----------------------
# Snippet search helper
# ----------------------


def find_file_by_snippet(
    snippet: str, repo_path: str, timeout_s: int = 20
) -> List[str]:
    """Return file paths containing `snippet`, ranked by match count.

    Args:
        snippet: Text snippet to search for. Treated as a literal string.
        repo_path: Directory to search within.
    Raises:
        ValueError: If no files contain the snippet.
    """
    repo_path = os.path.abspath(repo_path)
    if not snippet or not snippet.strip():
        raise ValueError("Snippet must be a non-empty string")

    # Use ripgrep for fast searching. -n gives line numbers, -F treats the
    # snippet literally, and -U allows matches across newlines.
    out = _run(["rg", "-n", "-F", "-U", snippet, repo_path], timeout_s=timeout_s)

    if not out:
        raise ValueError(f"Snippet not found in repository {repo_path}")

    counts = collections.Counter()
    for line in out.splitlines():
        file_path = line.split(":", 1)[0]
        if os.path.isfile(file_path):
            counts[file_path] += 1

    if not counts:
        raise ValueError(f"Snippet not found in repository {repo_path}")

    return [fp for fp, _ in counts.most_common()]


# ----------------------
# Tools
# ----------------------


@mcp.tool()
def usage_based_contributors(
    file_path: str, repo_path: str = ".", months: int = 6, max_importers: int = 200
) -> List[Dict]:
    """
    Rank contributors based on:
    - Direct edits to the target file
    - Edits to files importing this file or its barrels
    - Recent edits (last X months) weighted higher
    Args:
      file_path: path relative to repo root
      repo_path: absolute or relative repo path
      months: recency window for extra weight
      max_importers: cap number of importer files to analyze (to keep runtime bounded)
    """
    repo_path = os.path.abspath(repo_path)

    # Direct authorship
    direct_total = git_blame_counts(file_path, repo_path)
    direct_recent = git_blame_counts(file_path, repo_path, since=months)

    # Find importer files (bounded)
    importers = find_importers(file_path, repo_path)
    if max_importers and isinstance(max_importers, int):
        importers = importers[:max_importers]

    # Authorship of importers
    importer_total = collections.Counter()
    importer_recent = collections.Counter()
    for imp in importers:
        rel_imp = os.path.relpath(imp, repo_path)
        importer_total.update(git_blame_counts(rel_imp, repo_path))
        importer_recent.update(git_blame_counts(rel_imp, repo_path, since=months))

    # Combine scores
    scores = collections.Counter()
    breakdown = {}
    for author in (
        set(direct_total)
        | set(direct_recent)
        | set(importer_total)
        | set(importer_recent)
    ):
        score = (
            direct_total[author] * 1.0
            + direct_recent[author] * 1.5
            + importer_total[author] * 0.5
            + importer_recent[author] * 1.0
        )
        scores[author] = score
        breakdown[author] = {
            "target_lines": direct_total[author],
            "target_recent": direct_recent[author],
            "importer_lines": importer_total[author],
            "importer_recent": importer_recent[author],
        }

    ranked = [
        {"author": a, "score": round(scores[a], 2), "breakdown": breakdown[a]}
        for a in sorted(scores, key=scores.get, reverse=True)
    ]
    return ranked


@mcp.tool()
def top_contributors(file_path: str, n: int = 5, repo_path: str = ".") -> List[Dict]:
    """Top N authors by blame line count on a single file."""
    repo_path = os.path.abspath(repo_path)
    counts = git_blame_counts(file_path, repo_path)
    total = sum(counts.values()) or 1
    return [
        {"author": a, "lines": c, "share": round(c / total, 3)}
        for a, c in counts.most_common(n)
    ]


@mcp.tool()
def search_importers(module_or_path: str, repo_path: str = ".") -> List[str]:
    """Return lines 'file:line:match' where module_or_path is imported/reexported."""
    repo_path = os.path.abspath(repo_path)
    pattern = rf"(from|require\()\s*['\"].*{re.escape(module_or_path)}['\"]"
    out = _run(["rg", "-n", pattern, repo_path], timeout_s=20)
    return out.splitlines() if out else []


@mcp.resource("file://{path}")
def read_file(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


@mcp.prompt("triage-question")
def triage_prompt() -> str:
    return (
        "You are helping route a code question to the right engineer. "
        "Use the provided contributors list and import graph to propose 3 people."
    )


if __name__ == "__main__":
    mcp.run()
