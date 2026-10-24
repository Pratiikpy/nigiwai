import type { NextConfig } from "next";

// The browser only ever talks to this origin. `/api/v1/*` is forwarded to the API, so session cookies are
// first-party and no CORS is needed.
const apiOrigin = process.env.NIGIWAI_API_ORIGIN ?? "http://127.0.0.1:8000";

// What a page may load. Scripts and styles are this origin's own, plus the inline bootstraps Next.js and the theme script write into the
// page (a nonce would force every page to render per request, and it would still allow those); anything else, such as a script or a form
// post to another site, is refused. The one third party is OpenFreeMap, which draws the crowd map. Development needs `eval` for hot reload.
const production = process.env.NODE_ENV === "production";
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${production ? "" : " 'unsafe-eval'"}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://tiles.openfreemap.org",
  "font-src 'self' data:",
  "connect-src 'self' https://tiles.openfreemap.org",
  "worker-src 'self' blob:",
  "child-src blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  reactStrictMode: true,
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${apiOrigin}/v1/:path*` }];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(self)" },
          { key: "Content-Security-Policy", value: csp },
          // Browsers honour this only over https, so it does nothing on a plain-http development server.
          { key: "Strict-Transport-Security", value: "max-age=31536000" },
        ],
      },
    ];
  },
};

export default nextConfig;
