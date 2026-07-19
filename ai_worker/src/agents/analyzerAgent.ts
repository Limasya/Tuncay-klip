/**
 * AnalyzerAgent — Step 1 of the Chain-of-Thought pipeline.
 *
 * Reads the full transcript with timestamps and identifies
 * the top viral-worthy moments with reasoning.
 */

import { callLLM, parseJsonResponse } from "../llmClient";
import { ClipCandidate } from "../types";

export async function analyzeClips(
  transcript: string,
  language: string,
  maxClips: number
): Promise<ClipCandidate[]> {
  const langHint =
    language === "tr"
      ? "Respond in Turkish. Gaming slang (efsane, çıldırdı, abi) is encouraged."
      : "Respond in English.";

  const systemPrompt = `You are an expert viral video editor specializing in Twitch/Kick streaming clips.
Your task is to analyze a timestamped transcript and find the ${maxClips} most viral-worthy moments.

Think step by step:
1. Read the entire transcript to understand the full arc.
2. Identify emotional peaks: laughter, shock, hype, fails, comebacks, roasts.
3. Each clip must be 30–90 seconds long. Shorter is better for TikTok/Shorts.
4. Avoid selecting moments that start mid-sentence or end abruptly.

${langHint}

Return ONLY a JSON array. No extra text.
Format:
[
  {
    "start": 12.5,
    "end": 68.0,
    "reason": "Streamer reacts with extreme shock to losing the round",
    "score": 0.92,
    "emotion": "shock"
  }
]`;

  // Trim transcript to fit context window (~50k chars ≈ 12k tokens)
  const safeTranscript = transcript.slice(0, 50000);

  const raw = await callLLM(
    [
      { role: "system", content: systemPrompt },
      { role: "user", content: `Transcript:\n${safeTranscript}` },
    ],
    0.2,
    2048
  );

  try {
    const parsed = parseJsonResponse<ClipCandidate[]>(raw);
    return Array.isArray(parsed) ? parsed.slice(0, maxClips) : [];
  } catch {
    console.error("[AnalyzerAgent] Failed to parse JSON:", raw.slice(0, 200));
    return [];
  }
}
