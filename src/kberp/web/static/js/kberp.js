// KB ERP shell behaviour: app switcher, menus, keyboard, flash dismissal.
(function () {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  // -- Dropdown menus -----------------------------------------------------
  function closeMenus(except) {
    $$(".menu.open").forEach((menu) => {
      if (menu !== except) {
        menu.classList.remove("open");
        const button = $(".menu-btn", menu);
        if (button) button.setAttribute("aria-expanded", "false");
      }
    });
  }

  $$(".menu > .menu-btn").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.stopPropagation();
      const menu = button.parentElement;
      const willOpen = !menu.classList.contains("open");
      closeMenus(menu);
      menu.classList.toggle("open", willOpen);
      button.setAttribute("aria-expanded", String(willOpen));
    });
  });

  document.addEventListener("click", () => closeMenus(null));
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeMenus(null);
      closeSwitcher();
    }
  });

  // -- App switcher -------------------------------------------------------
  const switcher = $("#app-switcher");
  const switcherButton = $("#app-switcher-btn");

  function openSwitcher() {
    if (!switcher) return;
    switcher.hidden = false;
    if (switcherButton) switcherButton.setAttribute("aria-expanded", "true");
    const first = $(".app-card", switcher);
    if (first) first.focus();
  }

  function closeSwitcher() {
    if (!switcher || switcher.hidden) return;
    switcher.hidden = true;
    if (switcherButton) {
      switcherButton.setAttribute("aria-expanded", "false");
      switcherButton.focus();
    }
  }

  if (switcherButton) {
    switcherButton.addEventListener("click", (event) => {
      event.stopPropagation();
      if (switcher && switcher.hidden) openSwitcher();
      else closeSwitcher();
    });
  }
  if (switcher) {
    switcher.addEventListener("click", (event) => {
      if (event.target === switcher) closeSwitcher();
    });
    const closer = $("[data-close-switcher]", switcher);
    if (closer) closer.addEventListener("click", closeSwitcher);
  }

  // -- Keyboard shortcuts (design.md R-UI-08) -----------------------------
  document.addEventListener("keydown", (event) => {
    if (event.altKey && !event.ctrlKey && !event.metaKey) {
      const key = event.key.toLowerCase();
      if (key === "w") {
        event.preventDefault();
        if (switcher && switcher.hidden) openSwitcher();
        else closeSwitcher();
      }
      if (key === "q") {
        event.preventDefault();
        const search = $('input[type="search"]');
        if (search) search.focus();
      }
    }
  });

  // -- Flash messages -----------------------------------------------------
  $$(".flash").forEach((flash) => {
    const close = $(".flash-close", flash);
    if (close) close.addEventListener("click", () => flash.remove());
    window.setTimeout(() => {
      flash.style.opacity = "0";
      flash.style.transition = "opacity 200ms";
      window.setTimeout(() => flash.remove(), 220);
    }, 6000);
  });

  // -- Editable line tables ----------------------------------------------
  // Add a blank row by cloning the existing one, keeping the indexed names
  // unique. The form still works without this script: two blank rows ship in
  // the server-rendered markup.
  document.addEventListener("click", (event) => {
    const button = event.target.closest(".add-line-btn");
    if (!button) return;
    const editor = button.closest(".line-editor");
    const body = editor && $("tbody", editor);
    if (!body) return;
    const template = $(".line-new", body);
    if (!template) return;
    const clone = template.cloneNode(true);
    const indices = $$(".line-new", body)
      .map((row) => {
        const name = $("input, select", row)?.name || "";
        const match = /\[new-(\d+)\]/.exec(name);
        return match ? Number(match[1]) : -1;
      })
      .filter((index) => index >= 0);
    const next = indices.length ? Math.max(...indices) + 1 : 0;
    $$("[name]", clone).forEach((field) => {
      field.name = field.name.replace(/\[new-\d+\]/, `[new-${next}]`);
      if ("value" in field && field.type !== "checkbox") field.value = "";
    });
    body.appendChild(clone);
    const first = $("input, select", clone);
    if (first) first.focus();
  });

  // -- Barcode scan on stock transfers ------------------------------------
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-barcode-scan]");
    if (!button) return;
    const input = button.closest(".field")?.querySelector("[data-barcode-input]");
    const form = button.closest("form");
    const match = (form?.getAttribute("action") || location.pathname).match(
      /\/action\/(\d+)\/(\d+)/,
    );
    if (!input || !input.value.trim() || !match) return;
    const csrf = document.querySelector('meta[name="kberp-csrf"]')?.content || "";
    button.disabled = true;
    try {
      const response = await fetch("/web/rpc", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: Date.now(),
          method: "inventory.scan",
          params: { picking_id: Number(match[2]), code: input.value.trim() },
        }),
      });
      const payload = await response.json();
      if (payload.result?.ok) {
        location.reload();
        return;
      }
      input.setCustomValidity(payload.error?.message || "Barcode not recognised");
      input.reportValidity();
      input.setCustomValidity("");
    } catch (error) {
      input.setCustomValidity("Scan failed");
      input.reportValidity();
      input.setCustomValidity("");
    } finally {
      button.disabled = false;
    }
  });

  // -- Table row affordance ----------------------------------------------
  // Rows stay plain links: no JS navigation, so middle-click and copy work.
})();
