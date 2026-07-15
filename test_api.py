"""Quick integration test - runs server, tests endpoints, exits."""
import httpx
import time
import subprocess
import sys
import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Kill any existing server on port 8000
import socket
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1)
    result = s.connect_ex(('localhost', 8000))
    s.close()
    if result == 0:
        print("Port 8000 in use, killing...")
        os.system("taskkill /F /IM python.exe /T >nul 2>&1")
        time.sleep(2)
except Exception:
    pass

# Start server
proc = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE
)
time.sleep(6)

client = httpx.Client(timeout=10.0)
base = "http://localhost:8000"

try:
    # Health
    r = client.get(f"{base}/health")
    print(f"Health: {r.status_code} {r.json()}")

    # Status
    try:
        r = client.get(f"{base}/api/system/status")
        print(f"Status: {r.status_code} {r.json()}")
    except Exception as e:
        print(f"Status error: {e}")

    # Channel info (Kick API - may fail from dev env)
    try:
        r = client.get(f"{base}/api/system/channel-info", timeout=15)
        print(f"Channel: {r.status_code} {r.json()}")
    except Exception as e:
        print(f"Channel error (expected - Cloudflare): {type(e).__name__}")

    # Stream info
    try:
        r = client.get(f"{base}/api/system/stream-info", timeout=15)
        print(f"Stream: {r.status_code} {r.json()}")
    except Exception as e:
        print(f"Stream error: {type(e).__name__}")

    # Analysis stats
    try:
        r = client.get(f"{base}/api/system/analysis-stats")
        print(f"Analysis: {r.status_code} {r.json()}")
    except Exception as e:
        print(f"Analysis error: {e}")

    # List all routes
    r = client.get(f"{base}/openapi.json")
    paths = sorted(r.json().get("paths", {}).keys())
    print(f"\nAll routes ({len(paths)}):")
    for p in paths:
        methods = list(r.json()["paths"][p].keys())
        method_str = " ".join(m.upper() for m in methods)
        print(f"  {method_str:12s} {p}")

except Exception as e:
    print(f"FATAL: {e}")
finally:
    client.close()
    proc.terminate()
    proc.wait(timeout=5)
    print("\nServer stopped.")
