/**
 * Tuncay Klip AI — TypeScript Agent Worker
 * =========================================
 * Multi-agent Chain-of-Thought clip selection engine.
 *
 * Agents:
 *  1. AnalyzerAgent  — Reads transcript, identifies viral moments with reasoning
 *  2. CriticAgent    — Reviews the selections, flags issues (too long, boring start)
 *  3. EditorAgent    — Finalizes precise start/end timestamps as JSON
 *
 * Exposes a simple HTTP API (Express) that the Python Core calls.
 */

import express, { Request, Response } from "express";
import { analyzeClips } from "./agents/analyzerAgent";
import { critiqueClips } from "./agents/criticAgent";
import { finalizeClips } from "./agents/editorAgent";
import { ClipCandidate } from "./types";

const app = express();
app.use(express.json());

const PORT = process.env.PORT || 3001;

// ── Health Check ──────────────────────────────────────────────────────────────
app.get("/health", (_req: Request, res: Response) => {
  res.json({ status: "ok", service: "ai_worker", version: "1.0.0" });
});

// ── Main Endpoint: Analyze Transcript → Find Best Clips ───────────────────────
app.post("/analyze", async (req: Request, res: Response) => {
  const { transcript, language = "tr", max_clips = 3 } = req.body as {
    transcript: string;
    language?: string;
    max_clips?: number;
  };

  if (!transcript || typeof transcript !== "string") {
    res.status(400).json({ error: "transcript (string) is required" });
    return;
  }

  console.log(`[AI Worker] Starting 3-agent pipeline. Transcript length: ${transcript.length} chars`);

  try {
    // Step 1 — Analyzer Agent: find candidate clips with reasoning
    const candidates: ClipCandidate[] = await analyzeClips(transcript, language, max_clips);
    console.log(`[Analyzer] Found ${candidates.length} candidates.`);

    // Step 2 — Critic Agent: review and filter
    const reviewed = await critiqueClips(candidates, transcript, language);
    console.log(`[Critic] Approved ${reviewed.length} clips after review.`);

    // Step 3 — Editor Agent: finalize precise timestamps
    const finalClips = await finalizeClips(reviewed, language);
    console.log(`[Editor] Finalized ${finalClips.length} clips.`);

    res.json({ clips: finalClips, agent_log: { analyzed: candidates.length, reviewed: reviewed.length, finalized: finalClips.length } });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Unknown error";
    console.error("[AI Worker] Pipeline error:", message);
    res.status(500).json({ error: message });
  }
});

app.listen(PORT, () => {
  console.log(`\n🤖 AI Worker running on http://localhost:${PORT}`);
  console.log(`   Agents: Analyzer → Critic → Editor (Chain-of-Thought)\n`);
});
