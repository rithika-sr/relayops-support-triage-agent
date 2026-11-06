import type { NextConfig } from "next";

// The browser only talks to this origin; /api is proxied to the FastAPI service so session cookies
// stay first-party (HttpOnly, SameSite=Lax) and CSRF checks see a same-origin request.
const apiOrigin = process.env.RELAYOPS_API_INTERNAL_URL ?? "http://127.0.0.1:8020";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  output: "standalone",
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "same-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
