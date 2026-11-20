/** Toasts use one aria-live region so screen readers hear them once. */

import { h } from "./dom";

export type ToastLevel = "info" | "success" | "warning" | "danger";

let region: HTMLElement | null = null;

function ensureRegion(): HTMLElement {
  if (region && document.body.contains(region)) return region;
  region = h("div", {
    class: "toast-region",
    role: "status",
    "aria-live": "polite",
    "aria-atomic": "false",
  });
  document.body.appendChild(region);
  return region;
}

export function toast(message: string, level: ToastLevel = "info", timeout = 5200): void {
  const host = ensureRegion();
  const item = h(
    "div",
    { class: `toast toast-${level}`, role: "status" },
    h("p", { class: "toast-message", text: message }),
    h(
      "button",
      {
        class: "toast-close",
        type: "button",
        "aria-label": "Dismiss notification",
        onclick: () => dismiss(item),
      },
      "\u00d7",
    ),
  );
  host.appendChild(item);
  requestAnimationFrame(() => item.classList.add("is-in"));
  window.setTimeout(() => dismiss(item), timeout);
}

function dismiss(item: HTMLElement): void {
  if (!item.isConnected) return;
  item.classList.add("is-out");
  window.setTimeout(() => item.remove(), 220);
}

export function takeServerFlash(): void {
  document.querySelectorAll<HTMLElement>(".flash").forEach((flash) => {
    const text = flash.textContent?.trim() ?? "";
    if (text) {
      const level = flash.classList.contains("flash-danger")
        ? "danger"
        : flash.classList.contains("flash-warning")
          ? "warning"
          : "success";
      toast(text.replace("×", "").trim(), level);
    }
    flash.remove();
  });
}
