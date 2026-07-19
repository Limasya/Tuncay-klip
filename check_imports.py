"""Check import errors in key modules."""
import sys
import traceback

modules_to_check = [
    'config',
    'models.database',
    'models.schemas',
    'utils.pydantic_compat',
    'utils.auth',
    'utils.auth_compat',
    'utils.logging_config',
    'utils.rate_limiter',
    'shared.event_schemas',
    'shared.event_bus',
    'tasks.pipeline_tasks',
]

errors = []
ok = []

for mod in modules_to_check:
    try:
        __import__(mod)
        ok.append(mod)
    except Exception as e:
        errors.append((mod, traceback.format_exc()))

print(f"OK ({len(ok)}): {', '.join(ok)}")
print()
if errors:
    print(f"ERRORS ({len(errors)}):")
    for mod, tb in errors:
        print(f"\n--- {mod} ---")
        print(tb)
else:
    print("All imports OK!")
