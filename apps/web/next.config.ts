import type { NextConfig } from "next";

/*
 * Security headers on every response: pages, not-found pages (including the malformed
 * record id 404s from src/proxy.ts), static assets and the /api/v1 proxy.
 *
 * Content-Security-Policy locks every fetch directive to this origin. `script-src` and
 * `style-src` keep 'unsafe-inline' because the App Router streams its flight data and
 * bootstrap as inline <script> tags and the standalone server's static routes cannot carry
 * a per-request nonce; removing it would break hydration. No other source is allowed:
 * no 'unsafe-eval', no remote hosts, no plugins (object-src 'none') and no framing.
 * media-src 'self' covers <video> and its WebVTT <track>, both served through the proxy.
 *
 * Permissions-Policy denies the powerful features RepoVox never uses. fullscreen and
 * picture-in-picture are deliberately not listed, so native video controls keep working.
 */
const CONTENT_SECURITY_POLICY = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "media-src 'self'",
  "font-src 'self'",
  "connect-src 'self'",
  "object-src 'none'",
  "worker-src 'self'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "same-origin" },
          { key: "Content-Security-Policy", value: CONTENT_SECURITY_POLICY },
          {
            key: "Permissions-Policy",
            value: "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
          },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          { key: "Cross-Origin-Resource-Policy", value: "same-origin" },
        ],
      },
    ];
  },
};
export default config;
