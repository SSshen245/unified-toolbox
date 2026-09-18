"""Shared test helpers; independent of the application."""
import ast
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "unified" / "unified.py"


def method_source(text, cls, name):
    """Return the exact source of one method inside one class."""
    classes = [n for n in ast.parse(text).body
               if isinstance(n, ast.ClassDef) and n.name == cls]
    if len(classes) != 1:
        raise ValueError("Expected one class: " + cls)
    nodes = [n for n in classes[0].body
             if isinstance(n, ast.FunctionDef) and n.name == name]
    if len(nodes) != 1:
        raise ValueError("Expected one method: " + name)
    node = nodes[0]
    start = min([node.lineno] + [d.lineno for d in node.decorator_list])
    return "".join(text.splitlines(keepends=True)[start - 1:node.end_lineno]).rstrip("\r\n")


def atomic_apply(path, original, proposed):
    """Compile-check, drift-check, then atomically replace; return backup path."""
    compile(proposed, str(path), "exec")
    if path.read_bytes() != original:
        raise RuntimeError("Source changed during preparation")
    fd, backup = tempfile.mkstemp(prefix=path.name + ".filesafety.", suffix=".bak", dir=path.parent)
    with os.fdopen(fd, "wb") as stream:
        stream.write(original)
    fd, pending = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(proposed.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        if path.read_bytes() != original:
            raise RuntimeError("Source changed before commit")
        os.replace(pending, path)
    finally:
        if os.path.exists(pending):
            os.unlink(pending)
    return backup
