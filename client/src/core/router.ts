/** History-based router for `/apps/<app>/action/<id>[/new|/<record>]`. */

import { signal, type Signal } from "./signals";

export interface Route {
  app: string;
  actionId: number;
  record: null | "new" | number;
  menu: number | null;
  search: URLSearchParams;
}

export const route: Signal<Route | null> = signal<Route | null>(null);

export function parseRoute(input: string = location.pathname + location.search): Route | null {
  const url = new URL(input, location.origin);
  const match = /^\/apps\/([^/]+)\/action\/(\d+)(?:\/(new|\d+))?\/?$/.exec(url.pathname);
  if (!match) return null;
  const [, app, action, tail] = match;
  if (!app || !action) return null;
  const menu = Number(url.searchParams.get("menu") ?? 0) || null;
  return {
    app,
    actionId: Number(action),
    record: tail === undefined ? null : tail === "new" ? "new" : Number(tail),
    menu,
    search: url.searchParams,
  };
}

export function navigate(url: string): void {
  const parsed = parseRoute(url);
  if (!parsed) {
    location.assign(url);
    return;
  }
  history.pushState({}, "", url);
  route.value = parsed;
}

export function syncUrl(url: string, replace = false): void {
  if (replace) history.replaceState({}, "", url);
  else history.pushState({}, "", url);
}

export function startRouter(): void {
  document.addEventListener("click", (event) => {
    if (
      event.defaultPrevented ||
      event.button !== 0 ||
      event.metaKey ||
      event.ctrlKey ||
      event.shiftKey ||
      event.altKey
    ) {
      return;
    }
    const anchor = (event.target as Element | null)?.closest<HTMLAnchorElement>("a[href]");
    if (!anchor) return;
    if (anchor.target && anchor.target !== "_self") return;
    if (anchor.hasAttribute("download")) return;
    const url = new URL(anchor.href, location.href);
    if (url.origin !== location.origin) return;
    const parsed = parseRoute(url.pathname + url.search);
    if (!parsed) return;
    event.preventDefault();
    navigate(url.pathname + url.search);
  });

  window.addEventListener("popstate", () => {
    route.value = parseRoute();
  });

  route.value = parseRoute();
}

export function routeQuery(
  params: Record<string, string | number | null | undefined>,
): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue;
    search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
