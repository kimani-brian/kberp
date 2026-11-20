/** Display formatting shared by list cells and form read-only values. */

export type Selection = Array<[string, string]>;
export type RecordValue = unknown;

export function displayValue(
  value: RecordValue,
  type: string,
  selection?: Selection,
): string {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "object") {
    if (Array.isArray(value)) {
      return value
        .map((item) =>
          typeof item === "object" && item !== null
            ? String((item as { name?: unknown; id?: unknown }).name ?? (item as { id?: unknown }).id ?? "")
            : String(item),
        )
        .filter(Boolean)
        .join(", ");
    }
    const named = value as { name?: unknown; id?: unknown };
    return String(named.name ?? named.id ?? "");
  }
  if (type === "boolean") return value ? "Yes" : "No";
  if (type === "monetary" || type === "float") {
    const number = Number(value);
    return Number.isFinite(number)
      ? number.toLocaleString(undefined, {
          minimumFractionDigits: 2,
          maximumFractionDigits: 2,
        })
      : String(value);
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

export function rawValue(value: RecordValue): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") {
    const named = value as { id?: unknown };
    return named.id === undefined ? "" : String(named.id);
  }
  return String(value);
}
