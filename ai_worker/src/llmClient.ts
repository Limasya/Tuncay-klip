/**
 * LLM Client — Wraps OpenAI-compatible API calls.
 *
 * DESIGN DECISION: This client is intentionally SEPARATE from Python's
 * llm_client.py / litellm_config.yaml zero-cost provider chain.
 *
 * Rationale:
 * - ai_worker is a TypeScript-first microservice with its own runtime (Node.js)
 * - It runs in a separate process and has different latency/retry requirements
 * - Its 3-agent CoT pipeline (Analyzer→Critic→Editor) is self-contained
 * - The Python LLM pipeline handles different concerns: semantic highlights,
 *   metadata generation, smart clip extraction, and scene-level analysis
 * - Keeping them separate avoids cross-language FFI overhead and simplifies
 *   debugging each pipeline independently
 *
 * Provider priority: Groq (free) > OpenRouter > OpenAI (paid)
 */

import OpenAI from "openai";
import { LLMMessage } from "./types";

let client: OpenAI | null = null;

function getClient(): OpenAI {
  if (client) return client;

  const apiKey = process.env.GROQ_API_KEY || process.env.OPENAI_API_KEY || process.env.OPENROUTER_API_KEY;
  const baseURL = process.env.GROQ_API_KEY
    ? "https://api.groq.com/openai/v1"
    : process.env.OPENROUTER_API_KEY
    ? "https://openrouter.ai/api/v1"
    : undefined;

  if (!apiKey) {
    throw new Error(
      "No API key found. Set GROQ_API_KEY, OPENAI_API_KEY, or OPENROUTER_API_KEY environment variable."
    );
  }

  client = new OpenAI({ apiKey, baseURL });
  return client;
}

export const DEFAULT_MODEL = process.env.GROQ_API_KEY
  ? "llama-3.3-70b-versatile"
  : process.env.OPENROUTER_API_KEY
  ? "meta-llama/llama-3.3-70b-instruct"
  : "gpt-4o-mini";

export async function callLLM(
  messages: LLMMessage[],
  temperature = 0.3,
  maxTokens = 2048
): Promise<string> {
  const llm = getClient();

  const response = await llm.chat.completions.create({
    model: DEFAULT_MODEL,
    messages,
    temperature,
    max_tokens: maxTokens,
  });

  return response.choices[0]?.message?.content ?? "";
}

/**
 * Parse JSON from LLM response robustly.
 * Handles markdown code fences like ```json ... ```
 */
export function parseJsonResponse<T>(raw: string): T {
  // Strip markdown code fences if present
  const cleaned = raw
    .replace(/^```(?:json)?\n?/i, "")
    .replace(/\n?```$/i, "")
    .trim();

  return JSON.parse(cleaned) as T;
}
