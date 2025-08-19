import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from snippet_lookup import find_file_by_snippet

def test_single_match(tmp_path):
    f1 = tmp_path / "file1.txt"
    f1.write_text("hello world\\n")
    (tmp_path / "file2.txt").write_text("nothing here\\n")

    result = find_file_by_snippet("world", str(tmp_path))
    assert result == str(f1)

def test_no_match(tmp_path):
    (tmp_path / "file1.txt").write_text("foo\\n")
    result = find_file_by_snippet("bar", str(tmp_path))
    assert result is None

def test_multiple_matches_heuristic(tmp_path):
    snippet = "print('hi')\n"
    f1 = tmp_path / "a.py"
    f1.write_text(snippet)
    f2 = tmp_path / "b.py"
    f2.write_text("# header\\n" + snippet + "# footer\\n")

    result = find_file_by_snippet(snippet, str(tmp_path), prompt_user=False)
    assert result == str(f1)
