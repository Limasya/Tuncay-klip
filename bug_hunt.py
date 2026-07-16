"""Bug-hunt smoke test for Phase 5 timeline/project endpoints."""
import json
import os
import sys
from pathlib import Path

import httpx

# Ensure server is up
BASE = "http://localhost:8000"
client = httpx.Client(timeout=10)
try:
    client.get(f"{BASE}/health")
except Exception as exc:
    print("SERVER NOT REACHABLE:", exc)
    sys.exit(1)

errors = []


def check(method, url, expected_code, body=None):
    fn = client.get if method == "GET" else client.post if method == "POST" else client.delete
    kwargs = {"json": body} if body else {}
    try:
        r = fn(url, **kwargs)
        if r.status_code != expected_code:
            errors.append(
                f"{method} {url} -> expected {expected_code} got {r.status_code}: {r.text[:200]}"
            )
            return None
        ct = r.headers.get("content-type", "")
        return r.json() if ct.startswith("application/json") else r.text
    except Exception as exc:
        errors.append(f"{method} {url} -> CONNECT FAIL: {exc}")
        return None


# --- 1) Project lifecycle ---
print("1) Project CRUD ...")
r = client.post(f"{BASE}/api/v1/projects", json={"name": "Bug Hunt"})
assert r.status_code == 201, f"create project failed: {r.text}"
pid = r.json()["project_id"]
print(f"   created: {pid}")

r2 = client.get(f"{BASE}/api/v1/projects/{pid}")
assert r2.status_code == 200, f"get failed: {r2.text}"
data = r2.json()
v1 = next(t for t in data["timeline"]["tracks"] if t["track_type"] == "video")
print(f"   read OK, rev={data['revision']}")

# --- 2) Clip insert ---
print("2) Clip insert ...")
resp = client.post(
    f"{BASE}/api/v1/projects/{pid}/tracks/{v1['track_id']}/clips",
    json={
        "expected_revision": 1,
        "asset_path": "source.mp4",
        "source_range": {
            "start": {"numerator": 0, "denominator": 1},
            "duration": {"numerator": 10, "denominator": 1},
        },
        "record_start": {"numerator": 0, "denominator": 1},
        "mode": "insert",
    },
)
if resp.status_code != 200:
    errors.append(f"insert clip failed: {resp.text}")
else:
    clip_id = resp.json()["clip_id"]
    print(f"   OK, rev={resp.json()['project']['revision']}")

# --- 3) Render (compiler must reject -- asset not on disk) ---
print("3) Render (expect 422 asset missing) ...")
resp = client.post(
    f"{BASE}/api/v1/projects/{pid}/renders",
    json={"aspect_ratio": "9:16", "resolution": "1080p", "crf": 23},
)
if resp.status_code == 422:
    print(f"   422 OK - {resp.text[:100]}")
else:
    errors.append(f"render expected 422 got {resp.status_code}: {resp.text[:200]}")

# --- 4) Delete project ---
print("4) Delete ...")
resp = client.delete(f"{BASE}/api/v1/projects/{pid}")
assert resp.status_code == 204, f"delete failed: {resp.text}"

# --- 5) 404 guards ---
print("5) 404 guards ...")
resp = client.get(f"{BASE}/api/v1/projects/{pid}")
assert resp.status_code == 404, f"expected 404 got {resp.status_code}"
print("   deleted project 404 OK")

resp = client.get(f"{BASE}/api/v1/renders/nonexistent")
assert resp.status_code == 404, f"expected 404 got {resp.status_code}"
print("   unknown render job 404 OK")

# --- 6) Revision conflict ---
print("6) Revision conflict ...")
r1 = client.post(f"{BASE}/api/v1/projects", json={"name": "Conflict Test"})
pid2 = r1.json()["project_id"]
v2 = next(t for t in r1.json()["timeline"]["tracks"] if t["track_type"] == "video")

client.post(
    f"{BASE}/api/v1/projects/{pid2}/tracks/{v2['track_id']}/clips",
    json={
        "expected_revision": 1,
        "asset_path": "a.mp4",
        "source_range": {
            "start": {"numerator": 0, "denominator": 1},
            "duration": {"numerator": 5, "denominator": 1},
        },
        "record_start": {"numerator": 0, "denominator": 1},
        "mode": "insert",
    },
)

c1 = client.post(
    f"{BASE}/api/v1/projects/{pid2}/tracks/{v2['track_id']}/clips",
    json={
        "expected_revision": 1,
        "asset_path": "b.mp4",
        "source_range": {
            "start": {"numerator": 0, "denominator": 1},
            "duration": {"numerator": 3, "denominator": 1},
        },
        "record_start": {"numerator": 0, "denominator": 1},
        "mode": "insert",
    },
)
if c1.status_code == 409:
    print("   409 conflict OK")
else:
    errors.append(f"conflict expected 409 got {c1.status_code}: {c1.text[:200]}")
client.delete(f"{BASE}/api/v1/projects/{pid2}")

# --- 7) Lock guard (PermissionError → HTTP 423) ---
print("7) PermissionError → 423 guard ...")
r3 = client.post(f"{BASE}/api/v1/projects", json={"name": "Lock Test"})
pid3 = r3.json()["project_id"]
v3 = next(t for t in r3.json()["timeline"]["tracks"] if t["track_type"] == "video")

# Insert a clip, then lock it
ins = client.post(
    f"{BASE}/api/v1/projects/{pid3}/tracks/{v3['track_id']}/clips",
    json={
        "expected_revision": 1,
        "asset_path": "a.mp4",
        "source_range": {
            "start": {"numerator": 0, "denominator": 1},
            "duration": {"numerator": 5, "denominator": 1},
        },
        "record_start": {"numerator": 0, "denominator": 1},
        "mode": "insert",
    },
)
project_data = ins.json()["project"]
cd = next(
    clip for t in project_data["timeline"]["tracks"] if t["track_type"] == "video"
    for clip in t["clips"]
)
real_clip_id = cd["clip_id"]

# Lock the clip via direct model manipulation (no API endpoint yet for this)
# and then try to insert another clip that overlaps it
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.project_store import project_store
from services.timeline_engine import EditMode, RationalTime, TimeRange, TimelineClip

project = project_store.get(pid3)
track = project.timeline.get_track(v3["track_id"])
track.get_clip(real_clip_id).locked = True
project_store.save(project, expected_revision=project.revision)

# Now attempt overwrite over locked clip → 423
resp = client.post(
    f"{BASE}/api/v1/projects/{pid3}/tracks/{v3['track_id']}/clips",
    json={
        "expected_revision": project.revision,
        "asset_path": "b.mp4",
        "source_range": {
            "start": {"numerator": 0, "denominator": 1},
            "duration": {"numerator": 3, "denominator": 1},
        },
        "record_start": {"numerator": 0, "denominator": 1},
        "mode": "overwrite",
    },
)
if resp.status_code == 423:
    print("   423 locked clip OK")
else:
    errors.append(
        f"locked clip overwrite expected 423 got {resp.status_code}: {resp.text[:200]}"
    )
client.delete(f"{BASE}/api/v1/projects/{pid3}")

# --- 8) Validate timeline model integrity via CLI ---
print("8) CLI model integrity ...")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.timeline_engine import TrackType

r4 = client.post(f"{BASE}/api/v1/projects", json={"name": "Integrity"})
pid4 = r4.json()["project_id"]
v4 = next(t for t in r4.json()["timeline"]["tracks"] if t["track_type"] == "video")

# Insert a clip
client.post(
    f"{BASE}/api/v1/projects/{pid4}/tracks/{v4['track_id']}/clips",
    json={
        "expected_revision": 1,
        "asset_path": "a.mp4",
        "source_range": {
            "start": {"numerator": 0, "denominator": 1},
            "duration": {"numerator": 10, "denominator": 1},
        },
        "record_start": {"numerator": 0, "denominator": 1},
        "mode": "insert",
    },
)

# Overlapping insert must fail (track validation rejects overlap)
resp = client.post(
    f"{BASE}/api/v1/projects/{pid4}/tracks/{v4['track_id']}/clips",
    json={
        "expected_revision": 2,
        "asset_path": "b.mp4",
        "source_range": {
            "start": {"numerator": 0, "denominator": 1},
            "duration": {"numerator": 3, "denominator": 1},
        },
        "record_start": {"numerator": 0, "denominator": 1},
        "mode": "insert",
    },
)
assert resp.status_code == 422, f"overlap should 422, got {resp.status_code}"
print(f"   overlap rejected 422 (as expected)")

# Speed-split record rejection
resp = client.post(
    f"{BASE}/api/v1/projects/{pid4}/tracks/{v4['track_id']}/clips",
    json={
        "expected_revision": 2,
        "asset_path": "c.mp4",
        "source_range": {
            "start": {"numerator": 0, "denominator": 1},
            "duration": {"numerator": 5, "denominator": 1},
        },
        "record_start": {"numerator": 5, "denominator": 1},
        "mode": "insert",
        "speed_numerator": 2,
        "speed_denominator": 1,
    },
)
if resp.status_code == 200:
    print(f"   speed insert accepted (record_duration = 5 * (1/2) = 2.5)")
else:
    errors.append(f"speed insert should work: {resp.status_code} {resp.text[:200]}")

# Verify destructured clip by fetching project
fetched = client.get(f"{BASE}/api/v1/projects/{pid4}")
clips = [
    clip for t in fetched.json()["timeline"]["tracks"] if t["track_type"] == "video"
    for clip in t["clips"]
]
print(f"   clip count: {len(clips)}")
client.delete(f"{BASE}/api/v1/projects/{pid4}")

# --- 9) Empty timeline render guard ---
print("9) Empty timeline guard ...")
r5 = client.post(f"{BASE}/api/v1/projects", json={"name": "Empty"})
pid5 = r5.json()["project_id"]
resp = client.post(
    f"{BASE}/api/v1/projects/{pid5}/renders",
    json={"aspect_ratio": "16:9", "resolution": "1080p", "crf": 23},
)
if resp.status_code == 422:
    print(f"   422 empty timeline OK")
else:
    errors.append(f"empty timeline expected 422 got {resp.status_code}: {resp.text[:200]}")
client.delete(f"{BASE}/api/v1/projects/{pid5}")

# --- 10) Meta-system integrity ---
print("10) System health still alive ...")
r = client.get(f"{BASE}/api/system/status")
assert r.status_code == 200
d = r.json()
assert "cpu_usage" in d
assert "target_channel" in d
print(f"   system status OK, channel={d['target_channel']}")

r = client.get(f"{BASE}/openapi.json")
paths = sorted(r.json()["paths"].keys())
required = [
    "/api/v1/projects",
    "/api/v1/projects/{project_id}",
    "/api/v1/projects/{project_id}/tracks",
    "/api/v1/projects/{project_id}/tracks/{track_id}/clips",
    "/api/v1/projects/{project_id}/tracks/{track_id}/range-edit",
    "/api/v1/projects/{project_id}/tracks/{track_id}/clips/{clip_id}/ripple-trim",
    "/api/v1/projects/{project_id}/renders",
    "/api/v1/renders/{job_id}",
]
missing = [p for p in required if p not in paths]
if missing:
    errors.append(f"Missing routes: {missing}")
print(f"   routes: {len(paths)}")

# --- 11) Output-path sandboxing ---
print("11) Output-path sandbox ...")
r6 = client.post(f"{BASE}/api/v1/projects", json={"name": "Sandbox"})
pid6 = r6.json()["project_id"]
v6 = next(t for t in r6.json()["timeline"]["tracks"] if t["track_type"] == "video")
client.post(
    f"{BASE}/api/v1/projects/{pid6}/tracks/{v6['track_id']}/clips",
    json={
        "expected_revision": 1,
        "asset_path": "source.mp4",
        "source_range": {
            "start": {"numerator": 0, "denominator": 1},
            "duration": {"numerator": 5, "denominator": 1},
        },
        "record_start": {"numerator": 0, "denominator": 1},
        "mode": "insert",
    },
)
for bad_path in ["/tmp/evil.mp4", "data/exports/../secrets.mp4"]:
    resp = client.post(
        f"{BASE}/api/v1/projects/{pid6}/renders",
        json={
            "aspect_ratio": "16:9",
            "resolution": "1080p",
            "crf": 23,
            "output_path": bad_path,
        },
    )
    if resp.status_code == 422:
        print(f"   sandbox rejected '{bad_path}' -> 422")
    else:
        errors.append(f"output-path sandbox failed for '{bad_path}': {resp.status_code}")
client.delete(f"{BASE}/api/v1/projects/{pid6}")

# --- Final ---
client.close()
if errors:
    print(f"\nFAILURE: {len(errors)} error(s)")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print(f"\n=== ALL BUG-HUNT TESTS PASSED ===")