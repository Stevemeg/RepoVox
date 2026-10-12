import { NextRequest, NextResponse } from "next/server";

const allowed =
  /^(auth\/(session|sign-out|development\/sign-in)|projects(\/[a-f0-9-]+(\/jobs)?)?|jobs(\/[a-f0-9-]+(\/cancel)?)?|development\/(projects\/[a-f0-9-]+\/fixture-jobs|jobs\/[a-f0-9-]+\/retry))$/;
async function forward(
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) {
  const { path } = await context.params;
  const route = path.join("/");
  if (!allowed.test(route) || request.nextUrl.search)
    return NextResponse.json({ error: { code: "not_found" } }, { status: 404 });
  const headers = new Headers();
  for (const name of [
    "cookie",
    "origin",
    "content-type",
    "x-csrf-token",
    "idempotency-key",
    "x-request-id",
  ]) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
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
      `${process.env.REPOVOX_API_URL || "http://localhost:8000"}/v1/${route}`,
      {
        method: request.method,
        headers,
        body,
        cache: "no-store",
        redirect: "error",
        signal: AbortSignal.timeout(10000),
      },
    );
    const response = new NextResponse(upstream.body, {
      status: upstream.status,
    });
    for (const name of ["content-type", "x-request-id"]) {
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
