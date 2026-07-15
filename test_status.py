import sys
print("START", flush=True)

import psutil
print("psutil OK", flush=True)

from services.orchestrator import orchestrator
print("orchestrator import OK", flush=True)

try:
    status = orchestrator.get_status()
    print("get_status OK:", status, flush=True)
except Exception as e:
    print(f"get_status FAILED: {type(e).__name__}: {e}", flush=True)
    import traceback
    traceback.print_exc()
    print("DONE (error)", flush=True)
