import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/api/:path*",
      },
      {
        source: "/kb/:path*",
        destination: "http://localhost:8000/kb/:path*",
      },
      {
        source: "/health",
        destination: "http://localhost:8000/health",
      },
      {
        source: "/ready",
        destination: "http://localhost:8000/ready",
      },
      {
        source: "/metrics",
        destination: "http://localhost:8000/metrics",
      },
      {
        source: "/graphql",
        destination: "http://localhost:8000/graphql",
      },
    ];
  },
};

export default nextConfig;
