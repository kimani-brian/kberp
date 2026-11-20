"use strict";
(() => {
  var __defProp = Object.defineProperty;
  var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: true, configurable: true, writable: true, value }) : obj[key] = value;
  var __publicField = (obj, key, value) => __defNormalProp(obj, typeof key !== "symbol" ? key + "" : key, value);

  // src/core/signals.ts
  var activeEffect = null;
  var pending = /* @__PURE__ */ new Set();
  var scheduled = false;
  function schedule(subscriber) {
    pending.add(subscriber);
    if (scheduled) return;
    scheduled = true;
    queueMicrotask(() => {
      scheduled = false;
      const work = Array.from(pending);
      pending.clear();
      for (const item of work) item();
    });
  }
  var Signal = class {
    constructor(current) {
      this.current = current;
      __publicField(this, "subscribers", /* @__PURE__ */ new Set());
    }
    get value() {
      if (activeEffect) this.subscribers.add(activeEffect);
      return this.current;
    }
    set value(next) {
      if (Object.is(next, this.current)) return;
      this.current = next;
      for (const subscriber of this.subscribers) schedule(subscriber);
    }
    update(fn) {
      this.value = fn(this.value);
    }
  };
  function signal(initial) {
    return new Signal(initial);
  }
  function effect(fn) {
    const run = () => {
      const previous = activeEffect;
      activeEffect = run;
      try {
        fn();
      } finally {
        activeEffect = previous;
      }
    };
    run();
    return () => {
    };
  }

  // src/core/bus.ts
  var BusClient = class {
    constructor(channels, handler) {
      this.channels = channels;
      this.handler = handler;
      __publicField(this, "status", signal("connecting"));
      __publicField(this, "socket", null);
      __publicField(this, "last", 0);
      __publicField(this, "stopped", false);
      __publicField(this, "reconnectTimer");
      __publicField(this, "pollTimer");
      __publicField(this, "polling", false);
    }
    start() {
      this.connect();
    }
    close() {
      this.stopped = true;
      this.stopPolling();
      if (this.reconnectTimer) window.clearTimeout(this.reconnectTimer);
      this.socket?.close();
      this.socket = null;
    }
    setStatus(status) {
      this.status.value = status;
    }
    endpoint() {
      const params = new URLSearchParams({ channels: this.channels });
      if (this.last) params.set("after", String(this.last));
      return `/web/bus?${params.toString()}`;
    }
    connect() {
      if (this.stopped) return;
      this.setStatus("connecting");
      if (!("WebSocket" in window)) {
        this.startPolling();
        return;
      }
      let socket;
      try {
        const scheme = location.protocol === "https:" ? "wss" : "ws";
        socket = new WebSocket(`${scheme}://${location.host}${this.endpoint()}`);
      } catch {
        this.startPolling();
        return;
      }
      this.socket = socket;
      const helloTimer = window.setTimeout(() => {
        if (this.status.value === "connecting") socket.close();
      }, 6e3);
      socket.addEventListener("open", () => {
        this.stopPolling();
      });
      socket.addEventListener("message", (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === "hello") {
            window.clearTimeout(helloTimer);
            this.last = Math.max(this.last, Number(data.latest ?? 0));
            this.setStatus("live");
            return;
          }
          if (data.type === "bus" && typeof data.id === "number") {
            this.accept(data);
          }
        } catch {
        }
      });
      socket.addEventListener("close", () => {
        window.clearTimeout(helloTimer);
        this.socket = null;
        if (this.stopped) return;
        this.setStatus("offline");
        this.startPolling();
        this.scheduleReconnect();
      });
      socket.addEventListener("error", () => {
        socket.close();
      });
    }
    scheduleReconnect() {
      if (this.reconnectTimer || this.stopped) return;
      this.reconnectTimer = window.setTimeout(() => {
        this.reconnectTimer = void 0;
        this.connect();
      }, 2e3);
    }
    accept(message) {
      if (message.id <= this.last) return;
      this.last = message.id;
      this.handler(message);
    }
    startPolling() {
      if (this.polling || this.stopped) return;
      this.polling = true;
      this.setStatus("polling");
      const tick = async () => {
        if (this.stopped || !this.polling) return;
        try {
          const response = await fetch(this.endpoint(), { credentials: "same-origin" });
          if (response.ok) {
            const data = await response.json();
            for (const message of data.messages ?? []) this.accept(message);
            this.last = Math.max(this.last, Number(data.latest ?? 0));
            if (!this.socket) this.setStatus("polling");
          } else {
            this.setStatus("offline");
          }
        } catch {
          this.setStatus("offline");
        }
        this.pollTimer = window.setTimeout(() => void tick(), 4e3);
      };
      void tick();
    }
    stopPolling() {
      this.polling = false;
      if (this.pollTimer) window.clearTimeout(this.pollTimer);
      this.pollTimer = void 0;
    }
  };
  function busStatusLabel(status) {
    switch (status) {
      case "live":
        return "Realtime connected";
      case "polling":
        return "Realtime polling";
      case "offline":
        return "Realtime offline";
      default:
        return "Realtime connecting";
    }
  }

  // src/core/dom.ts
  function h(tag, attrs = {}, ...children) {
    const element = document.createElement(tag);
    for (const [key, value] of Object.entries(attrs)) {
      if (value === null || value === void 0 || value === false) continue;
      if (typeof value === "function") {
        element.addEventListener(key.replace(/^on/, "").toLowerCase(), value);
        continue;
      }
      if (key === "class") {
        element.className = String(value);
      } else if (key === "text") {
        element.textContent = String(value);
      } else if (key === "checked") {
        element.checked = Boolean(value);
      } else if (key === "value") {
        element.value = String(value);
      } else {
        element.setAttribute(key, value === true ? "" : String(value));
      }
    }
    append(element, children);
    return element;
  }
  function append(parent, children) {
    for (const child of children) {
      if (child === null || child === void 0 || child === false) continue;
      if (Array.isArray(child)) {
        append(parent, child);
      } else if (child instanceof Node) {
        parent.appendChild(child);
      } else {
        parent.appendChild(document.createTextNode(String(child)));
      }
    }
  }
  function clear(element) {
    while (element.firstChild) element.removeChild(element.firstChild);
  }
  var loader = null;
  function setLoading(active) {
    if (!loader) {
      loader = h("div", {
        id: "kwl-loading",
        class: "kwl-loading",
        role: "progressbar",
        "aria-label": "Loading",
        "aria-hidden": "true"
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

  // src/core/registry.ts
  var Registry = class {
    constructor() {
      __publicField(this, "categories", /* @__PURE__ */ new Map());
    }
    category(name) {
      let bucket = this.categories.get(name);
      if (!bucket) {
        bucket = /* @__PURE__ */ new Map();
        this.categories.set(name, bucket);
      }
      return bucket;
    }
    add(category, name, value) {
      this.category(category).set(name, value);
    }
    get(category, name) {
      return this.category(category).get(name);
    }
  };
  var registry = new Registry();

  // src/core/router.ts
  var route = signal(null);
  function parseRoute(input = location.pathname + location.search) {
    const url = new URL(input, location.origin);
    const match = /^\/apps\/([^/]+)\/action\/(\d+)(?:\/(new|\d+))?\/?$/.exec(url.pathname);
    if (!match) return null;
    const [, app, action, tail] = match;
    if (!app || !action) return null;
    const menu = Number(url.searchParams.get("menu") ?? 0) || null;
    return {
      app,
      actionId: Number(action),
      record: tail === void 0 ? null : tail === "new" ? "new" : Number(tail),
      menu,
      search: url.searchParams
    };
  }
  function navigate(url) {
    const parsed = parseRoute(url);
    if (!parsed) {
      location.assign(url);
      return;
    }
    history.pushState({}, "", url);
    route.value = parsed;
  }
  function syncUrl(url, replace = false) {
    if (replace) history.replaceState({}, "", url);
    else history.pushState({}, "", url);
  }
  function startRouter() {
    document.addEventListener("click", (event) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      const anchor = event.target?.closest("a[href]");
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
  function routeQuery(params) {
    const search = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      if (value === null || value === void 0 || value === "") continue;
      search.set(key, String(value));
    }
    const text = search.toString();
    return text ? `?${text}` : "";
  }

  // src/core/rpc.ts
  var RpcError = class extends Error {
    constructor(message, code = -32e3) {
      super(message);
      this.code = code;
      this.name = "RpcError";
    }
  };
  var nextId = 1;
  function meta(name) {
    return document.querySelector(`meta[name="${name}"]`)?.content ?? "";
  }
  function csrfToken() {
    return meta("kberp-csrf");
  }
  async function rpc(method, params = {}) {
    const id = nextId++;
    let response;
    try {
      response = await fetch("/web/rpc", {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": csrfToken()
        },
        body: JSON.stringify({ jsonrpc: "2.0", id, method, params })
      });
    } catch {
      throw new RpcError("The server is unreachable. Check your connection and try again.");
    }
    const text = await response.text();
    let payload;
    try {
      payload = JSON.parse(text);
    } catch {
      throw new RpcError("Your session expired. Reload the page and sign in again.");
    }
    if (payload.error) {
      throw new RpcError(payload.error.message ?? "The request failed.", payload.error.code);
    }
    if (payload.result === void 0) {
      throw new RpcError("The server returned an empty response.");
    }
    return payload.result;
  }

  // src/core/toast.ts
  var region = null;
  function ensureRegion() {
    if (region && document.body.contains(region)) return region;
    region = h("div", {
      class: "toast-region",
      role: "status",
      "aria-live": "polite",
      "aria-atomic": "false"
    });
    document.body.appendChild(region);
    return region;
  }
  function toast(message, level = "info", timeout = 5200) {
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
          onclick: () => dismiss(item)
        },
        "\xD7"
      )
    );
    host.appendChild(item);
    requestAnimationFrame(() => item.classList.add("is-in"));
    window.setTimeout(() => dismiss(item), timeout);
  }
  function dismiss(item) {
    if (!item.isConnected) return;
    item.classList.add("is-out");
    window.setTimeout(() => item.remove(), 220);
  }
  function takeServerFlash() {
    document.querySelectorAll(".flash").forEach((flash) => {
      const text = flash.textContent?.trim() ?? "";
      if (text) {
        const level = flash.classList.contains("flash-danger") ? "danger" : flash.classList.contains("flash-warning") ? "warning" : "success";
        toast(text.replace("\xD7", "").trim(), level);
      }
      flash.remove();
    });
  }

  // src/core/format.ts
  function displayValue(value, type, selection) {
    if (value === null || value === void 0 || value === "") return "";
    if (typeof value === "object") {
      if (Array.isArray(value)) {
        return value.map(
          (item) => typeof item === "object" && item !== null ? String(item.name ?? item.id ?? "") : String(item)
        ).filter(Boolean).join(", ");
      }
      const named = value;
      return String(named.name ?? named.id ?? "");
    }
    if (type === "boolean") return value ? "Yes" : "No";
    if (type === "monetary" || type === "float") {
      const number = Number(value);
      return Number.isFinite(number) ? number.toLocaleString(void 0, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
      }) : String(value);
    }
    if (type === "integer") {
      const number = Number(value);
      return Number.isFinite(number) ? number.toLocaleString() : String(value);
    }
    if (type === "selection" && selection) {
      const match = selection.find(([key]) => key === String(value));
      if (match) return match[1];
    }
    if (type === "datetime") return String(value).replace("T", " ").slice(0, 16);
    if (type === "date") return String(value).slice(0, 10);
    return String(value);
  }
  function rawValue(value) {
    if (value === null || value === void 0) return "";
    if (typeof value === "object") {
      const named = value;
      return named.id === void 0 ? "" : String(named.id);
    }
    return String(value);
  }

  // src/views/shared.ts
  function breadcrumbs(items) {
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
  function listHref(baseUrl, params) {
    return `${baseUrl}${routeQuery(params)}`;
  }
  function readOnlyNote(canCreate, canWrite) {
    if (canWrite) return null;
    const message = canCreate ? "You can create records here but not edit existing ones." : "Read-only access. You can view these records but not change them.";
    return h("p", { class: "permission-note", role: "status" }, message);
  }

  // src/views/form.ts
  function meta2(name) {
    return document.querySelector(`meta[name="${name}"]`)?.content ?? "";
  }
  function renderForm(payload, onSaved) {
    const fragment = document.createDocumentFragment();
    const suffix = payload.menu_id ? `?menu=${payload.menu_id}` : "";
    fragment.appendChild(breadcrumbs(payload.breadcrumbs));
    fragment.appendChild(
      h(
        "header",
        { class: "page-head" },
        h(
          "div",
          {},
          h("h1", { text: payload.title_text }),
          payload.record_id ? h("p", { class: "muted" }, `#${payload.record_id}`) : h("p", { class: "muted" }, "New record")
        )
      )
    );
    const note = readOnlyNote(payload.can_create, payload.can_write);
    if (note) fragment.appendChild(note);
    if (payload.record_id !== null && payload.smart_buttons.length) {
      fragment.appendChild(smartButtons(payload));
    }
    const canSave = payload.record_id === null ? payload.can_create : payload.can_write;
    const form = h("form", {
      method: "post",
      class: "record-form",
      action: payload.record_url,
      novalidate: true
    });
    form.appendChild(
      h("input", { type: "hidden", name: "csrf_token", value: meta2("kberp-csrf") })
    );
    if (payload.menu_id) {
      form.appendChild(
        h("input", { type: "hidden", name: "menu", value: String(payload.menu_id) })
      );
    }
    if (payload.spec.reports.length && payload.record_id !== null) {
      const bar = h("div", {
        class: "form-header-actions",
        role: "group",
        "aria-label": "Reports"
      });
      for (const report of payload.spec.reports) {
        bar.appendChild(
          h(
            "a",
            {
              class: "btn",
              href: `${payload.record_url}/report/${report.name}`,
              target: "_blank",
              rel: "noopener"
            },
            report.label
          )
        );
      }
      form.appendChild(bar);
    }
    if (payload.spec.buttons.length && payload.record_id !== null) {
      const bar = h("div", {
        class: "form-header-actions",
        role: "group",
        "aria-label": "Actions"
      });
      for (const button of payload.spec.buttons) {
        if (button.visible === false) continue;
        const control = h(
          "button",
          {
            class: `btn ${button.name === "action_confirm" ? "btn-primary" : ""}`,
            type: "button"
          },
          button.label
        );
        control.addEventListener("click", () => {
          void (async () => {
            try {
              control.disabled = true;
              const result = await rpc("object.action", {
                app: payload.app_key,
                action_id: payload.action.id,
                id: payload.record_id,
                menu: payload.menu_id,
                name: button.name
              });
              toast(result.message ?? "Action completed.", "success");
              onSaved(result, `${result.record_url}${suffix}`);
            } catch (error) {
              toast(
                error instanceof RpcError ? error.message : "The action could not be completed.",
                "danger"
              );
              control.disabled = false;
            }
          })();
        });
        bar.appendChild(control);
      }
      form.appendChild(bar);
    }
    for (const group of payload.spec.groups) {
      form.appendChild(groupSection(group, payload.record));
    }
    if (payload.spec.pages.length) {
      form.appendChild(formTabs(payload));
    }
    const saveButton = h(
      "button",
      { class: "btn btn-primary", type: "submit", disabled: !canSave },
      "Save"
    );
    form.appendChild(
      h(
        "div",
        { class: "form-actions" },
        saveButton,
        h("a", { class: "btn", href: `${payload.base_url}${suffix}` }, "Discard")
      )
    );
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!canSave || saveButton.disabled) return;
      saveButton.disabled = true;
      saveButton.textContent = "Saving\u2026";
      try {
        const saved = await rpc("view.save", {
          app: payload.app_key,
          action_id: payload.action.id,
          id: payload.record_id,
          values: collect(form),
          menu: payload.menu_id
        });
        toast(saved.message ?? "Record saved.", "success");
        const url = `${saved.record_url}${suffix}`;
        onSaved(saved, url);
      } catch (error) {
        const message = error instanceof RpcError ? error.message : "The record could not be saved.";
        toast(message, "danger");
        focusFirstInvalid(form);
        saveButton.disabled = false;
        saveButton.textContent = "Save";
      }
    });
    const scanButton = form.querySelector("[data-barcode-scan]");
    if (scanButton && payload.record_id !== null) {
      scanButton.addEventListener("click", () => {
        void (async () => {
          const input = form.querySelector("[data-barcode-input]");
          if (!input?.value.trim()) return;
          try {
            await rpc("inventory.scan", {
              picking_id: payload.record_id,
              code: input.value.trim()
            });
            const fresh = await rpc("view.form", {
              app: payload.app_key,
              action_id: payload.action.id,
              id: payload.record_id,
              menu: payload.menu_id
            });
            toast("Line added from barcode.", "success");
            onSaved(fresh, `${fresh.record_url}${suffix}`);
          } catch (error) {
            toast(
              error instanceof RpcError ? error.message : "Barcode not recognised.",
              "danger"
            );
          }
        })();
      });
    }
    fragment.appendChild(form);
    if (payload.record_id !== null) {
      fragment.appendChild(chatter(payload));
      if (payload.can_unlink) {
        fragment.appendChild(deleteForm(payload));
      }
    }
    return fragment;
  }
  function widget(field, value) {
    if (field.readonly) {
      return h(
        "span",
        { class: "readonly-value" },
        displayValue(
          value,
          field.type,
          field.options.map((option) => [String(option.value), option.label])
        )
      );
    }
    if (field.widget === "barcode") {
      return h(
        "div",
        { class: "barcode-scan" },
        h("input", {
          class: "input",
          type: "text",
          "data-barcode-input": "",
          placeholder: "Scan or type a barcode",
          "aria-label": "Scan barcode"
        }),
        h("button", { class: "btn btn-sm", type: "button", "data-barcode-scan": "" }, "Add line")
      );
    }
    if (field.widget === "status") {
      const bar = h("div", { class: "status-bar", role: "status", "aria-label": field.label });
      for (const option of field.options) {
        bar.appendChild(
          h(
            "span",
            {
              class: `status-pill${String(option.value) === String(value) ? " status-active" : ""}`
            },
            option.label
          )
        );
      }
      return bar;
    }
    if (field.type === "one2many") return linesWidget(field);
    const required = field.required;
    if (field.widget === "radio") {
      const group = h("div", {
        class: "radio-group",
        role: "radiogroup",
        "aria-label": field.label
      });
      const choice = (label, option, checked) => h(
        "label",
        { class: "radio" },
        h("input", {
          type: "radio",
          name: field.name,
          value: option,
          checked
        }),
        h("span", {}, label)
      );
      group.appendChild(choice("Company", "1", Boolean(value)));
      group.appendChild(choice("Person", "0", !value));
      return group;
    }
    switch (field.type) {
      case "boolean":
        return h(
          "label",
          { class: "checkbox" },
          h("input", {
            type: "checkbox",
            name: field.name,
            id: `f-${field.name}`,
            checked: Boolean(value)
          }),
          h("span", {}, field.label)
        );
      case "selection":
      case "many2one": {
        const select = h("select", {
          class: "input",
          name: field.name,
          id: `f-${field.name}`,
          required
        });
        select.appendChild(h("option", { value: "" }, "\u2014"));
        const selected = rawValue(value);
        for (const option of field.options) {
          select.appendChild(
            h(
              "option",
              { value: String(option.value), selected: String(option.value) === selected },
              option.label
            )
          );
        }
        return select;
      }
      case "many2many": {
        const select = h("select", {
          class: "input",
          name: field.name,
          id: `f-${field.name}`,
          multiple: true,
          size: 6
        });
        const selected = new Set(
          Array.isArray(value) ? value.map((item) => rawValue(item)) : []
        );
        for (const option of field.options) {
          select.appendChild(
            h(
              "option",
              {
                value: String(option.value),
                selected: selected.has(String(option.value))
              },
              option.label
            )
          );
        }
        return select;
      }
      case "text":
        return h("textarea", {
          class: "input input-textarea",
          name: field.name,
          id: `f-${field.name}`,
          rows: Number(field.rows) || 3,
          required,
          value: rawValue(value)
        });
      case "monetary":
      case "float":
      case "integer":
        return h("input", {
          class: "input input-number",
          type: "number",
          step: field.type === "integer" ? "1" : "0.01",
          name: field.name,
          id: `f-${field.name}`,
          value: rawValue(value),
          required
        });
      case "date":
        return h("input", {
          class: "input",
          type: "date",
          name: field.name,
          id: `f-${field.name}`,
          value: rawValue(value).slice(0, 10),
          required
        });
      default:
        return h("input", {
          class: "input",
          type: "text",
          name: field.name,
          id: `f-${field.name}`,
          value: rawValue(value),
          required
        });
    }
  }
  function linesWidget(field) {
    const wrap = h("div", { class: "line-editor", "data-field": field.name });
    const table = h("table", { class: "data-table line-table" });
    const head = h("thead");
    const headRow = h("tr");
    for (const sub of field.subfields ?? []) {
      headRow.appendChild(h("th", { scope: "col" }, sub.label));
    }
    headRow.appendChild(h("th", { scope: "col", class: "line-remove-col" }));
    head.appendChild(headRow);
    table.appendChild(head);
    const body = h("tbody");
    for (const line of field.lines ?? []) {
      body.appendChild(lineRow(field, line, String(line.id)));
    }
    let nextLine = 0;
    body.appendChild(lineRow(field, {}, `new-${nextLine}`));
    table.appendChild(body);
    wrap.appendChild(h("div", { class: "table-wrap" }, table));
    if (field.editable) {
      const add = h("button", { class: "btn btn-sm add-line-btn", type: "button" }, "Add line");
      add.addEventListener("click", () => {
        nextLine += 1;
        body.appendChild(lineRow(field, {}, `new-${nextLine}`));
        const last = body.lastElementChild;
        last?.querySelector("input, select")?.focus();
      });
      wrap.appendChild(add);
    }
    wrap.appendChild(
      h(
        "p",
        { class: "muted line-hint" },
        "Quantities and prices recalculate the totals when you save."
      )
    );
    return wrap;
  }
  function lineRow(field, line, key) {
    const isNew = key.startsWith("new-");
    const row = h("tr", isNew ? { class: "line-new" } : {});
    for (const sub of field.subfields ?? []) {
      const name = `${field.name}[${key}][${sub.name}]`;
      row.appendChild(h("td", {}, lineInput(sub, line[sub.name], name)));
    }
    if (isNew) {
      row.appendChild(h("td", { class: "line-remove-col" }));
    } else {
      row.appendChild(
        h(
          "td",
          { class: "line-remove-col" },
          h(
            "label",
            { class: "line-remove", title: "Remove this line" },
            h("input", { type: "checkbox", name: `${field.name}[${key}][_delete]` }),
            h("span", { "aria-hidden": "true" }, "\xD7"),
            h("span", { class: "visually-hidden" }, "Remove line")
          )
        )
      );
    }
    return row;
  }
  function lineInput(sub, value, name) {
    if (sub.readonly) {
      return h("span", { class: "readonly-value" }, rawValue(value));
    }
    if (sub.type === "many2many") {
      const select = h("select", {
        class: "input input-sm",
        name,
        multiple: true,
        size: 3
      });
      const selected = new Set(
        Array.isArray(value) ? value.map((item) => String(rawValue(item))) : []
      );
      for (const option of sub.options) {
        select.appendChild(
          h(
            "option",
            { value: String(option.value), selected: selected.has(String(option.value)) },
            option.label
          )
        );
      }
      return select;
    }
    if (sub.type === "many2one" || sub.type === "selection") {
      const select = h("select", { class: "input input-sm", name });
      select.appendChild(h("option", { value: "" }, "\u2014"));
      for (const option of sub.options) {
        select.appendChild(
          h(
            "option",
            {
              value: String(option.value),
              selected: String(option.value) === rawValue(value)
            },
            option.label
          )
        );
      }
      return select;
    }
    if (["monetary", "float", "integer"].includes(sub.type)) {
      return h("input", {
        class: "input input-sm input-number",
        type: "number",
        step: sub.type === "integer" ? "1" : "0.01",
        name,
        value: rawValue(value)
      });
    }
    return h("input", { class: "input input-sm", type: "text", name, value: rawValue(value) });
  }
  function groupSection(group, record) {
    const section = h("section", { class: "panel form-group" });
    if (group.title) section.appendChild(h("h2", { class: "section-title" }, group.title));
    const grid = h("div", { class: "form-grid" });
    for (const field of group.fields) {
      const value = record[field.name] ?? field.value;
      const wrapper = h("div", {
        class: `field${field.type === "text" || field.type === "one2many" || field.widget === "status" ? " field-wide" : ""}`
      });
      if (field.widget === "radio") {
        wrapper.appendChild(h("span", { class: "field-label" }, field.label));
      } else if (field.type !== "boolean" && field.widget !== "status") {
        wrapper.appendChild(
          h(
            "label",
            { class: "field-label", for: `f-${field.name}` },
            field.label,
            field.required ? h("span", { class: "required" }, " *") : null
          )
        );
      }
      wrapper.appendChild(widget(field, value));
      grid.appendChild(wrapper);
    }
    section.appendChild(grid);
    return section;
  }
  function formTabs(payload) {
    const tabs = h("div", { class: "form-tabs" });
    payload.spec.pages.forEach((page, index) => {
      const tabId = `form-tab-${index + 1}`;
      tabs.appendChild(
        h("input", {
          class: "tab-input",
          type: "radio",
          name: "form-tab",
          id: tabId,
          checked: index === 0
        })
      );
      tabs.appendChild(h("label", { class: "tab-label", for: tabId }, page.title));
    });
    const panels = h("div", { class: "tab-panels" });
    payload.spec.pages.forEach((page, index) => {
      const panel = h("div", { class: "tab-panel", "data-tab": String(index + 1) });
      for (const group of page.groups) {
        panel.appendChild(groupSection(group, payload.record));
      }
      panels.appendChild(panel);
    });
    tabs.appendChild(panels);
    return tabs;
  }
  function smartButtons(payload) {
    const row = h("div", { class: "smart-buttons", role: "list" });
    for (const button of payload.smart_buttons) {
      row.appendChild(
        h(
          "div",
          { class: "smart-button", role: "listitem" },
          h("strong", {}, String(button.count)),
          h("span", {}, button.label)
        )
      );
    }
    return row;
  }
  function inputValue(element) {
    if (element instanceof HTMLInputElement && element.type === "checkbox") {
      return element.checked;
    }
    if (element instanceof HTMLInputElement && element.type === "radio") {
      return element.checked ? element.value === "1" : void 0;
    }
    if (element instanceof HTMLSelectElement && element.multiple) {
      return Array.from(element.selectedOptions).map((option) => option.value).filter(Boolean);
    }
    return element.value;
  }
  function collect(form) {
    const values = {};
    const lines = {};
    const deleted = /* @__PURE__ */ new Set();
    form.querySelectorAll("[name]").forEach((element) => {
      if (!element.name || element.name === "csrf_token") return;
      const nested = /^(.+)\[([^[\]]+)\]\[([^[\]]+)\]$/.exec(element.name);
      if (!nested) {
        const value2 = inputValue(element);
        if (value2 !== void 0) values[element.name] = value2;
        return;
      }
      const [, field, key, subfield] = nested;
      if (!field || !key || !subfield) return;
      if (subfield === "_delete") {
        if (element instanceof HTMLInputElement && element.checked) {
          deleted.add(`${field}::${key}`);
        }
        return;
      }
      const value = inputValue(element);
      if (value === void 0) return;
      const rows = lines[field] ?? (lines[field] = {});
      const row = rows[key] ?? (rows[key] = {});
      row[subfield] = value;
    });
    for (const [field, rows] of Object.entries(lines)) {
      values[field] = Object.entries(rows).filter(([key]) => !deleted.has(`${field}::${key}`)).map(([key, row]) => ({
        .../^\d+$/.test(key) ? { id: Number(key) } : {},
        ...row
      }));
    }
    return values;
  }
  function focusFirstInvalid(form) {
    const first = form.querySelector("[required]");
    if (first && !first.value) first.focus();
  }
  function chatter(payload) {
    const section = h("section", { class: "panel chatter" });
    const heading = h("div", { class: "chatter-head-row" });
    heading.appendChild(h("h2", { class: "section-title" }, "Chatter"));
    heading.appendChild(
      postForm(payload, "follow", [], h("button", { class: "btn btn-sm", type: "submit" }, "Follow"))
    );
    section.appendChild(heading);
    if (payload.followers.length) {
      const followers = h("div", { class: "followers", "aria-label": "Followers" });
      followers.appendChild(h("span", { class: "muted" }, "Followers"));
      for (const follower of payload.followers) {
        const name = follower.partner_id?.name ?? "Unknown";
        followers.appendChild(
          h(
            "span",
            { class: "follower-chip" },
            h("span", { class: "follower-avatar", "aria-hidden": "true" }, name.slice(0, 1).toUpperCase()),
            name
          )
        );
      }
      section.appendChild(followers);
    }
    section.appendChild(activityBlock(payload));
    const noteForm = postForm(
      payload,
      "note",
      [
        h("textarea", {
          class: "input input-textarea",
          id: "chatter-body",
          name: "body",
          rows: 3,
          placeholder: "Log a note\u2026",
          "aria-label": "Add a note"
        })
      ],
      h("button", { class: "btn", type: "submit" }, "Add note")
    );
    noteForm.classList.add("note-form");
    section.appendChild(noteForm);
    if (!payload.messages.length) {
      section.appendChild(h("p", { class: "muted" }, "No messages yet."));
      return section;
    }
    const list = h("ul", { class: "chatter-list" });
    for (const message of payload.messages) {
      const author = message.author_id?.name ?? "System";
      const created = message.create_date ? String(message.create_date).replace("T", " ").slice(0, 16) : "";
      list.appendChild(
        h(
          "li",
          { class: "chatter-message" },
          h(
            "div",
            { class: "chatter-head" },
            h("span", { class: "avatar" }, author.slice(0, 1).toUpperCase()),
            h("strong", {}, author),
            h("span", { class: "muted" }, created)
          ),
          h("p", { class: "chatter-body" }, message.body)
        )
      );
    }
    section.appendChild(list);
    return section;
  }
  function activityBlock(payload) {
    const block = h("div", { class: "activity-block" });
    block.appendChild(h("h3", { class: "subsection-title" }, "Next activities"));
    if (payload.activities.length) {
      const list = h("ul", { class: "activity-list" });
      for (const activity of payload.activities) {
        const row = h("li", { class: "activity" });
        row.appendChild(
          h(
            "div",
            {},
            h("strong", {}, activity.activity_type_id?.name ?? "Activity"),
            h("span", {}, activity.summary ?? ""),
            h(
              "span",
              { class: "muted" },
              activity.date_deadline ? `due ${String(activity.date_deadline).slice(0, 10)}` : "no date"
            )
          )
        );
        row.appendChild(
          postForm(
            payload,
            `activity/${activity.id}/done`,
            [],
            h("button", { class: "btn btn-sm", type: "submit" }, "Done")
          )
        );
        list.appendChild(row);
      }
      block.appendChild(list);
    } else {
      block.appendChild(h("p", { class: "muted" }, "Nothing scheduled."));
    }
    if (!payload.activity_types.length) return block;
    const details = h("details", { class: "activity-form" });
    details.appendChild(h("summary", {}, "Schedule an activity"));
    const typeSelect = h("select", { class: "input", name: "activity_type_id", required: true });
    for (const type of payload.activity_types) {
      typeSelect.appendChild(h("option", { value: String(type.id) }, type.name));
    }
    details.appendChild(
      postForm(
        payload,
        "activity",
        [
          labelField("Activity", typeSelect),
          labelField(
            "Summary",
            h("input", { class: "input", type: "text", name: "summary" })
          ),
          labelField(
            "Due date",
            h("input", { class: "input", type: "date", name: "date_deadline" })
          ),
          labelField(
            "Note",
            h("input", { class: "input", type: "text", name: "note" })
          )
        ],
        h("button", { class: "btn btn-sm", type: "submit" }, "Schedule")
      )
    );
    block.appendChild(details);
    return block;
  }
  function labelField(label, input) {
    return h(
      "div",
      { class: "field" },
      h("label", { class: "field-label" }, label),
      input
    );
  }
  function postForm(payload, suffix, children, button, extraClass = "") {
    const form = h("form", {
      method: "post",
      action: `${payload.base_url}/${payload.record_id}/${suffix}`,
      class: extraClass
    });
    form.appendChild(
      h("input", { type: "hidden", name: "csrf_token", value: meta2("kberp-csrf") })
    );
    if (payload.menu_id) {
      form.appendChild(
        h("input", { type: "hidden", name: "menu", value: String(payload.menu_id) })
      );
    }
    for (const child of children) form.appendChild(child);
    form.appendChild(button);
    return form;
  }
  function deleteForm(payload) {
    const button = h(
      "button",
      { class: "btn btn-danger", type: "submit" },
      "Delete"
    );
    const form = h(
      "form",
      {
        method: "post",
        class: "danger-zone",
        action: `${payload.base_url}/${payload.record_id}/delete`
      },
      h("input", { type: "hidden", name: "csrf_token", value: meta2("kberp-csrf") }),
      button
    );
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!window.confirm("Delete this record permanently?")) return;
      button.disabled = true;
      button.textContent = "Deleting\u2026";
      try {
        const result = await rpc("view.unlink", {
          app: payload.app_key,
          action_id: payload.action.id,
          id: payload.record_id
        });
        toast(result.message, "success");
        navigate(result.redirect);
      } catch (error) {
        toast(
          error instanceof RpcError ? error.message : "The record could not be deleted.",
          "danger"
        );
        button.disabled = false;
        button.textContent = "Delete";
      }
    });
    return form;
  }

  // src/views/list.ts
  function renderList(payload) {
    const fragment = document.createDocumentFragment();
    fragment.appendChild(breadcrumbs(payload.breadcrumbs));
    const actions = h("div", { class: "page-actions" });
    const note = readOnlyNote(payload.can_create, payload.can_write);
    if (payload.kanban) actions.appendChild(viewToggle(payload));
    if (payload.can_create) {
      const suffix = payload.menu_id ? `?menu=${payload.menu_id}` : "";
      actions.appendChild(
        h(
          "a",
          { class: "btn btn-primary", href: `${payload.base_url}/new${suffix}` },
          h("span", { "aria-hidden": "true", class: "btn-plus" }, "+"),
          " New"
        )
      );
    }
    fragment.appendChild(
      h(
        "header",
        { class: "page-head" },
        h(
          "div",
          {},
          h("h1", { text: payload.spec.string }),
          h(
            "p",
            { class: "muted" },
            `${payload.total} record${payload.total === 1 ? "" : "s"}`
          )
        ),
        actions
      )
    );
    if (note) fragment.appendChild(note);
    fragment.appendChild(searchBar(payload));
    if (payload.groups.length === 0 && payload.records.length === 0) {
      fragment.appendChild(
        h(
          "div",
          { class: "empty-state panel" },
          h("h2", { text: "Nothing here yet" }),
          h(
            "p",
            { class: "muted" },
            payload.q || payload.selected_filter ? "No records match this search." : "Create the first record to get started."
          )
        )
      );
      return fragment;
    }
    if (payload.groups.length) {
      for (const group of payload.groups) {
        fragment.appendChild(
          h(
            "section",
            { class: "record-group" },
            h(
              "h2",
              { class: "group-head" },
              h("span", {}, group.label),
              h("span", { class: "group-count" }, String(group.count))
            ),
            payload.view === "kanban" && payload.kanban ? kanbanCards(payload, group.records) : recordsTable(payload, group.records)
          )
        );
      }
    } else {
      fragment.appendChild(
        payload.view === "kanban" && payload.kanban ? kanbanCards(payload, payload.records) : recordsTable(payload, payload.records)
      );
    }
    const pager = pagerFor(payload);
    if (pager) fragment.appendChild(pager);
    return fragment;
  }
  function searchBar(payload) {
    const input = h("input", {
      class: "input",
      type: "search",
      name: "q",
      value: payload.q,
      placeholder: `Search ${payload.spec.string.toLowerCase()}\u2026`,
      "aria-label": "Search"
    });
    const form = h(
      "form",
      { class: "searchbar", method: "get", action: payload.base_url, role: "search" },
      h("label", { class: "search-input" }, h("span", { class: "search-mark" }, "\u2315"), input),
      h("button", { class: "btn", type: "submit" }, "Search")
    );
    if (payload.menu_id) {
      form.appendChild(
        h("input", { type: "hidden", name: "menu", value: String(payload.menu_id) })
      );
    }
    if (payload.selected_filter) {
      form.appendChild(
        h("input", {
          type: "hidden",
          name: "filter",
          value: payload.selected_filter
        })
      );
    }
    if (payload.view === "kanban") {
      form.appendChild(h("input", { type: "hidden", name: "view", value: "kanban" }));
    }
    if (payload.selected_group) {
      form.appendChild(
        h("input", { type: "hidden", name: "group_by", value: payload.selected_group })
      );
    }
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      navigate(
        listHref(payload.base_url, {
          q: input.value.trim(),
          filter: payload.selected_filter,
          menu: payload.menu_id,
          view: payload.view === "kanban" ? "kanban" : null,
          group_by: payload.selected_group
        })
      );
    });
    if (payload.search.filters.length) {
      const chips = h("div", { class: "filter-chips" });
      for (const filter of payload.search.filters) {
        chips.appendChild(
          h(
            "a",
            {
              class: `chip ${filter.name === payload.selected_filter ? "chip-active" : ""}`,
              href: listHref(payload.base_url, {
                q: payload.q,
                filter: filter.name,
                menu: payload.menu_id,
                view: payload.view === "kanban" ? "kanban" : null,
                group_by: payload.selected_group
              })
            },
            filter.label
          )
        );
      }
      if (payload.q || payload.selected_filter) {
        chips.appendChild(
          h(
            "a",
            {
              class: "chip chip-clear",
              href: listHref(payload.base_url, {
                menu: payload.menu_id,
                view: payload.view === "kanban" ? "kanban" : null,
                group_by: payload.selected_group
              })
            },
            "Clear"
          )
        );
      }
      form.appendChild(chips);
    }
    if (payload.search.group_bys.length) {
      const chips = h("div", { class: "groupby-chips" });
      chips.appendChild(h("span", { class: "muted" }, "Group by"));
      for (const group of payload.search.group_bys) {
        chips.appendChild(
          h(
            "a",
            {
              class: `chip ${group.name === payload.selected_group ? "chip-active" : ""}`,
              href: listHref(payload.base_url, {
                q: payload.q,
                filter: payload.selected_filter,
                menu: payload.menu_id,
                view: payload.view === "kanban" ? "kanban" : null,
                group_by: group.name === payload.selected_group ? null : group.name
              })
            },
            group.label
          )
        );
      }
      form.appendChild(chips);
    }
    return form;
  }
  function viewToggle(payload) {
    const group = h("div", {
      class: "view-toggle",
      role: "group",
      "aria-label": "View"
    });
    const link = (view, label) => h(
      "a",
      {
        class: `btn btn-sm ${payload.view === view ? "btn-primary" : ""}`,
        href: listHref(payload.base_url, {
          q: payload.q,
          filter: payload.selected_filter,
          menu: payload.menu_id,
          view: view === "kanban" ? "kanban" : null,
          group_by: payload.selected_group
        })
      },
      label
    );
    group.appendChild(link("list", "List"));
    group.appendChild(link("kanban", "Kanban"));
    return group;
  }
  function kanbanCards(payload, records) {
    const grid = h("div", { class: "kanban-grid" });
    const spec = payload.kanban;
    if (!spec) return grid;
    for (const record of records) {
      const suffix = payload.menu_id ? `?menu=${payload.menu_id}` : "";
      const card = h("a", {
        class: "kanban-card",
        href: `${payload.base_url}/${record.id}${suffix}`
      });
      const name = String(record["name"] ?? "?");
      card.appendChild(
        h(
          "span",
          { class: "kanban-avatar", "aria-hidden": "true" },
          (name.slice(0, 1) || "?").toUpperCase()
        )
      );
      for (const field of spec.fields) {
        const value = record[field.name];
        if (field.name === "name") {
          card.appendChild(h("h3", { class: "kanban-name" }, name || "(no name)"));
        } else if (field.name === "parent_id" && value) {
          const parent = value;
          if (parent.name) {
            card.appendChild(h("span", { class: "kanban-parent" }, parent.name));
          }
        } else if (field.name === "tag_ids" && Array.isArray(value)) {
          const tags = h("span", { class: "kanban-tags" });
          for (const item of value) {
            const tag = item;
            if (tag.name) tags.appendChild(h("span", { class: "kanban-tag" }, tag.name));
          }
          if (tags.childElementCount) card.appendChild(tags);
        } else {
          const text = displayValue(value, field.type);
          if (text) card.appendChild(h("span", { class: "kanban-line" }, text));
        }
      }
      const stats = record["statistics"];
      const addresses = Number(stats?.addresses ?? 0);
      const banks = Number(stats?.bank_accounts ?? 0);
      if (addresses || banks) {
        const footer = h("span", { class: "kanban-stats" });
        if (addresses) {
          footer.appendChild(
            h("span", {}, `${addresses} address${addresses === 1 ? "" : "es"}`)
          );
        }
        if (addresses && banks) {
          footer.appendChild(h("span", { "aria-hidden": "true" }, "\xB7"));
        }
        if (banks) footer.appendChild(h("span", {}, `${banks} bank`));
        card.appendChild(footer);
      }
      grid.appendChild(card);
    }
    return grid;
  }
  function recordsTable(payload, records) {
    const head = h("tr");
    for (const column of payload.spec.columns) {
      head.appendChild(h("th", { scope: "col" }, column.label));
    }
    const body = h("tbody");
    for (const record of records) {
      const row = h("tr");
      payload.spec.columns.forEach((column, index) => {
        const cell = h("td", {
          class: `col-${column.type}${index === 0 ? " col-primary" : ""}`
        });
        if (column.type === "statistics") {
          cell.appendChild(statistics(record[column.name]));
        } else {
          const text = displayValue(record[column.name], column.type, column.selection) || (index === 0 ? "(no name)" : "");
          if (index === 0) {
            const suffix = payload.menu_id ? `?menu=${payload.menu_id}` : "";
            cell.appendChild(
              h("a", { href: `${payload.base_url}/${record.id}${suffix}` }, text)
            );
          } else {
            cell.textContent = text;
          }
        }
        row.appendChild(cell);
      });
      body.appendChild(row);
    }
    return h(
      "div",
      { class: "table-wrap" },
      h("table", { class: "data-table" }, h("thead", {}, head), body)
    );
  }
  function statistics(value) {
    const stats = value ?? {};
    const addresses = Number(stats.addresses ?? 0);
    const banks = Number(stats.bank_accounts ?? 0);
    if (!addresses && !banks) {
      return h("span", { class: "muted" }, "\u2014");
    }
    const wrap = h("span", { class: "stat-badges" });
    if (addresses) {
      wrap.appendChild(
        h("span", { class: "stat-badge" }, `${addresses} address${addresses === 1 ? "" : "es"}`)
      );
    }
    if (banks) {
      wrap.appendChild(h("span", { class: "stat-badge" }, `${banks} bank`));
    }
    return wrap;
  }
  function pagerFor(payload) {
    if (payload.groups.length || payload.total <= payload.limit) return null;
    const pager = h("nav", { class: "pager", "aria-label": "Pagination" });
    const params = (offset) => listHref(payload.base_url, {
      offset,
      q: payload.q,
      filter: payload.selected_filter,
      menu: payload.menu_id,
      view: payload.view === "kanban" ? "kanban" : null,
      group_by: payload.selected_group
    });
    pager.appendChild(
      payload.offset > 0 ? h("a", { class: "btn btn-sm", href: params(payload.prev_offset) }, "Previous") : h("span", { class: "btn btn-sm btn-disabled" }, "Previous")
    );
    pager.appendChild(
      h(
        "span",
        { class: "pager-info" },
        `${payload.offset + 1}\u2013${Math.min(payload.offset + payload.limit, payload.total)} of ${payload.total}`
      )
    );
    pager.appendChild(
      payload.next_offset !== null ? h("a", { class: "btn btn-sm", href: params(payload.next_offset) }, "Next") : h("span", { class: "btn btn-sm btn-disabled" }, "Next")
    );
    return pager;
  }

  // src/index.ts
  function meta3(name) {
    return document.querySelector(`meta[name="${name}"]`)?.content ?? "";
  }
  function boot() {
    const main = document.querySelector("main");
    const userId = Number(meta3("kberp-user") || 0);
    if (!main || !userId) return;
    const host = main;
    registry.add("views", "list", renderList);
    registry.add("views", "form", renderForm);
    takeServerFlash();
    const bus = startBus(userId);
    let renderToken = 0;
    const mount = (fragment, animate = true) => {
      clear(host);
      host.appendChild(fragment);
      if (animate) {
        host.classList.add("kwl-enter");
        requestAnimationFrame(() => host.classList.remove("kwl-enter"));
      }
    };
    const mountForm = (payload, url) => {
      syncUrl(url, true);
      const view = registry.get("views", "form");
      if (view) mount(view(payload, mountForm));
    };
    effect(() => {
      const current = route.value;
      if (!current) return;
      void showRoute(current);
    });
    async function showRoute(current) {
      const token = ++renderToken;
      setLoading(true);
      host.classList.add("is-loading");
      try {
        if (current.record === null) {
          const payload = await rpc("view.load", {
            app: current.app,
            action_id: current.actionId,
            q: current.search.get("q") ?? "",
            filter: current.search.get("filter") ?? "",
            offset: Number(current.search.get("offset") ?? 0),
            menu: current.menu,
            view: current.search.get("view") ?? "",
            group_by: current.search.get("group_by") ?? ""
          });
          if (token !== renderToken) return;
          const view = registry.get("views", "list");
          if (view) mount(view(payload));
        } else {
          const payload = await rpc("view.form", {
            app: current.app,
            action_id: current.actionId,
            id: current.record === "new" ? null : current.record,
            menu: current.menu
          });
          if (token !== renderToken) return;
          const view = registry.get("views", "form");
          if (view) mount(view(payload, mountForm));
        }
      } catch (error) {
        if (token !== renderToken) return;
        toast(
          error instanceof RpcError ? error.message : "This screen could not be loaded.",
          "danger"
        );
      } finally {
        if (token === renderToken) {
          host.classList.remove("is-loading");
          setLoading(false);
        }
      }
    }
    startRouter();
    window.addEventListener("beforeunload", () => bus.close());
  }
  function startBus(userId) {
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
      title: busStatusLabel("connecting")
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
})();
