export const navigationRouteOwners = [
  "/settings/security",
  "/settings/sessions",
  "/settings/account",
  "/settings/tokens",
  "/settings/about",
  "/admin/users",
  "/review/knowledge",
  "/organizations",
  "/documents",
  "/contracts",
  "/timeline",
  "/upcoming",
  "/search",
  "/review",
  "/",
] as const;

export type NavigationRoute = (typeof navigationRouteOwners)[number];

export function activeNavigationRoute(pathname: string): NavigationRoute | null {
  return navigationRouteOwners.reduce<NavigationRoute | null>((owner, route) => {
    const ownsPath = route === "/"
      ? pathname === route
      : pathname === route || pathname.startsWith(`${route}/`);
    return ownsPath && (!owner || route.length > owner.length) ? route : owner;
  }, null);
}
