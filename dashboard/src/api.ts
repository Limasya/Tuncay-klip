export class PipelineAPI {
  private apiUrl: string;

  constructor(apiUrl: string) {
    this.apiUrl = apiUrl;
  }

  private async get<T>(path: string): Promise<T> {
    try {
      const resp = await fetch(`${this.apiUrl}${path}`, {
        signal: AbortSignal.timeout(5000),
      });
      if (!resp.ok) {
        throw new Error(`HTTP ${resp.status}`);
      }
      return (await resp.json()) as T;
    } catch (err) {
      console.error(`[API] GET ${path} failed:`, err);
      return {} as T;
    }
  }

  async getSystemStatus(): Promise<Record<string, unknown>> {
    return this.get("/health");
  }

  async getClips(): Promise<unknown[]> {
    const data = await this.get<{ clips?: unknown[] }>("/api/clips");
    return data.clips || [];
  }

  async getAnalytics(): Promise<Record<string, unknown>> {
    return this.get("/api/analytics/summary");
  }

  async triggerSync(): Promise<Record<string, unknown>> {
    try {
      const resp = await fetch(`${this.apiUrl}/api/zero-bandwidth/sync`, {
        method: "POST",
        signal: AbortSignal.timeout(10000),
      });
      return (await resp.json()) as Record<string, unknown>;
    } catch (err) {
      return { success: false, error: String(err) };
    }
  }
}
