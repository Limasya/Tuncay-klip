/**
 * CriticAgent — Step 2 of the Chain-of-Thought pipeline.
 *
 * Reviews the AnalyzerAgent's clip selections, flags issues,
 * and either approves or rejects each clip with feedback.
 */

import { callLLM, parseJsonResponse } from "../llmClient";
import { ClipCandidate } from "../types";

interface CriticReview {
  start: number;
  approved: boolean;
  critique: string;
}

export async function critiqueClips(
  candidates: ClipCandidate[],
  transcript: string,
  language: string
): Promise<ClipCandidate[]> {
  if (candidates.length === 0) return [];

  const langHint =
    language === "tr"
      ? "Respond in Turkish."
      : "Respond in English.";

  const systemPrompt = `You are a strict content quality critic for a viral clip generator.
The Analyzer has proposed some clip segments. Your job is to review each one and:

1. REJECT if: duration > 90 seconds, or start/end is mid-sentence, or the content is boring/slow
2. APPROVE if: emotional peak is clear, clip starts with a hook, duration is 30–90 seconds
3. If you REJECT, explain briefly what the fix would be.

${langHint}

Return ONLY a JSON array with your verdicts. No extra text.
Format:
[
  { "start": 12.5, "approved": true, "critique": "Strong opening shock moment, approved." },
  { "start": 180.0, "approved": false, "critique": "Clip is 110s, too long. Should end at 240s instead of 290s." }
]`;

  const candidatesSummary = JSON.stringify(
    candidates.map((c) => ({
      start: c.start,
      end: c.end,
      duration: Math.round(c.end - c.start),
      reason: c.reason,
      emotion: c.emotion,
      score: c.score,
    })),
    null,
    2
  );

  const raw = await callLLM(
    [
      { role: "system", content: systemPrompt },
      { role: "user", content: `Clip Proposals:\n${candidatesSummary}` },
    ],
    0.1,
    1024
  );

  try {
    const reviews = parseJsonResponse<CriticReview[]>(raw);
    const reviewMap = new Map(reviews.map((r) => [r.start, r]));

    return candidates.map((c) => {
      const review = reviewMap.get(c.start);
      return {
        ...c,
        approved: review?.approved ?? true,
        critique: review?.critique ?? "",
      };
    }).filter((c) => c.approved !== false);
  } catch {
    console.error("[CriticAgent] Failed to parse JSON, passing all candidates through.");
    return candidates;
  }
}
