// Next.js configuration.
//
// SAME-ORIGIN PROXY: the browser only ever talks to this Next.js server. Requests to
// /api/* are forwarded ("rewritten") to the FastAPI backend. Benefits:
//   - no CORS: the page and the API share one origin;
//   - the refresh-token cookie (Path=/auth/session) works, because the browser sees
//     /auth/session on this same origin;
//   - the backend address never appears in browser code.

/** Where FastAPI runs. Override with API_URL in frontend/.env.local. */
const API_URL = process.env.API_URL || "http://127.0.0.1:8000";

const securityHeaders = [
  // Nobody may show this app inside a frame (stops clickjacking an "Approve" button).
  { key: "X-Frame-Options", value: "DENY" },
  // Browsers must trust the declared content type, not guess (no MIME sniffing).
  { key: "X-Content-Type-Options", value: "nosniff" },
  // Don't send full URLs (which contain run ids) to other sites.
  { key: "Referrer-Policy", value: "same-origin" },
  // No camera / microphone / location for this page or anything embedded in it.
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

/** @type {import('next').NextConfig} */
const nextConfig = {
  poweredByHeader: false, // don't advertise "X-Powered-By: Next.js"
  // DEV ONLY: the dev server serves its scripts only to localhost by default. Opening
  // http://127.0.0.1:3000 (as the E2E tests do) would load the HTML WITHOUT JavaScript.
  allowedDevOrigins: ["127.0.0.1"],
  async rewrites() {
    return [
      { source: "/api/:path*", destination: `${API_URL}/:path*` },
      // Browser login sessions keep the backend's path, so the cookie path matches.
      { source: "/auth/session", destination: `${API_URL}/auth/session` },
      { source: "/auth/session/:path*", destination: `${API_URL}/auth/session/:path*` },
    ];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
