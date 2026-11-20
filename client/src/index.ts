import { BusClient, busStatusLabel } from "./core/bus";
import { clear, h, setLoading } from "./core/dom";
import { registry } from "./core/registry";
import { effect } from "./core/signals";
import { route, startRouter, syncUrl, type Route } from "./core/router";
import { rpc, RpcError } from "./core/rpc";
import { takeServerFlash, toast } from "./core/toast";
import type { FormPayload, ListPayload } from "./types";
import { renderForm } from "./views/form";
import { renderList } from "./views/list";

type ListRenderer = (payload: ListPayload) => DocumentFragment;
type FormRenderer = (
  payload: FormPayload,
  onSaved: (payload: FormPayload, url: string) => void,
) => DocumentFragment;

function meta(name: string): string {
  return document.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)?.content ?? "";
}

function boot(): void {
  const main = document.querySelector<HTMLElement>("main");
  const userId = Number(meta("kberp-user") || 0);
  if (!main || !userId) return;
  const host: HTMLElement = main;

  registry.add<ListRenderer>("views", "list", renderList);
  registry.add<FormRenderer>("views", "form", renderForm);

  takeServerFlash();
  const bus = startBus(userId);

  let renderToken = 0;

  const mount = (fragment: DocumentFragment, animate = true): void => {
    clear(host);
    host.appendChild(fragment);
    if (animate) {
      host.classList.add("kwl-enter");
      requestAnimationFrame(() => host.classList.remove("kwl-enter"));
    }
  };

  const mountForm = (payload: FormPayload, url: string): void => {
    syncUrl(url, true);
    const view = registry.get<FormRenderer>("views", "form");
    if (view) mount(view(payload, mountForm));
  };

  effect(() => {
    const current = route.value;
    if (!current) return;
    void showRoute(current);
  });

  async function showRoute(current: Route): Promise<void> {
    const token = ++renderToken;
    setLoading(true);
    host.classList.add("is-loading");
    try {
      if (current.record === null) {
        const payload = await rpc<ListPayload>("view.load", {
          app: current.app,
          action_id: current.actionId,
          q: current.search.get("q") ?? "",
          filter: current.search.get("filter") ?? "",
          offset: Number(current.search.get("offset") ?? 0),
          menu: current.menu,
          view: current.search.get("view") ?? "",
          group_by: current.search.get("group_by") ?? "",
        });
        if (token !== renderToken) return;
        const view = registry.get<ListRenderer>("views", "list");
        if (view) mount(view(payload));
      } else {
        const payload = await rpc<FormPayload>("view.form", {
          app: current.app,
          action_id: current.actionId,
          id: current.record === "new" ? null : current.record,
          menu: current.menu,
        });
        if (token !== renderToken) return;
        const view = registry.get<FormRenderer>("views", "form");
        if (view) mount(view(payload, mountForm));
      }
    } catch (error) {
      if (token !== renderToken) return;
      toast(
        error instanceof RpcError ? error.message : "This screen could not be loaded.",
        "danger",
      );
    } finally {
      if (token === renderToken) {
        host.classList.remove("is-loading");
        setLoading(false);
      }
    }
  }

  void bus;
  startRouter();
  window.addEventListener("beforeunload", () => bus.close());
}

function startBus(userId: number): BusClient {
  const channels = `platform,user.${userId}`;
  const bus = new BusClient(channels, (message) => {
    if (message.event === "platform.ping") {
      toast("Platform heartbeat delivered.", "info");
      return;
    }
    toast(`Document update: ${message.event}`, "info");
  });
  const dot = h("span", {
    class: "bus-status is-connecting",
    role: "status",
    "aria-label": busStatusLabel("connecting"),
    title: busStatusLabel("connecting"),
  });
  const right = document.querySelector(".topbar-right");
  if (right) right.insertBefore(dot, right.firstChild);

  effect(() => {
    const status = bus.status.value;
    dot.className = `bus-status is-${status}`;
    dot.setAttribute("aria-label", busStatusLabel(status));
    dot.setAttribute("title", busStatusLabel(status));
  });

  bus.start();
  return bus;
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot);
} else {
  boot();
}
