import type { NextConfig } from "next";

// The browser only ever talks to this origin; /api is proxied to FastAPI so the
// session cookie stays first-party.
const api = process.env.API_URL ?? "http://localhost:8000";

// Everything the app loads comes from its own origin (fonts are self-hosted by
// next/font). Scripts still need 'unsafe-inline' for Next's hydration data and the
// theme script that runs before paint; nonces would make every page dynamic.
// The dev server needs eval, so the policy only applies to production builds.
const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "media-src 'self' blob:",
  "font-src 'self'",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${api}/:path*` }];
  },
  async headers() {
    if (process.env.NODE_ENV !== "production") return [];
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Content-Security-Policy", value: csp },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
        ],
      },
    ];
  },
};

export default config;
