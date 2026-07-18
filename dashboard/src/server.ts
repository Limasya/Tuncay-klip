import express from "express";
import cors from "cors";
import { WebSocketServer } from "ws";
import http from "http";
import { HealthMonitor } from "./health.js";
import { PipelineAPI } from "./api.js";

const PORT = parseInt(process.env.DASHBOARD_PORT || "3100", 10);
const API_URL = process.env.API_URL || "http://localhost:8000";

const app = express();
app.use(cors());
app.use(express.json());

const server = http.createServer(app);
const wss = new WebSocketServer({ server, path: "/ws" });

const health = new HealthMonitor(API_URL);
const api = new PipelineAPI(API_URL);

app.get("/api/health", async (_req, res) => {
  res.json(await health.check());
});

app.get("/api/system", async (_req, res) => {
  res.json(await api.getSystemStatus());
});

app.get("/api/clips", async (_req, res) => {
  res.json(await api.getClips());
});

app.get("/api/analytics", async (_req, res) => {
  res.json(await api.getAnalytics());
});

wss.on("connection", (ws) => {
  console.log("[WS] Client connected");
  const interval = setInterval(async () => {
    if (ws.readyState === ws.OPEN) {
      ws.send(JSON.stringify(await health.check()));
    }
  }, 5000);

  ws.on("close", () => {
    clearInterval(interval);
    console.log("[WS] Client disconnected");
  });
});

health.startPeriodicChecks((status) => {
  wss.clients.forEach((client) => {
    if (client.readyState === client.OPEN) {
      client.send(JSON.stringify(status));
    }
  });
});

server.listen(PORT, () => {
  console.log(`[Dashboard] Server running on http://localhost:${PORT}`);
  console.log(`[Dashboard] WebSocket at ws://localhost:${PORT}/ws`);
  console.log(`[Dashboard] Proxying API at ${API_URL}`);
});
