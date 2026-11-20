/** Server payloads for `view.load`, `view.form` and `view.save`. */

export interface Breadcrumb {
  name: string;
  url: string | null;
}

export interface WindowAction {
  id: number;
  name: string;
  res_model: string;
  view_mode: string;
}

export interface SelectionOption {
  value: string | number;
  label: string;
}

export interface ListColumn {
  name: string;
  label: string;
  type: string;
  selection?: Array<[string, string]>;
}

export interface ListSpec {
  string: string;
  columns: ListColumn[];
  can_create: boolean;
  can_delete: boolean;
}

export interface KanbanField {
  name: string;
  label: string;
  type: string;
}

export interface KanbanSpec {
  string: string;
  fields: KanbanField[];
}

export interface SearchFilter {
  name: string;
  label: string;
  domain: unknown[];
}

export interface SearchGroupBy {
  name: string;
  label: string;
}

export interface SearchSpec {
  search_fields: Array<{ name: string; label: string }>;
  filters: SearchFilter[];
  group_bys: SearchGroupBy[];
}

export type RecordValues = Record<string, unknown>;

export interface RecordGroup {
  value: unknown;
  label: string;
  count: number;
  records: Array<RecordValues & { id: number }>;
}

export interface ListPayload {
  action: WindowAction;
  app_key: string;
  spec: ListSpec;
  kanban: KanbanSpec | null;
  view: string;
  search: SearchSpec;
  records: Array<RecordValues & { id: number }>;
  groups: RecordGroup[];
  fields_meta: Record<string, unknown>;
  q: string;
  selected_filter: string;
  selected_group: string;
  total: number;
  offset: number;
  limit: number;
  prev_offset: number;
  next_offset: number | null;
  menu_id: number | null;
  breadcrumbs: Breadcrumb[];
  can_create: boolean;
  can_write: boolean;
  can_unlink: boolean;
  base_url: string;
}

export interface FormField {
  name: string;
  label: string;
  type: string;
  widget: string;
  required: boolean;
  readonly: boolean;
  options: SelectionOption[];
  value: unknown;
  rows: number | string;
  subfields?: FormField[];
  lines?: Array<RecordValues & { id: number }>;
  editable?: boolean;
}

export interface FormButton {
  name: string;
  label: string;
  visible?: boolean;
}

export interface FormGroup {
  title: string;
  fields: FormField[];
}

export interface FormPage {
  title: string;
  groups: FormGroup[];
}

export interface FormReport {
  name: string;
  label: string;
}

export interface FormSpec {
  string: string;
  buttons: FormButton[];
  reports: FormReport[];
  groups: FormGroup[];
  pages: FormPage[];
}

export interface ChatterMessage {
  id: number;
  body: string;
  author_id?: { id: number; name: string } | null;
  create_date?: string | null;
}

export interface ChatterFollower {
  id: number;
  partner_id?: { id: number; name: string } | null;
}

export interface ChatterActivity {
  id: number;
  summary?: string | null;
  date_deadline?: string | null;
  activity_type_id?: { id: number; name: string } | null;
  user_id?: { id: number; name: string } | null;
}

export interface ActivityType {
  id: number;
  name: string;
}

export interface SmartButton {
  key: string;
  label: string;
  count: number;
}

export interface FormPayload {
  action: WindowAction;
  app_key: string;
  spec: FormSpec;
  record_id: number | null;
  record: RecordValues;
  messages: ChatterMessage[];
  followers: ChatterFollower[];
  activities: ChatterActivity[];
  activity_types: ActivityType[];
  smart_buttons: SmartButton[];
  fields_meta: Record<string, unknown>;
  menu_id: number | null;
  breadcrumbs: Breadcrumb[];
  base_url: string;
  record_url: string;
  title_text: string;
  can_create: boolean;
  can_write: boolean;
  can_unlink: boolean;
  ok?: boolean;
  id?: number;
  message?: string;
}
