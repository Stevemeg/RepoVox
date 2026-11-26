import { NextResponse, type NextRequest } from "next/server";
import { isUuid } from "@/lib/security";

/*
 * Request boundary for record pages (Next.js 16 `proxy` convention, formerly middleware).
 *
 * /projects/<id> and /jobs/<id> are dynamic routes under a streaming loading boundary, so a
 * page-level notFound() for a malformed id arrives after HTTP 200 is already committed.
 * Here, before any rendering, a segment that is not a lowercase UUID is rewritten to a path
 * no route can match (app/ folders starting with "_" are private, never routes). Next.js
 * then renders app/not-found.tsx with a real HTTP 404 and the next.config.ts security
 * headers. No API request is made and nothing about the request is echoed back: the only
 * trace is Next.js's own `x-middleware-rewrite` client-router header, which names this fixed
 * sentinel path (relative when the server binds 0.0.0.0, as the web image does).
 *
 * The check runs on the raw, still percent-encoded segment and fails closed: an encoded,
 * uppercase or otherwise unexpected id is a 404 even if it would decode to a valid UUID.
 * The pages keep their own isUuid() guards as defence in depth.
 */
const RECORD_PAGE = /^\/(?:projects|jobs)\/([^/]+)$/;
const NOT_FOUND = "/_not-a-route/malformed-record-id";

export function proxy(request: NextRequest) {
  const segment = RECORD_PAGE.exec(request.nextUrl.pathname)?.[1];
  if (segment !== undefined && isUuid(segment)) return NextResponse.next();
  return NextResponse.rewrite(new URL(NOT_FOUND, request.url));
}

export const config = {
  matcher: ["/projects/:id", "/jobs/:id"],
};
