import asyncio
import os
import time
import sys
from dotenv import load_dotenv

load_dotenv()

# Yolu düzelt ki services klasörünü bulabilsin
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.llm_engine import LLMEngine
from services.llm_client import generate, generate_json

async def run_comparison():
    print("=== SHADOW TRAFFIC TEST: Legacy vs LiteLLM ===")
    
    # 1. Eski LLMEngine'i hazırla
    legacy_engine = LLMEngine()
    
    # 2. Test Promptları
    test_prompts = [
        {
            "template": "title_generation",
            "context": {
                "count": 3,
                "streamer_name": "Tuncay", 
                "game_name": "Valorant", 
                "emotion": "surprised", 
                "category": "clutch",
                "viewer_count": 1000,
                "tags": "fps, clutch",
                "duration": 30,
                "platform": "tiktok",
                "language": "tr"
            },
            "is_json": False
        },
        {
            "template": "chat_sentiment",
            "context": {"chat_log": "LUL KEKW", "streamer_name": "Tuncay", "language": "tr"},
            "is_json": True
        }
    ]
    
    results = []

    os.environ["FEATURE_LLM_LITELLM_ROUTER"] = "true"
    
    for i, test in enumerate(test_prompts):
        template = test["template"]
        ctx = test["context"]
        print(f"\n--- Test {i+1}: {template} ---")
        
        # --- LEGACY ÇAĞRI ---
        start_t = time.time()
        legacy_success = False
        legacy_res = ""
        try:
            if test["is_json"]:
                legacy_res = await legacy_engine.generate_json(template, context=ctx)
            else:
                legacy_res = await legacy_engine.generate(template, context=ctx)
            legacy_success = True
        except Exception as e:
            legacy_res = str(e)
            print(f"[Legacy Error] {e}")
        legacy_dur = time.time() - start_t
        print(f"[Legacy] Süre: {legacy_dur:.2f}s | Başarı: {legacy_success}")
        
        # --- LITELLM ÇAĞRI ---
        start_t = time.time()
        lite_success = False
        lite_res = ""
        try:
            if test["is_json"]:
                lite_res = await generate_json(template, context=ctx)
                print(f"[LiteLLM Output] {str(lite_res)[:50]}...")
            else:
                lite_res = await generate(template, context=ctx)
                print(f"[LiteLLM Output] {str(lite_res)[:50]}...")
            lite_success = True
        except Exception as e:
            lite_res = str(e)
            print(f"[LiteLLM Error] {e}")
        lite_dur = time.time() - start_t
        print(f"[LiteLLM] Süre: {lite_dur:.2f}s | Başarı: {lite_success}")
        
        results.append({
            "test": template,
            "legacy_dur": legacy_dur,
            "legacy_success": legacy_success,
            "lite_dur": lite_dur,
            "lite_success": lite_success
        })
        
    print("\n=== SONUÇ ÖZETİ ===")
    print("| Test | Legacy Başarı | Legacy Süre | LiteLLM Başarı | LiteLLM Süre | Maliyet |")
    print("|------|--------------|-------------|---------------|--------------|---------|")
    for r in results:
        print(f"| {r['test']} | {r['legacy_success']} | {r['legacy_dur']:.2f}s | {r['lite_success']} | {r['lite_dur']:.2f}s | $0.00 |")

if __name__ == "__main__":
    asyncio.run(run_comparison())
