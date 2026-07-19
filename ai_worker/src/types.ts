/**
 * Shared Types for the AI Agent Pipeline
 */

export interface ClipCandidate {
  start: number;       // seconds
  end: number;         // seconds
  reason: string;      // why this moment is viral-worthy
  score: number;       // 0.0 → 1.0 virality score
  emotion: string;     // e.g. "shock", "laugh", "hype"
  approved?: boolean;  // set by CriticAgent
  critique?: string;   // feedback from CriticAgent
}

export interface FinalClip {
  start: number;
  end: number;
  duration: number;
  reason: string;
  score: number;
  emotion: string;
  hook: string;        // first-sentence hook for caption/title
}

export interface LLMMessage {
  role: "system" | "user" | "assistant";
  content: string;
}
