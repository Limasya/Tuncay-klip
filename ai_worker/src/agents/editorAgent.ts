/**
 * EditorAgent — Step 3 of the Chain-of-Thought pipeline.
 *
 * Takes the Critic-approved clips and finalizes them:
 * - Generates a viral hook sentence
 * - Ensures precise start/end alignment
 * - Outputs the final structured FinalClip objects
 */

import { callLLM, parseJsonResponse } from "../llmClient";
import { ClipCandidate, FinalClip } from "../types";

export async function finalizeClips(
  approved: ClipCandidate[],
  language: string
): Promise<FinalClip[]> {
  if (approved.length === 0) return [];

  const langHint =
    language === "tr"
      ? "Write the hook in Turkish. Use energetic, punchy language like a Turkish TikTok creator."
      : "Write the hook in English. Punchy, hook-first style.";

  const systemPrompt = `You are a master clip editor who writes viral captions.
For each approved clip, generate a short (max 10 words) "hook" — the first sentence someone would read as a caption.

${langHint}

Return ONLY a JSON array. No extra text.
Format:
[
  {
    "start": 12.5,
    "end": 68.0,
    "hook": "Bu kısımda tamamen çıldırdı 😱"
  }
]`;

  const clipSummary = JSON.stringify(
    approved.map((c) => ({
      start: c.start,
      end: c.end,
      reason: c.reason,
      emotion: c.emotion,
    })),
    null,
    2
  );

  const raw = await callLLM(
    [
      { role: "system", content: systemPrompt },
      { role: "user", content: `Approved clips:\n${clipSummary}` },
    ],
    0.5,
    1024
  );

  try {
    const hooks = parseJsonResponse<Array<{ start: number; end: number; hook: string }>>(raw);
    const hookMap = new Map(hooks.map((h) => [h.start, h.hook]));

    return approved.map((c): FinalClip => ({
      start: c.start,
      end: c.end,
      duration: Math.round((c.end - c.start) * 10) / 10,
      reason: c.reason,
      score: c.score,
      emotion: c.emotion,
      hook: hookMap.get(c.start) ?? c.reason.slice(0, 60),
    }));
  } catch {
    console.error("[EditorAgent] Failed to parse JSON, using raw data.");
    return approved.map((c): FinalClip => ({
      start: c.start,
      end: c.end,
      duration: Math.round((c.end - c.start) * 10) / 10,
      reason: c.reason,
      score: c.score,
      emotion: c.emotion,
      hook: c.reason.slice(0, 60),
    }));
  }
}
