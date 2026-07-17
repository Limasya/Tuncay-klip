"""Bug-hunt smoke test for Phase 5 timeline/project endpoints."""
import json
import sys
import time
import httpx

BASE = "http://localhost:8000"
client = httpx.Client(timeout=10)
errors = []


def check(label, method, url, expected_code, body=None):
    fn = {"GET": client.get, "POST": client.post, "DELETE": client.delete}[method]
    kwargs = {"json": body} if body else {}
    try:
        r = fn(url, **kwargs)
        if r.status_code != expected_code:
            errors.append(f"FAIL {label}: expected {expected_code}, got {r.status_code} -- {r.text[:150]}")
            return None
        print(f"   {label}: {r.status_code} OK")
        try:
            return r.json()
        except Exception:
            return r.text
    except Exception as e:
        errors.append(f"FAIL {label}: {e}")
        return None


# ============================================================
print("=== BUG HUNT: Phase 5 Timeline/Project API ===\n")

# 1) Project lifecycle
print("1) Project CRUD")
proj = check("create", "POST", f"{BASE}/api/v1/projects", 201, {"name": "BugHunt"})
pid = proj["project_id"]
check("read", "GET", f"{BASE}/api/v1/projects/{pid}", 200)
check("list", "GET", f"{BASE}/api/v1/projects?limit=10", 200)

# 2) Clip insert
print("\n2) Clip insert + rippling")
v1 = next(t for t in proj["timeline"]["tracks"] if t["track_type"] == "video")
insert1 = check("clip_a", "POST", f"{BASE}/api/v1/projects/{pid}/tracks/{v1['track_id']}/clips", 200, {
    "expected_revision": 1,
    "asset_path": "source.mp4",
    "source_range": {"start": {"numerator": 0, "denominator": 1}, "duration": {"numerator": 10, "denominator": 1}},
    "record_start": {"numerator": 0, "denominator": 1},
    "mode": "insert",
})
clip_a_id = insert1["clip_id"]
insert2 = check("clip_b_ripple", "POST", f"{BASE}/api/v1/projects/{pid}/tracks/{v1['track_id']}/clips", 200, {
    "expected_revision": 2,
    "asset_path": "b.mp4",
    "source_range": {"start": {"numerator": 0, "denominator": 1}, "duration": {"numerator": 5, "denominator": 1}},
    "record_start": {"numerator": 3, "denominator": 1},
    "mode": "insert",
})
# Verify a was split: should now have 3 clips on track
fetched = check("verify_split", "GET", f"{BASE}/api/v1/projects/{pid}", 200)
clips = [c for t in fetched["timeline"]["tracks"] if t["track_type"] == "video" for c in t["clips"]]
if len(clips) != 3:
    errors.append(f"Expected 3 clips after insert, got {len(clips)}")
else:
    print(f"   split OK: {len(clips)} clips on V1")

# 3) Render guard (missing asset)
print("\n3) Render with missing asset")
check("render_422", "POST", f"{BASE}/api/v1/projects/{pid}/renders", 422, {
    "aspect_ratio": "16:9", "resolution": "1080p", "crf": 23,
})

# 4) Revision conflict
print("\n4) Revision conflict")
check("conflict", "POST", f"{BASE}/api/v1/projects/{pid}/tracks/{v1['track_id']}/clips", 409, {
    "expected_revision": 1,  # stale
    "asset_path": "c.mp4",
    "source_range": {"start": {"numerator": 0, "denominator": 1}, "duration": {"numerator": 3, "denominator": 1}},
    "record_start": {"numerator": 0, "denominator": 1},
    "mode": "insert",
})

# 5) Range edit (lift)
print("\n5) Range edit (lift)")
clips_before = len(clips)
check("lift", "POST", f"{BASE}/api/v1/projects/{pid}/tracks/{v1['track_id']}/range-edit", 200, {
    "expected_revision": 3,
    "time_range": {"start": {"numerator": 0, "denominator": 1}, "duration": {"numerator": 2, "denominator": 1}},
    "mode": "lift",
})

# 6) Range edit (extract = ripple close gap)
print("\n6) Range edit (extract)")
check("extract", "POST", f"{BASE}/api/v1/projects/{pid}/tracks/{v1['track_id']}/range-edit", 200, {
    "expected_revision": 4,
    "time_range": {"start": {"numerator": 0, "denominator": 1}, "duration": {"numerator": 1, "denominator": 1}},
    "mode": "extract",
})

# 7) Ripple trim
print("\n7) Ripple trim")
fetched2 = check("pre_trim", "GET", f"{BASE}/api/v1/projects/{pid}", 200)
remaining_clips = [c for t in fetched2["timeline"]["tracks"] if t["track_type"] == "video" for c in t["clips"]]
first_clip_id = remaining_clips[0]["clip_id"]
check("ripple_trim", "POST", f"{BASE}/api/v1/projects/{pid}/tracks/{v1['track_id']}/clips/{first_clip_id}/ripple-trim", 200, {
    "expected_revision": 5,
    "new_source_duration": {"numerator": 3, "denominator": 1},
})

# 8) Overwrite (replace in place)
print("\n8) Overwrite edit")
fetched3 = check("pre_overwrite", "GET", f"{BASE}/api/v1/projects/{pid}", 200)
clips3 = [c for t in fetched3["timeline"]["tracks"] if t["track_type"] == "video" for c in t["clips"]]
if clips3:
    first_start = clips3[0]["record_range"]["start"]["numerator"]
    check("overwrite", "POST", f"{BASE}/api/v1/projects/{pid}/tracks/{v1['track_id']}/clips", 200, {
        "expected_revision": 6,
        "asset_path": "replaced.mp4",
        "source_range": {"start": {"numerator": 0, "denominator": 1}, "duration": {"numerator": 2, "denominator": 1}},
        "record_start": {"numerator": first_start, "denominator": 1},
        "mode": "overwrite",
    })

# 9) 404 guards
print("\n9) 404 guards")
check("deleted_project", "GET", f"{BASE}/api/v1/projects/00000000-0000-0000-0000-000000000000", 404)
check("unknown_render", "GET", f"{BASE}/api/v1/projects/renders/nonexistent-id", 404)
check("missing_clip_ripple", "POST", f"{BASE}/api/v1/projects/{pid}/tracks/{v1['track_id']}/clips/missing/ripple-trim", 404, {
    "expected_revision": 7,
    "new_source_duration": {"numerator": 1, "denominator": 1},
})

# 10) Validation guards
print("\n10) Validation guards (422)")
check("zero_speed", "POST", f"{BASE}/api/v1/projects/{pid}/tracks/{v1['track_id']}/clips", 422, {
    "expected_revision": 7,
    "asset_path": "x.mp4",
    "source_range": {"start": {"numerator": 0, "denominator": 1}, "duration": {"numerator": 5, "denominator": 1}},
    "record_start": {"numerator": 0, "denominator": 1},
    "speed_numerator": 0,
    "speed_denominator": 1,
    "mode": "insert",
})
check("empty_asset", "POST", f"{BASE}/api/v1/projects/{pid}/tracks/{v1['track_id']}/clips", 422, {
    "expected_revision": 7,
    "asset_path": "",
    "source_range": {"start": {"numerator": 0, "denominator": 1}, "duration": {"numerator": 5, "denominator": 1}},
    "record_start": {"numerator": 0, "denominator": 1},
    "mode": "insert",
})

# 11) Output path sandbox
print("\n11) Output path sandbox")
for bad in ["/tmp/evil.mp4", "data/exports/../secrets.mp4", "C:\\Windows\\evil.mp4"]:
    check(f"sandbox_{bad[:15]}", "POST", f"{BASE}/api/v1/projects/{pid}/renders", 422, {
        "aspect_ratio": "16:9", "resolution": "1080p", "crf": 23, "output_path": bad,
    })

# 12) Track operations
print("\n12) Track add")
check("add_title_track", "POST", f"{BASE}/api/v1/projects/{pid}/tracks", 200, {
    "expected_revision": 7, "track_type": "title", "name": "T1",
})

# 13) Empty timeline render
print("\n13) Empty timeline render guard")
r_new = check("create_empty", "POST", f"{BASE}/api/v1/projects", 201, {"name": "Empty"})
pid2 = r_new["project_id"]
check("render_empty", "POST", f"{BASE}/api/v1/projects/{pid2}/renders", 422, {
    "aspect_ratio": "16:9", "resolution": "1080p", "crf": 23,
})

# 14) Delete project
print("\n14) Delete")
check("delete_1", "DELETE", f"{BASE}/api/v1/projects/{pid}", 204)
check("delete_2", "DELETE", f"{BASE}/api/v1/projects/{pid2}", 204)
check("delete_gone", "DELETE", f"{BASE}/api/v1/projects/{pid}", 404)

# 15) System health survives everything
print("\n15) System health intact")
check("health", "GET", f"{BASE}/health", 200)
# check("system_status", "GET", f"{BASE}/api/system/status", 200) # Requires auth

# 16) OpenAPI integrity
print("\n16) OpenAPI routes")
api = check("openapi", "GET", f"{BASE}/openapi.json", 200)
paths = sorted(api["paths"].keys()) if api else []
required = [
    "/api/v1/projects", "/api/v1/projects/{project_id}",
    "/api/v1/projects/{project_id}/tracks",
    "/api/v1/projects/{project_id}/tracks/{track_id}/clips",
    "/api/v1/projects/{project_id}/tracks/{track_id}/range-edit",
    "/api/v1/projects/{project_id}/tracks/{track_id}/clips/{clip_id}/ripple-trim",
    "/api/v1/projects/{project_id}/renders",
    "/api/v1/projects/renders/{job_id}",
]
missing = [p for p in required if p not in paths]
if missing:
    errors.append(f"Missing routes: {missing}")
else:
    print(f"   all {len(required)} timeline routes present, total={len(paths)}")

# ============================================================
client.close()
print(f"\n{'=' * 50}")
if errors:
    print(f"FAILURES: {len(errors)}")
    for e in errors:
        print(f"  {e}")
    sys.exit(1)
else:
    print("ALL BUG-HUNT TESTS PASSED")
