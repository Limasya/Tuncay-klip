/**
 * LLM Client — Wraps OpenAI-compatible API calls.
 * Uses OPENAI_API_KEY or GROQ_API_KEY env (Groq is free + fast).
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
