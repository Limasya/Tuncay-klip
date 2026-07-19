# ADR-003: TypeScript AI Worker with Independent LLM Client

## Status
Accepted (revised — zero-cost behavior documented)

## Context
The AI analysis pipeline has two distinct LLM use cases:
1. **Semantic analysis of transcripts** (Python): Finding viral moments, metadata generation, scene-level reasoning. Uses `llm_client.py` + `litellm_config.yaml` zero-cost provider chain.
2. **Transcript-based clip selection via CoT agents** (TypeScript): 3-agent pipeline (Analyzer→Critic→Editor) that reads transcripts and selects precise clip timestamps. Uses `llmClient.ts`.

## Decision
Keep the TypeScript AI Worker's LLM client separate from Python's LLM facade.

## Zero-Cost Behavior (verified)

### Provider priority chain (llmClient.ts:27-32)
```
1. GROQ_API_KEY   → api.groq.com/openai/v1  (FREE, model: llama-3.3-70b-versatile)
2. OPENROUTER_API_KEY → openrouter.ai/api/v1  (FREE tier available, model: meta-llama/llama-3.3-70b-instruct)
3. OPENAI_API_KEY  → api.openai.com (PAID, model: gpt-4o-mini)
```

Priority is determined by env var presence, NOT by cost. If `GROQ_API_KEY` is set, it's used regardless of whether `OPENAI_API_KEY` is also set. This matches Python's zero-cost-first behavior.

### Key difference from Python
- **Python** (litellm_config.yaml): Explicit zero-cost chain with health checks, cooldowns, and automatic failover between free providers. Paid providers disabled by default.
- **TypeScript** (llmClient.ts): Simple env var priority. No health checks, no cooldowns, no automatic failover between providers. If GROQ is down, it will fail (no automatic fallback to OpenRouter).

### Missing: dotenv loading
The `dotenv` package is listed in `ai_worker/package.json` but **never imported** in any source file. When ai_worker runs standalone (`npm run dev`), it reads `process.env` directly — meaning API keys must be set in the shell environment, not in a `.env` file.

**Risk**: If launched from Python via `microservices_client.py`, Python's dotenv-loaded env is inherited. But if launched standalone, keys must be manually exported.

**Recommendation**: Add `import "dotenv/config"` at the top of `index.ts` to load `.env` from the ai_worker directory.

### Missing: template fallback
Python's `llm_client.py` has `template_content_fallback` — when ALL LLM providers fail, it returns a pre-defined template response. ai_worker has **no equivalent fallback**. If all LLM calls fail:
- AnalyzerAgent returns `[]` (empty array)
- CriticAgent receives empty array, returns empty
- EditorAgent receives empty array, returns empty
- The /analyze endpoint returns `{ clips: [], agent_log: { analyzed: 0, reviewed: 0, finalized: 0 } }`

This is not a crash, but it's a silent empty result. The Python side (`microservices_client.py:_python_fallback`) handles this by falling back to `LLMReasoner` when ai_worker is offline, but NOT when ai_worker returns empty clips.

### Config synchronization risk
Both Python and TypeScript read from the same root `.env` file (when dotenv is loaded). However:
- Python loads `.env` via `dotenv.load_dotenv()` in `main.py`
- TypeScript does NOT load `.env` (missing import)
- If API keys are rotated in `.env`, Python picks it up on restart, but TypeScript only picks it up if the shell env is updated or if dotenv import is added

## Consequences
- **Positive**: Each pipeline is independently debuggable and deployable.
- **Positive**: No cross-language FFI overhead for LLM calls.
- **Positive**: Provider priority matches Python's zero-cost-first approach.
- **Negative**: No automatic failover between free providers (unlike Python's litellm chain).
- **Negative**: No template fallback when all providers fail (silent empty result).
- **Negative**: dotenv not loaded — standalone launch requires manual env setup.
- **Mitigation**: Add `import "dotenv/config"` to index.ts. Consider adding a simple fallback in AnalyzerAgent.
