interface HealthStatus {
  status: "healthy" | "degraded" | "down";
  timestamp: string;
  uptime_sec: number;
  services: Record<string, ServiceHealth>;
  memory: MemoryInfo;
}

interface ServiceHealth {
  status: "up" | "down" | "slow";
  latency_ms: number;
  last_check: string;
}

interface MemoryInfo {
  rss_mb: number;
  heap_used_mb: number;
  heap_total_mb: number;
}

export class HealthMonitor {
  private apiUrl: string;
  private startTime: number;
  private lastStatus: HealthStatus | null = null;

  constructor(apiUrl: string) {
    this.apiUrl = apiUrl;
    this.startTime = Date.now();
  }

  async check(): Promise<HealthStatus> {
    const services: Record<string, ServiceHealth> = {};

    const checkService = async (name: string, url: string): Promise<void> => {
      const start = Date.now();
      try {
        const resp = await fetch(url, { signal: AbortSignal.timeout(3000) });
        services[name] = {
          status: resp.ok ? "up" : "down",
          latency_ms: Date.now() - start,
          last_check: new Date().toISOString(),
        };
      } catch {
        services[name] = {
          status: "down",
          latency_ms: Date.now() - start,
          last_check: new Date().toISOString(),
        };
      }
    };

    await Promise.all([
      checkService("api", `${this.apiUrl}/health`),
      checkService("pipeline", `${this.apiUrl}/api/system/status`),
    ]);

    const mem = process.memoryUsage();
    const overallStatus = Object.values(services).every((s) => s.status === "up")
      ? "healthy"
      : Object.values(services).some((s) => s.status === "up")
        ? "degraded"
        : "down";

    const status: HealthStatus = {
      status: overallStatus,
      timestamp: new Date().toISOString(),
      uptime_sec: Math.floor((Date.now() - this.startTime) / 1000),
      services,
      memory: {
        rss_mb: Math.round(mem.rss / 1024 / 1024),
        heap_used_mb: Math.round(mem.heapUsed / 1024 / 1024),
        heap_total_mb: Math.round(mem.heapTotal / 1024 / 1024),
      },
    };

    this.lastStatus = status;
    return status;
  }

  startPeriodicChecks(callback: (status: HealthStatus) => void): void {
    setInterval(async () => {
      const status = await this.check();
      callback(status);
    }, 10000);
  }

  getLastStatus(): HealthStatus | null {
    return this.lastStatus;
  }
}
