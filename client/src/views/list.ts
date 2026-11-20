import { h } from "../core/dom";
import { displayValue } from "../core/format";
import { navigate } from "../core/router";
import type { ListPayload, RecordValues } from "../types";
import { breadcrumbs, listHref, readOnlyNote } from "./shared";

type Row = RecordValues & { id: number };

export function renderList(payload: ListPayload): DocumentFragment {
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
        " New",
      ),
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
          `${payload.total} record${payload.total === 1 ? "" : "s"}`,
        ),
      ),
      actions,
    ),
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
          payload.q || payload.selected_filter
            ? "No records match this search."
            : "Create the first record to get started.",
        ),
      ),
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
            h("span", { class: "group-count" }, String(group.count)),
          ),
          payload.view === "kanban" && payload.kanban
            ? kanbanCards(payload, group.records)
            : recordsTable(payload, group.records),
        ),
      );
    }
  } else {
    fragment.appendChild(
      payload.view === "kanban" && payload.kanban
        ? kanbanCards(payload, payload.records)
        : recordsTable(payload, payload.records),
    );
  }

  const pager = pagerFor(payload);
  if (pager) fragment.appendChild(pager);
  return fragment;
}

function searchBar(payload: ListPayload): HTMLElement {
  const input = h("input", {
    class: "input",
    type: "search",
    name: "q",
    value: payload.q,
    placeholder: `Search ${payload.spec.string.toLowerCase()}\u2026`,
    "aria-label": "Search",
  });
  const form = h(
    "form",
    { class: "searchbar", method: "get", action: payload.base_url, role: "search" },
    h("label", { class: "search-input" }, h("span", { class: "search-mark" }, "\u2315"), input),
    h("button", { class: "btn", type: "submit" }, "Search"),
  );
  if (payload.menu_id) {
    form.appendChild(
      h("input", { type: "hidden", name: "menu", value: String(payload.menu_id) }),
    );
  }
  if (payload.selected_filter) {
    form.appendChild(
      h("input", {
        type: "hidden",
        name: "filter",
        value: payload.selected_filter,
      }),
    );
  }
  if (payload.view === "kanban") {
    form.appendChild(h("input", { type: "hidden", name: "view", value: "kanban" }));
  }
  if (payload.selected_group) {
    form.appendChild(
      h("input", { type: "hidden", name: "group_by", value: payload.selected_group }),
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
        group_by: payload.selected_group,
      }),
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
              group_by: payload.selected_group,
            }),
          },
          filter.label,
        ),
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
              group_by: payload.selected_group,
            }),
          },
          "Clear",
        ),
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
              group_by: group.name === payload.selected_group ? null : group.name,
            }),
          },
          group.label,
        ),
      );
    }
    form.appendChild(chips);
  }
  return form;
}

function viewToggle(payload: ListPayload): HTMLElement {
  const group = h("div", {
    class: "view-toggle",
    role: "group",
    "aria-label": "View",
  });
  const link = (view: string, label: string): HTMLElement =>
    h(
      "a",
      {
        class: `btn btn-sm ${payload.view === view ? "btn-primary" : ""}`,
        href: listHref(payload.base_url, {
          q: payload.q,
          filter: payload.selected_filter,
          menu: payload.menu_id,
          view: view === "kanban" ? "kanban" : null,
          group_by: payload.selected_group,
        }),
      },
      label,
    );
  group.appendChild(link("list", "List"));
  group.appendChild(link("kanban", "Kanban"));
  return group;
}

function kanbanCards(payload: ListPayload, records: Row[]): HTMLElement {
  const grid = h("div", { class: "kanban-grid" });
  const spec = payload.kanban;
  if (!spec) return grid;
  for (const record of records) {
    const suffix = payload.menu_id ? `?menu=${payload.menu_id}` : "";
    const card = h("a", {
      class: "kanban-card",
      href: `${payload.base_url}/${record.id}${suffix}`,
    });
    const name = String(record["name"] ?? "?");
    card.appendChild(
      h(
        "span",
        { class: "kanban-avatar", "aria-hidden": "true" },
        (name.slice(0, 1) || "?").toUpperCase(),
      ),
    );
    for (const field of spec.fields) {
      const value = record[field.name];
      if (field.name === "name") {
        card.appendChild(h("h3", { class: "kanban-name" }, name || "(no name)"));
      } else if (field.name === "parent_id" && value) {
        const parent = value as { name?: string };
        if (parent.name) {
          card.appendChild(h("span", { class: "kanban-parent" }, parent.name));
        }
      } else if (field.name === "tag_ids" && Array.isArray(value)) {
        const tags = h("span", { class: "kanban-tags" });
        for (const item of value) {
          const tag = item as { name?: string };
          if (tag.name) tags.appendChild(h("span", { class: "kanban-tag" }, tag.name));
        }
        if (tags.childElementCount) card.appendChild(tags);
      } else {
        const text = displayValue(value, field.type);
        if (text) card.appendChild(h("span", { class: "kanban-line" }, text));
      }
    }
    const stats = record["statistics"] as
      | { addresses?: number; bank_accounts?: number }
      | undefined;
    const addresses = Number(stats?.addresses ?? 0);
    const banks = Number(stats?.bank_accounts ?? 0);
    if (addresses || banks) {
      const footer = h("span", { class: "kanban-stats" });
      if (addresses) {
        footer.appendChild(
          h("span", {}, `${addresses} address${addresses === 1 ? "" : "es"}`),
        );
      }
      if (addresses && banks) {
        footer.appendChild(h("span", { "aria-hidden": "true" }, "\u00b7"));
      }
      if (banks) footer.appendChild(h("span", {}, `${banks} bank`));
      card.appendChild(footer);
    }
    grid.appendChild(card);
  }
  return grid;
}

function recordsTable(payload: ListPayload, records: Row[]): HTMLElement {
  const head = h("tr");
  for (const column of payload.spec.columns) {
    head.appendChild(h("th", { scope: "col" }, column.label));
  }
  const body = h("tbody");
  for (const record of records) {
    const row = h("tr");
    payload.spec.columns.forEach((column, index) => {
      const cell = h("td", {
        class: `col-${column.type}${index === 0 ? " col-primary" : ""}`,
      });
      if (column.type === "statistics") {
        cell.appendChild(statistics(record[column.name]));
      } else {
        const text =
          displayValue(record[column.name], column.type, column.selection) ||
          (index === 0 ? "(no name)" : "");
        if (index === 0) {
          const suffix = payload.menu_id ? `?menu=${payload.menu_id}` : "";
          cell.appendChild(
            h("a", { href: `${payload.base_url}/${record.id}${suffix}` }, text),
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
    h("table", { class: "data-table" }, h("thead", {}, head), body),
  );
}

function statistics(value: unknown): HTMLElement {
  const stats = (value ?? {}) as { addresses?: number; bank_accounts?: number };
  const addresses = Number(stats.addresses ?? 0);
  const banks = Number(stats.bank_accounts ?? 0);
  if (!addresses && !banks) {
    return h("span", { class: "muted" }, "\u2014");
  }
  const wrap = h("span", { class: "stat-badges" });
  if (addresses) {
    wrap.appendChild(
      h("span", { class: "stat-badge" }, `${addresses} address${addresses === 1 ? "" : "es"}`),
    );
  }
  if (banks) {
    wrap.appendChild(h("span", { class: "stat-badge" }, `${banks} bank`));
  }
  return wrap;
}

function pagerFor(payload: ListPayload): HTMLElement | null {
  if (payload.groups.length || payload.total <= payload.limit) return null;
  const pager = h("nav", { class: "pager", "aria-label": "Pagination" });
  const params = (offset: number): string =>
    listHref(payload.base_url, {
      offset,
      q: payload.q,
      filter: payload.selected_filter,
      menu: payload.menu_id,
      view: payload.view === "kanban" ? "kanban" : null,
      group_by: payload.selected_group,
    });

  pager.appendChild(
    payload.offset > 0
      ? h("a", { class: "btn btn-sm", href: params(payload.prev_offset) }, "Previous")
      : h("span", { class: "btn btn-sm btn-disabled" }, "Previous"),
  );
  pager.appendChild(
    h(
      "span",
      { class: "pager-info" },
      `${payload.offset + 1}\u2013${Math.min(payload.offset + payload.limit, payload.total)} of ${payload.total}`,
    ),
  );
  pager.appendChild(
    payload.next_offset !== null
      ? h("a", { class: "btn btn-sm", href: params(payload.next_offset) }, "Next")
      : h("span", { class: "btn btn-sm btn-disabled" }, "Next"),
  );
  return pager;
}
