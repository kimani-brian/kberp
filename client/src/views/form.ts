import { h } from "../core/dom";
import { displayValue, rawValue } from "../core/format";
import { rpc, RpcError } from "../core/rpc";
import { navigate } from "../core/router";
import { toast } from "../core/toast";
import type { FormField, FormGroup, FormPayload, RecordValues } from "../types";
import { breadcrumbs, readOnlyNote } from "./shared";

type SaveHandler = (payload: FormPayload, url: string) => void;

function meta(name: string): string {
  return document.querySelector<HTMLMetaElement>(`meta[name="${name}"]`)?.content ?? "";
}

export function renderForm(payload: FormPayload, onSaved: SaveHandler): DocumentFragment {
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
        payload.record_id
          ? h("p", { class: "muted" }, `#${payload.record_id}`)
          : h("p", { class: "muted" }, "New record"),
      ),
    ),
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
    novalidate: true,
  });
  form.appendChild(
    h("input", { type: "hidden", name: "csrf_token", value: meta("kberp-csrf") }),
  );
  if (payload.menu_id) {
    form.appendChild(
      h("input", { type: "hidden", name: "menu", value: String(payload.menu_id) }),
    );
  }

  if (payload.spec.reports.length && payload.record_id !== null) {
    const bar = h("div", {
      class: "form-header-actions",
      role: "group",
      "aria-label": "Reports",
    });
    for (const report of payload.spec.reports) {
      bar.appendChild(
        h(
          "a",
          {
            class: "btn",
            href: `${payload.record_url}/report/${report.name}`,
            target: "_blank",
            rel: "noopener",
          },
          report.label,
        ),
      );
    }
    form.appendChild(bar);
  }

  if (payload.spec.buttons.length && payload.record_id !== null) {
    const bar = h("div", {
      class: "form-header-actions",
      role: "group",
      "aria-label": "Actions",
    });
    for (const button of payload.spec.buttons) {
      if (button.visible === false) continue;
      const control = h(
        "button",
        {
          class: `btn ${button.name === "action_confirm" ? "btn-primary" : ""}`,
          type: "button",
        },
        button.label,
      );
      control.addEventListener("click", () => {
        void (async () => {
          try {
            control.disabled = true;
            const result = await rpc<FormPayload>("object.action", {
              app: payload.app_key,
              action_id: payload.action.id,
              id: payload.record_id,
              menu: payload.menu_id,
              name: button.name,
            });
            toast(result.message ?? "Action completed.", "success");
            onSaved(result, `${result.record_url}${suffix}`);
          } catch (error) {
            toast(
              error instanceof RpcError ? error.message : "The action could not be completed.",
              "danger",
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
    "Save",
  );
  form.appendChild(
    h(
      "div",
      { class: "form-actions" },
      saveButton,
      h("a", { class: "btn", href: `${payload.base_url}${suffix}` }, "Discard"),
    ),
  );

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!canSave || saveButton.disabled) return;
    saveButton.disabled = true;
    saveButton.textContent = "Saving\u2026";
    try {
      const saved = await rpc<FormPayload>("view.save", {
        app: payload.app_key,
        action_id: payload.action.id,
        id: payload.record_id,
        values: collect(form),
        menu: payload.menu_id,
      });
      toast(saved.message ?? "Record saved.", "success");
      const url = `${saved.record_url}${suffix}`;
      onSaved(saved, url);
    } catch (error) {
      const message =
        error instanceof RpcError ? error.message : "The record could not be saved.";
      toast(message, "danger");
      focusFirstInvalid(form);
      saveButton.disabled = false;
      saveButton.textContent = "Save";
    }
  });
  const scanButton = form.querySelector<HTMLElement>("[data-barcode-scan]");
  if (scanButton && payload.record_id !== null) {
    scanButton.addEventListener("click", () => {
      void (async () => {
        const input = form.querySelector<HTMLInputElement>("[data-barcode-input]");
        if (!input?.value.trim()) return;
        try {
          await rpc("inventory.scan", {
            picking_id: payload.record_id,
            code: input.value.trim(),
          });
          const fresh = await rpc<FormPayload>("view.form", {
            app: payload.app_key,
            action_id: payload.action.id,
            id: payload.record_id,
            menu: payload.menu_id,
          });
          toast("Line added from barcode.", "success");
          onSaved(fresh, `${fresh.record_url}${suffix}`);
        } catch (error) {
          toast(
            error instanceof RpcError ? error.message : "Barcode not recognised.",
            "danger",
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

function widget(field: FormField, value: unknown): HTMLElement {
  if (field.readonly) {
    return h(
      "span",
      { class: "readonly-value" },
      displayValue(
        value,
        field.type,
        field.options.map((option) => [String(option.value), option.label]),
      ),
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
        "aria-label": "Scan barcode",
      }),
      h("button", { class: "btn btn-sm", type: "button", "data-barcode-scan": "" }, "Add line"),
    );
  }
  if (field.widget === "status") {
    const bar = h("div", { class: "status-bar", role: "status", "aria-label": field.label });
    for (const option of field.options) {
      bar.appendChild(
        h(
          "span",
          {
            class: `status-pill${String(option.value) === String(value) ? " status-active" : ""}`,
          },
          option.label,
        ),
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
      "aria-label": field.label,
    });
    const choice = (label: string, option: string, checked: boolean): HTMLElement =>
      h(
        "label",
        { class: "radio" },
        h("input", {
          type: "radio",
          name: field.name,
          value: option,
          checked,
        }),
        h("span", {}, label),
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
          checked: Boolean(value),
        }),
        h("span", {}, field.label),
      );
    case "selection":
    case "many2one": {
      const select = h("select", {
        class: "input",
        name: field.name,
        id: `f-${field.name}`,
        required,
      });
      select.appendChild(h("option", { value: "" }, "\u2014"));
      const selected = rawValue(value);
      for (const option of field.options) {
        select.appendChild(
          h(
            "option",
            { value: String(option.value), selected: String(option.value) === selected },
            option.label,
          ),
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
        size: 6,
      });
      const selected = new Set(
        Array.isArray(value) ? value.map((item) => rawValue(item)) : [],
      );
      for (const option of field.options) {
        select.appendChild(
          h(
            "option",
            {
              value: String(option.value),
              selected: selected.has(String(option.value)),
            },
            option.label,
          ),
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
        value: rawValue(value),
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
        required,
      });
    case "date":
      return h("input", {
        class: "input",
        type: "date",
        name: field.name,
        id: `f-${field.name}`,
        value: rawValue(value).slice(0, 10),
        required,
      });
    default:
      return h("input", {
        class: "input",
        type: "text",
        name: field.name,
        id: `f-${field.name}`,
        value: rawValue(value),
        required,
      });
  }
}

function linesWidget(field: FormField): HTMLElement {
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
      const last = body.lastElementChild as HTMLElement | null;
      last?.querySelector<HTMLElement>("input, select")?.focus();
    });
    wrap.appendChild(add);
  }
  wrap.appendChild(
    h(
      "p",
      { class: "muted line-hint" },
      "Quantities and prices recalculate the totals when you save.",
    ),
  );
  return wrap;
}

function lineRow(
  field: FormField,
  line: RecordValues,
  key: string,
): HTMLElement {
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
          h("span", { "aria-hidden": "true" }, "\u00d7"),
          h("span", { class: "visually-hidden" }, "Remove line"),
        ),
      ),
    );
  }
  return row;
}

function lineInput(sub: FormField, value: unknown, name: string): HTMLElement {
  if (sub.readonly) {
    return h("span", { class: "readonly-value" }, rawValue(value));
  }
  if (sub.type === "many2many") {
    const select = h("select", {
      class: "input input-sm",
      name,
      multiple: true,
      size: 3,
    });
    const selected = new Set(
      Array.isArray(value) ? value.map((item) => String(rawValue(item))) : [],
    );
    for (const option of sub.options) {
      select.appendChild(
        h(
          "option",
          { value: String(option.value), selected: selected.has(String(option.value)) },
          option.label,
        ),
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
            selected: String(option.value) === rawValue(value),
          },
          option.label,
        ),
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
      value: rawValue(value),
    });
  }
  return h("input", { class: "input input-sm", type: "text", name, value: rawValue(value) });
}

function groupSection(group: FormGroup, record: RecordValues): HTMLElement {
  const section = h("section", { class: "panel form-group" });
  if (group.title) section.appendChild(h("h2", { class: "section-title" }, group.title));
  const grid = h("div", { class: "form-grid" });
  for (const field of group.fields) {
    const value = record[field.name] ?? field.value;
    const wrapper = h("div", {
      class: `field${
        field.type === "text" || field.type === "one2many" || field.widget === "status"
          ? " field-wide"
          : ""
      }`,
    });
    if (field.widget === "radio") {
      wrapper.appendChild(h("span", { class: "field-label" }, field.label));
    } else if (field.type !== "boolean" && field.widget !== "status") {
      wrapper.appendChild(
        h(
          "label",
          { class: "field-label", for: `f-${field.name}` },
          field.label,
          field.required ? h("span", { class: "required" }, " *") : null,
        ),
      );
    }
    wrapper.appendChild(widget(field, value));
    grid.appendChild(wrapper);
  }
  section.appendChild(grid);
  return section;
}

function formTabs(payload: FormPayload): HTMLElement {
  const tabs = h("div", { class: "form-tabs" });
  payload.spec.pages.forEach((page, index) => {
    const tabId = `form-tab-${index + 1}`;
    tabs.appendChild(
      h("input", {
        class: "tab-input",
        type: "radio",
        name: "form-tab",
        id: tabId,
        checked: index === 0,
      }),
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

function smartButtons(payload: FormPayload): HTMLElement {
  const row = h("div", { class: "smart-buttons", role: "list" });
  for (const button of payload.smart_buttons) {
    row.appendChild(
      h(
        "div",
        { class: "smart-button", role: "listitem" },
        h("strong", {}, String(button.count)),
        h("span", {}, button.label),
      ),
    );
  }
  return row;
}

type FieldElement = HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement;

function inputValue(element: FieldElement): unknown {
  if (element instanceof HTMLInputElement && element.type === "checkbox") {
    return element.checked;
  }
  if (element instanceof HTMLInputElement && element.type === "radio") {
    return element.checked ? element.value === "1" : undefined;
  }
  if (element instanceof HTMLSelectElement && element.multiple) {
    return Array.from(element.selectedOptions)
      .map((option) => option.value)
      .filter(Boolean);
  }
  return element.value;
}

function collect(form: HTMLFormElement): RecordValues {
  const values: RecordValues = {};
  const lines: Record<string, Record<string, RecordValues>> = {};
  const deleted = new Set<string>();
  form.querySelectorAll<FieldElement>("[name]").forEach((element) => {
    if (!element.name || element.name === "csrf_token") return;
    const nested = /^(.+)\[([^[\]]+)\]\[([^[\]]+)\]$/.exec(element.name);
    if (!nested) {
      const value = inputValue(element);
      if (value !== undefined) values[element.name] = value;
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
    if (value === undefined) return;
    const rows = (lines[field] ??= {});
    const row = (rows[key] ??= {});
    row[subfield] = value;
  });

  for (const [field, rows] of Object.entries(lines)) {
    values[field] = Object.entries(rows)
      .filter(([key]) => !deleted.has(`${field}::${key}`))
      .map(([key, row]) => ({
        ...(/^\d+$/.test(key) ? { id: Number(key) } : {}),
        ...row,
      }));
  }
  return values;
}

function focusFirstInvalid(form: HTMLFormElement): void {
  const first = form.querySelector<HTMLInputElement>("[required]");
  if (first && !first.value) first.focus();
}

function chatter(payload: FormPayload): HTMLElement {
  const section = h("section", { class: "panel chatter" });
  const heading = h("div", { class: "chatter-head-row" });
  heading.appendChild(h("h2", { class: "section-title" }, "Chatter"));
  heading.appendChild(
    postForm(payload, "follow", [], h("button", { class: "btn btn-sm", type: "submit" }, "Follow")),
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
          name,
        ),
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
        "aria-label": "Add a note",
      }),
    ],
    h("button", { class: "btn", type: "submit" }, "Add note"),
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
    const created = message.create_date
      ? String(message.create_date).replace("T", " ").slice(0, 16)
      : "";
    list.appendChild(
      h(
        "li",
        { class: "chatter-message" },
        h(
          "div",
          { class: "chatter-head" },
          h("span", { class: "avatar" }, author.slice(0, 1).toUpperCase()),
          h("strong", {}, author),
          h("span", { class: "muted" }, created),
        ),
        h("p", { class: "chatter-body" }, message.body),
      ),
    );
  }
  section.appendChild(list);
  return section;
}

function activityBlock(payload: FormPayload): HTMLElement {
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
            activity.date_deadline ? `due ${String(activity.date_deadline).slice(0, 10)}` : "no date",
          ),
        ),
      );
      row.appendChild(
        postForm(
          payload,
          `activity/${activity.id}/done`,
          [],
          h("button", { class: "btn btn-sm", type: "submit" }, "Done"),
        ),
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
          h("input", { class: "input", type: "text", name: "summary" }),
        ),
        labelField(
          "Due date",
          h("input", { class: "input", type: "date", name: "date_deadline" }),
        ),
        labelField(
          "Note",
          h("input", { class: "input", type: "text", name: "note" }),
        ),
      ],
      h("button", { class: "btn btn-sm", type: "submit" }, "Schedule"),
    ),
  );
  block.appendChild(details);
  return block;
}

function labelField(label: string, input: HTMLElement): HTMLElement {
  return h(
    "div",
    { class: "field" },
    h("label", { class: "field-label" }, label),
    input,
  );
}

function postForm(
  payload: FormPayload,
  suffix: string,
  children: HTMLElement[],
  button: HTMLElement,
  extraClass = "",
): HTMLElement {
  const form = h("form", {
    method: "post",
    action: `${payload.base_url}/${payload.record_id}/${suffix}`,
    class: extraClass,
  });
  form.appendChild(
    h("input", { type: "hidden", name: "csrf_token", value: meta("kberp-csrf") }),
  );
  if (payload.menu_id) {
    form.appendChild(
      h("input", { type: "hidden", name: "menu", value: String(payload.menu_id) }),
    );
  }
  for (const child of children) form.appendChild(child);
  form.appendChild(button);
  return form;
}

function deleteForm(payload: FormPayload): HTMLElement {
  const button = h(
    "button",
    { class: "btn btn-danger", type: "submit" },
    "Delete",
  );
  const form = h(
    "form",
    {
      method: "post",
      class: "danger-zone",
      action: `${payload.base_url}/${payload.record_id}/delete`,
    },
    h("input", { type: "hidden", name: "csrf_token", value: meta("kberp-csrf") }),
    button,
  );
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!window.confirm("Delete this record permanently?")) return;
    button.disabled = true;
    button.textContent = "Deleting\u2026";
    try {
      const result = await rpc<{ message: string; redirect: string }>("view.unlink", {
        app: payload.app_key,
        action_id: payload.action.id,
        id: payload.record_id,
      });
      toast(result.message, "success");
      navigate(result.redirect);
    } catch (error) {
      toast(
        error instanceof RpcError ? error.message : "The record could not be deleted.",
        "danger",
      );
      button.disabled = false;
      button.textContent = "Delete";
    }
  });
  return form;
}
