/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  outputFileTracingIncludes: {
    "/api/chat": ["../docs/CHATBOT_KNOWLEDGE_BASE.md"],
  },
  async rewrites() {
    if (process.env.NEXT_PUBLIC_API_URL) {
      return [];
    }

    const apiBase = process.env.INTERNAL_API_URL ?? "http://127.0.0.1:8000";
    return [
      { source: "/auth/:path*", destination: `${apiBase}/auth/:path*` },
      { source: "/status", destination: `${apiBase}/status` },
      { source: "/forecast", destination: `${apiBase}/forecast` },
      { source: "/optimize", destination: `${apiBase}/optimize` },
      { source: "/data-feeds", destination: `${apiBase}/data-feeds` },
      { source: "/feature-importance", destination: `${apiBase}/feature-importance` },
      { source: "/api-keys/:path*", destination: `${apiBase}/api-keys/:path*` },
      { source: "/audit", destination: `${apiBase}/audit` }
    ];
  },
  async headers() {
    const apiBase = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
    const connectSrc = ["'self'", apiBase, "http://localhost:8000", "http://127.0.0.1:8000"];
    const scriptSrc = ["'self'", "'unsafe-inline'"];

    if (process.env.NODE_ENV !== "production") {
      scriptSrc.push("'unsafe-eval'");
      connectSrc.push("ws://localhost:3000", "ws://127.0.0.1:3000");
    }

    return [
      {
        source: "/(.*)",
        headers: [
          {
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              `script-src ${scriptSrc.join(" ")}`,
              "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data:",
              "font-src 'self' data:",
              `connect-src ${Array.from(new Set(connectSrc)).join(" ")}`,
              "frame-ancestors 'none'",
              "base-uri 'self'",
              "form-action 'self'"
            ].join("; ")
          },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          // HSTS: only sent in production (APP_COOKIE_SECURE=true deployments behind TLS).
          ...(process.env.NODE_ENV === "production"
            ? [{ key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" }]
            : [])
        ]
      }
    ];
  }
};

export default nextConfig;
