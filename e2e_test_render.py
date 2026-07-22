import asyncio
import os
from pathlib import Path

async def run_e2e_render_test():
    print("[1] Generating a 5-second 1920x1080 test video...")
    os.system("ffmpeg -y -f lavfi -i testsrc=duration=5:size=1920x1080:rate=30 -c:v libx264 -preset ultrafast raw_test.mp4")
    
    print("[2] Initializing AutoEditor...")
    from services.auto_editor import AutoEditor
    editor = AutoEditor()
    
    # Ensure workspace is ready
    os.makedirs(editor.workspace, exist_ok=True)
    os.makedirs(editor.edited_dir, exist_ok=True)
    
    print("[3] Testing Adobe-Level _crop_to_vertical (Ken Burns zoompan)...")
    try:
        await editor._crop_to_vertical("raw_test.mp4", "vert_test.mp4", duration=5.0)
        
        if os.path.exists("vert_test.mp4") and os.path.getsize("vert_test.mp4") > 1024:
            print("✅ E2E TEST PASSED! The Ken Burns crop was successfully generated.")
            print(f"File size: {os.path.getsize('vert_test.mp4')} bytes")
        else:
            print("❌ E2E TEST FAILED! Output file is missing or empty.")
            
    except Exception as e:
        print(f"❌ E2E TEST CRASHED: {e}")

if __name__ == "__main__":
    asyncio.run(run_e2e_render_test())
