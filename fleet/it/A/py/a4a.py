"""A4a — AST scan of EVERY src/fleet/*.py. `ast.walk` sees a function-local import too, which is the
one a module-header grep misses (`cli._default_runner` really does `import subprocess` inside itself)."""
import ast, json, os, sys
from pathlib import Path
src = Path(os.environ["A4_SRC"])
std = set(sys.stdlib_module_names)
files = sorted(src.glob("*.py"))
assert files, f"no modules under {src}"
per_file, offenders = {}, []
for path in files:
    tree = ast.parse(path.read_text())
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                roots.add("<relative>")
            elif node.module:
                roots.add(node.module.split(".")[0])
    per_file[path.name] = sorted(roots)
    for root in sorted(roots):
        if root not in std and root not in ("fleet", "<relative>"):
            offenders.append(f"{path.name}:{root}")
for name, roots in per_file.items():
    print(f"{name:22} {' '.join(roots)}")
print("FILES:", len(files))
print("DISTINCT_ROOTS:", sorted({r for rs in per_file.values() for r in rs}))
print("OFFENDERS:", offenders)
print(json.dumps({"files": len(files), "offenders": offenders}))
assert not offenders, offenders
print("OK A4a")
