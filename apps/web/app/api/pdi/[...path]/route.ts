import { NextRequest } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

type RouteContext = { params: Promise<{ path: string[] }> };

const REQUEST_HEADERS = ["accept", "content-type", "range", "if-range", "x-csrf-token"];
const RESPONSE_HEADERS = [
  "accept-ranges",
  "cache-control",
  "content-disposition",
  "content-length",
  "content-range",
  "content-security-policy",
  "content-type",
  "etag",
  "last-modified",
  "referrer-policy",
  "x-content-type-options",
  "x-frame-options",
];

async function forward(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  const base = process.env.PDI_API_INTERNAL_URL ?? "http://localhost:8000";
  const upstreamUrl = new URL(`/${path.map(encodeURIComponent).join("/")}`, base);
  upstreamUrl.search = request.nextUrl.search;

  const headers = new Headers();
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("cookie", cookie);
  for (const name of REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const upstream = await fetch(upstreamUrl, {
    method: request.method,
    headers,
    body: hasBody ? await request.arrayBuffer() : undefined,
    cache: "no-store",
    redirect: "manual",
  });

  const responseHeaders = new Headers();
  for (const name of RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  const cookieHeaders = (
    upstream.headers as Headers & { getSetCookie?: () => string[] }
  ).getSetCookie?.();
  if (cookieHeaders?.length) {
    for (const value of cookieHeaders) responseHeaders.append("set-cookie", value);
  } else {
    const value = upstream.headers.get("set-cookie");
    if (value) responseHeaders.append("set-cookie", value);
  }

  return new Response(upstream.status === 204 ? null : upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export const GET = forward;
export const HEAD = forward;
export const POST = forward;
