import { NextRequest, NextResponse } from "next/server";

export function proxy(request: NextRequest) {
  if (process.env.PDI_AUTH_ENABLED !== "true") return NextResponse.next();
  const path = request.nextUrl.pathname;
  if (path === "/login" || path.startsWith("/_next/") || path === "/favicon.ico") {
    return NextResponse.next();
  }
  if (!request.cookies.has("pdi_session")) {
    const login = new URL("/login", request.url);
    login.searchParams.set("next", path);
    return NextResponse.redirect(login);
  }
  return NextResponse.next();
}

export const config = { matcher: ["/((?!api).*)"] };
