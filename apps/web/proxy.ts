import { NextRequest, NextResponse } from "next/server";

async function setupRequired() {
  const base = process.env.PDI_API_INTERNAL_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(`${base}/api/v1/setup/status`, { cache: "no-store" });
    if (!response.ok) return null;
    return Boolean((await response.json() as { setup_required?: boolean }).setup_required);
  } catch {
    return null;
  }
}

async function sessionIsValid(cookie: string) {
  const base = process.env.PDI_API_INTERNAL_URL ?? "http://localhost:8000";
  try {
    const response = await fetch(`${base}/api/v1/auth/session`, {
      cache: "no-store",
      headers: { cookie },
    });
    return response.ok;
  } catch {
    return false;
  }
}

export async function proxy(request: NextRequest) {
  if (process.env.PDI_AUTH_ENABLED !== "true") return NextResponse.next();
  const path = request.nextUrl.pathname;
  if (path.startsWith("/_next/") || path === "/favicon.ico") {
    return NextResponse.next();
  }
  const cookie = request.headers.get("cookie");
  if (request.cookies.has("pdi_session") && cookie && await sessionIsValid(cookie)) {
    return path === "/setup"
      ? NextResponse.redirect(new URL("/", request.url))
      : NextResponse.next();
  }
  const required = await setupRequired();
  if (required) {
    return path === "/setup"
      ? NextResponse.next()
      : NextResponse.redirect(new URL("/setup", request.url));
  }
  if (path === "/setup") return NextResponse.redirect(new URL("/login", request.url));
  if (path !== "/login") {
    const login = new URL("/login", request.url);
    login.searchParams.set("next", path);
    return NextResponse.redirect(login);
  }
  return NextResponse.next();
}

export const config = { matcher: ["/((?!api).*)"] };
