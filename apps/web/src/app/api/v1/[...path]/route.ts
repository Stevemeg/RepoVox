import { NextRequest, NextResponse } from "next/server";

const allowed =
  /^(auth\/(session|sign-out|config|development\/sign-in|github\/(login|callback))|projects(\/[a-f0-9-]+(\/(jobs|video-jobs))?)?|jobs(\/[a-f0-9-]+(\/cancel)?)?|video-jobs\/[a-f0-9-]+(\/cancel|\/videos\/[a-f0-9-]+(\/(captions|download))?)?|development\/(projects\/[a-f0-9-]+\/(fixture-jobs|analysis-jobs)|jobs\/[a-f0-9-]+\/(retry|analysis)))$/;
const oauthRoute = /^auth\/github\/(login|callback)$/;
async function forward(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  const route = path.join("/");
  // GitHub sign-in: a GET-only redirect hop each way. Only the callback carries a query
  // (GitHub's code and state); every other route still refuses one.
  const oauth = oauthRoute.test(route);
  const search = request.nextUrl.search;
  const query =
    route === "auth/github/callback" && search.length <= 2048 ? search : "";
  if (
    !allowed.test(route) ||
    (search && !query) ||
    (oauth && request.method !== "GET")
  )
    return NextResponse.json({ error: { code: "not_found" } }, { status: 404 });
  const headers = new Headers();
  for (const name of [
    "cookie",
    "origin",
    "content-type",
    "x-csrf-token",
    "idempotency-key",
    "x-request-id",
    "range",
  ]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  const media = /\/videos\/[a-f0-9-]+(\/(captions|download))?$/.test(route);
  const mutating = !["GET", "HEAD"].includes(request.method);
  let body: string | undefined;
  if (mutating && request.body) {
    const reader = request.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 16384) {
        await reader.cancel();
        return NextResponse.json(
          { error: { code: "request_too_large" } },
          { status: 413 },
        );
      }
      chunks.push(value);
    }
    body = Buffer.concat(chunks).toString("utf-8");
  }
  try {
    const upstream = await fetch(
      `${process.env.REPOVOX_API_URL || "http://localhost:8000"}/v1/${route}${query}`,
      {
        method: request.method,
        headers,
        body,
        cache: "no-store",
        // The sign-in redirect is handed to the browser, never followed here.
        redirect: oauth ? "manual" : "error",
        // Resolution has a 10-second aggregate limit; leave bounded DB publication time.
        signal: AbortSignal.timeout(
          media
            ? 60000
            : /\/(analysis|video)-jobs$/.test(route)
              ? 15000
              : 10000,
        ),
      },
    );
    const response = new NextResponse(upstream.body, {
      status: upstream.status,
    });
    for (const name of [
      "content-type",
      "x-request-id",
      ...(oauth ? ["location"] : []),
      // Byte-range playback and download of an owner-authorized video only.
      ...(media
        ? [
            "content-range",
            "accept-ranges",
            "content-length",
            "content-disposition",
          ]
        : []),
    ]) {
      const value = upstream.headers.get(name);
      if (value) response.headers.set(name, value);
    }
    for (const cookie of upstream.headers.getSetCookie())
      response.headers.append("set-cookie", cookie);
    response.headers.set("cache-control", "no-store");
    return response;
  } catch {
    return NextResponse.json(
      { error: { code: "dependency_unavailable" } },
      { status: 503 },
    );
  }
}
export { forward as GET, forward as POST, forward as PATCH, forward as DELETE };
