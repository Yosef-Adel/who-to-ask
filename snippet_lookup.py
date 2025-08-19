import os
from difflib import SequenceMatcher
from typing import Callable, List, Optional, Tuple


def find_file_by_snippet(
    snippet: str,
    repo_path: str = ".",
    prompt_user: bool = False,
    input_func: Callable[[str], str] = input,
) -> Optional[str]:
    """Locate a file in ``repo_path`` containing ``snippet``.

    If multiple files match, either prompt the user to choose one or select the
    best match heuristically using :class:`difflib.SequenceMatcher` to measure
    similarity (longest common subsequence ratio).

    Args:
        snippet: The snippet of text to search for.
        repo_path: Directory tree to search.
        prompt_user: If ``True`` and multiple matches are found, interactively
            ask the user to choose a file. If ``False``, the best match is
            selected automatically.
        input_func: Function used to obtain user input. Useful for unit tests.

    Returns:
        The path of the matching file relative to ``repo_path`` or ``None`` if
        no match is found.
    """

    repo_path = os.path.abspath(repo_path)
    candidates: List[Tuple[str, str]] = []  # (path, content)

    for root, dirs, files in os.walk(repo_path):
        if ".git" in dirs:
            dirs.remove(".git")
        for name in files:
            path = os.path.join(root, name)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
            except OSError:
                continue
            if snippet in content:
                candidates.append((path, content))

    if not candidates:
        return None

    if len(candidates) == 1:
        return candidates[0][0]

    if prompt_user:
        for idx, (path, _) in enumerate(candidates, 1):
            print(f"{idx}: {os.path.relpath(path, repo_path)}")
        while True:
            try:
                choice = int(input_func("Select the correct file: ")) - 1
            except ValueError:
                continue
            if 0 <= choice < len(candidates):
                return candidates[choice][0]

    # Heuristic selection: pick file with highest similarity ratio
    def score(item: Tuple[str, str]) -> float:
        return SequenceMatcher(None, snippet, item[1]).ratio()

    best_path, _ = max(candidates, key=score)
    return best_path
