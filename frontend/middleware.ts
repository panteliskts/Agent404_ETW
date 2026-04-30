import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "bess_session";
const PROTECTED_ROUTES = ["/dashboard", "/onboarding", "/account"];

function isProtectedRoute(pathname: string) {
  return PROTECTED_ROUTES.some((route) => pathname === route || pathname.startsWith(`${route}/`));
}

function loginUrl(request: NextRequest) {
  const url = request.nextUrl.clone();
  const nextPath = `${request.nextUrl.pathname}${request.nextUrl.search}`;
  url.pathname = "/login";
  url.search = "";
  url.searchParams.set("next", nextPath);
  return url;
}

export function middleware(request: NextRequest) {
  if (!isProtectedRoute(request.nextUrl.pathname)) {
    return NextResponse.next();
  }

  const hasSessionCookie = Boolean(request.cookies.get(SESSION_COOKIE)?.value);
  if (!hasSessionCookie) {
    return NextResponse.redirect(loginUrl(request));
  }

  return NextResponse.next();
}

export const config = {
  matcher: ["/dashboard/:path*", "/onboarding/:path*", "/account/:path*"]
};
