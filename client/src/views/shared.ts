import { h } from "../core/dom";
import { routeQuery } from "../core/router";
import type { Breadcrumb } from "../types";

export function breadcrumbs(items: Breadcrumb[]): HTMLElement {
  const nav = h("nav", { class: "breadcrumbs", "aria-label": "Breadcrumb" });
  items.forEach((crumb, index) => {
    if (crumb.url) {
      nav.appendChild(h("a", { href: crumb.url }, crumb.name));
    } else {
      nav.appendChild(h("span", { "aria-current": "page" }, crumb.name));
    }
    if (index < items.length - 1) {
      nav.appendChild(h("span", { class: "crumb-sep" }, "/"));
    }
  });
  return nav;
}

export function listHref(
  baseUrl: string,
  params: Record<string, string | number | null | undefined>,
): string {
  return `${baseUrl}${routeQuery(params)}`;
}

export function readOnlyNote(canCreate: boolean, canWrite: boolean): HTMLElement | null {
  if (canWrite) return null;
  const message = canCreate
    ? "You can create records here but not edit existing ones."
    : "Read-only access. You can view these records but not change them.";
  return h("p", { class: "permission-note", role: "status" }, message);
}
