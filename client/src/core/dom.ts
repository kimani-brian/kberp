/** DOM helpers. Every record value enters the page as text, never as HTML. */

export type Child = Node | string | number | null | undefined | false;
export type AttrValue = string | number | boolean | null | undefined;

export function h<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  attrs: Record<string, AttrValue | ((event: Event) => void)> = {},
  ...children: Child[]
): HTMLElementTagNameMap[K] {
  const element = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === null || value === undefined || value === false) continue;
    if (typeof value === "function") {
      element.addEventListener(key.replace(/^on/, "").toLowerCase(), value);
      continue;
    }
    if (key === "class") {
      element.className = String(value);
    } else if (key === "text") {
      element.textContent = String(value);
    } else if (key === "checked") {
      (element as unknown as HTMLInputElement).checked = Boolean(value);
    } else if (key === "value") {
      (element as unknown as HTMLInputElement).value = String(value);
    } else {
      element.setAttribute(key, value === true ? "" : String(value));
    }
  }
  append(element, children);
  return element;
}

function append(parent: HTMLElement, children: Child[]): void {
  for (const child of children) {
    if (child === null || child === undefined || child === false) continue;
    if (Array.isArray(child)) {
      append(parent, child as Child[]);
    } else if (child instanceof Node) {
      parent.appendChild(child);
    } else {
      parent.appendChild(document.createTextNode(String(child)));
    }
  }
}

export function clear(element: Element): void {
  while (element.firstChild) element.removeChild(element.firstChild);
}

let loader: HTMLElement | null = null;

export function setLoading(active: boolean): void {
  if (!loader) {
    loader = h("div", {
      id: "kwl-loading",
      class: "kwl-loading",
      role: "progressbar",
      "aria-label": "Loading",
      "aria-hidden": "true",
    });
    document.body.appendChild(loader);
  }
  loader.setAttribute("aria-hidden", String(!active));
  if (active) {
    loader.classList.remove("is-settling");
    loader.classList.add("is-active");
    return;
  }
  if (loader.classList.contains("is-active")) {
    loader.classList.add("is-settling");
    window.setTimeout(() => {
      loader?.classList.remove("is-active", "is-settling");
    }, 220);
  }
}
