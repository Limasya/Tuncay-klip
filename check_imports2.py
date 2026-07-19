"""Check import errors in services and API modules."""
import sys
import traceback
import os

# Set AUTH_DISABLED to avoid auth issues during imports
os.environ['AUTH_DISABLED'] = '1'

# Check services
service_files = [
    'services.database',
    'services.cache',
    'services.clip_service',
    'services.ai_analysis',
    'services.llm_client',
    'services.llm_engine',
    'services.smart_editor',
    'services.video_editor',
    'services.subtitle_service',
    'services.recommendation_engine',
    'services.task_queue',
    'services.metrics',
    'services.ws_manager',
    'services.auto_boot',
    'services.auto_backup',
    'services.rate_limiter',
    'services.health_monitor',
    'services.kick_api',
    'services.youtube_downloader',
    'services.social_poster',
    'services.project_store',
]

api_modules = [
    'api.domains',
    'api.routers.clips',
    'api.routers.pipeline',
    'api.routers.analytics',
    'api.routers.edit',
    'api.routers.recommendations',
    'api.routers.projects',
    'api.routers.system',
    'api.routers.platform',
    'api.routers.admin',
    'api.routers.advanced',
    'api.routers.search',
    'api.routers.smart_editor',
    'api.routers.social',
    'api.routers.knowledge_base',
    'api.routers.preferences',
    'api.routers.llm_status',
]

all_modules = service_files + api_modules
errors = []
ok = []

for mod in all_modules:
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
        # Only show last 10 lines of traceback
        lines = tb.strip().split('\n')
        print('\n'.join(lines[-10:]))
else:
    print("All imports OK!")
