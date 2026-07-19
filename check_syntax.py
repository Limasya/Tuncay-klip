"""Quick syntax checker for all Python files in the project."""
import ast
import os
import sys

errors = []
checked = 0

for root, dirs, files in os.walk('.'):
    # Skip irrelevant dirs
    dirs[:] = [d for d in dirs if d not in ('__pycache__', 'node_modules', '.git', '.pytest_cache', 'dist', 'models_store')]
    for fname in files:
        if not fname.endswith('.py'):
            continue
        fpath = os.path.join(root, fname)
        try:
            with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                src = f.read()
            ast.parse(src, filename=fpath)
            checked += 1
        except SyntaxError as e:
            errors.append(f"SYNTAX ERROR {fpath}:{e.lineno}: {e.msg}")
        except Exception as e:
            errors.append(f"ERROR {fpath}: {e}")

print(f"Checked {checked} files")
if errors:
    print(f"\n{len(errors)} SYNTAX ERRORS FOUND:")
    for err in errors:
        print(err)
else:
    print("No syntax errors found!")
