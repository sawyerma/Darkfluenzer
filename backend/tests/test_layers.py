"""Importrichtung der Pakete (SP0 Schritt 2, Abnahme „Prüfskript belegt die Importrichtung“).

core/ importiert nie web/; media/, nodes/, store/, channels/ und payments/ importieren weder core/
noch web/. Importe nur für die Typprüfung (``if TYPE_CHECKING:``) zählen nicht, weil sie zur
Laufzeit nicht ausgeführt werden.
"""

from __future__ import annotations

import ast
from pathlib import Path

PKG = Path(__file__).resolve().parents[1] / "src" / "darkfluenzer"
FORBIDDEN = {
    "core": {"web"},
    "media": {"core", "web"},
    "nodes": {"core", "web"},
    "store": {"core", "web"},
    "channels": {"core", "web"},
    "payments": {"core", "web"},
}


def _type_checking_lines(tree: ast.AST) -> set[int]:
    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and "TYPE_CHECKING" in ast.unparse(node.test):
            for child in node.body:
                lines.update(range(child.lineno, (child.end_lineno or child.lineno) + 1))
    return lines


def _targets(path: Path, tree: ast.AST) -> list[tuple[int, str]]:
    """Ziel-Pakete (erste Ebene unter darkfluenzer) aller Importe einer Datei."""
    parts = path.relative_to(PKG).with_suffix("").parts
    package = list(parts[:-1])
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)] if node.level > 1 else package
                full = base + (node.module.split(".") if node.module else [])
                names = [full + [a.name] for a in node.names] if not node.module else [full]
            elif node.module and node.module.startswith("darkfluenzer"):
                names = [node.module.split(".")[1:]]
            else:
                continue
            found += [(node.lineno, n[0]) for n in names if n]
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("darkfluenzer."):
                    found.append((node.lineno, a.name.split(".")[1]))
    return found


def test_import_direction():
    violations = []
    for path in sorted(PKG.rglob("*.py")):
        rel = path.relative_to(PKG)
        if rel.parts[0] == "v1" or len(rel.parts) == 1:
            continue
        forbidden = FORBIDDEN.get(rel.parts[0], set())
        tree = ast.parse(path.read_text())
        skip = _type_checking_lines(tree)
        for line, target in _targets(path, tree):
            if line not in skip and target in forbidden:
                violations.append(f"{rel}:{line} importiert {target}/")
    assert not violations, "\n".join(violations)


def test_checker_sees_a_violation():
    """Gegenprobe: ein verbotener relativer Import in core/ wird erkannt."""
    probe = PKG / "core" / "probe.py"  # nur der Pfad, keine Datei
    tree = ast.parse("from ..web import http\nfrom . import orders\n")
    assert [t for _, t in _targets(probe, tree)] == ["web", "core"]
