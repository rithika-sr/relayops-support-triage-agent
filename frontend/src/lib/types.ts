// Response shapes returned by the RelayOps API.

export type Role = "admin" | "support" | "customer";

export interface Me {
  user_id: string;
  email: string;
  name: string;
  role: Role;
  organization: { id: string; name: string };
  customer_account: { id: string; name: string | null } | null;
}

export interface Target {
  due_at: string | null;
  responded_at: string | null;
  state: "due" | "breached" | "met" | "missed" | "none";
  seconds_remaining?: number | null;
  policy: { policy_version?: string; hours?: number; basis?: string; reasons?: string[]; priority?: string };
}

export interface Ticket {
  id: string;
  number: number;
  subject: string;
  status: string;
  priority: string;
  reported_severity: string;
  component: string | null;
  product_version: string | null;
  error_code: string | null;
  created_at: string;
  updated_at: string;
  customer_account_id: string;
  account_name: string | null;
  revision?: number;
  restricted?: boolean;
  target?: Target;
  tags?: string[];
}

export interface Message {
  id: string;
  author_kind: "customer" | "staff" | "system";
  author_name: string | null;
  visibility: "customer" | "internal";
  body: string;
  action_id: string | null;
  created_at: string;
}

export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Account {
  id: string;
  name: string;
  plan: string;
  product_version: string;
}

export interface RunSummary {
  id: string;
  ticket_id: string;
  ticket_number: number | null;
  ticket_subject: string | null;
  status: string;
  mode: "live" | "recorded_replay";
  replay_of_run_id: string | null;
  compare_of_run_id: string | null;
  playbook: string;
  playbook_revision: number;
  route: string | null;
  verdict: string | null;
  model_provider: string;
  model_name: string;
  current_node: string | null;
  usage: { turns?: number; tool_calls?: number; model_calls?: number; repairs?: number };
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
}

export interface TicketDetail {
  ticket: Ticket;
  messages: Message[];
  account?: Account & { region: string; entitlements: Record<string, boolean | number> };
  runs?: { id: string; status: string; mode: string; route: string | null; playbook: string; created_at: string }[];
  proposals?: {
    id: string;
    run_id: string;
    version: number;
    status: string;
    route: string;
    action_kind: string;
    verification_status: string;
    created_at: string;
  }[];
  actions?: { id: string; kind: string; adapter: string; status: string; receipt: Record<string, unknown>; created_at: string }[];
  issue_links?: { issue_id: string; key: string; title: string; status: string; link_kind: string }[];
  incidents: { id: string; title: string; status: string; public_summary?: string | null; severity?: string }[];
}

export interface Evidence {
  source_type: string;
  source_id: string;
  title: string;
  excerpt: string;
  visibility: string;
  version: number | null;
  content_hash: string | null;
  kind: string | null;
  authority: number | null;
  timestamp: string | null;
  snapshot_hash: string;
  meta: Record<string, unknown>;
}

export interface RunEvent {
  seq: number;
  kind: string;
  node: string | null;
  payload: Record<string, unknown>;
  created_at: string;
}

export interface Check {
  name: string;
  status: "pass" | "fail" | "warn";
  detail: string;
  method: string;
}

export interface Proposal {
  id: string;
  run_id: string;
  version: number;
  route: string;
  action_kind: string;
  destination: Record<string, unknown>;
  payload: {
    customer_reply: string;
    reply_evidence_ids: string[];
    internal_evidence_ids?: string[];
    rationale?: string;
    overrides?: string[];
    verdict?: string;
    clarifying_questions?: string[];
    missing_facts?: string[];
    observations?: string[];
    hypotheses?: string[];
    issue_key?: string | null;
    handoff?: Record<string, unknown> | null;
    computed_facts?: Record<string, unknown>;
    reply_source?: string;
  };
  payload_hash: string;
  evidence: (Evidence & { id: string })[];
  evidence_hash: string;
  policy_version: string;
  ticket_revision: number;
  verification: {
    status: string;
    failed: string[];
    checks: Check[];
    claims: { text: string; lexical_overlap: number; label: string }[];
    note: string;
  };
  verification_status: string;
  status: string;
  authored_by: string;
  created_at: string;
  stale_reasons: string[];
  reviews: { id: string; decision: string; reviewer: string; binding_hash: string; note: string | null; created_at: string }[];
}

export interface GraphNode {
  id: string;
  label: string;
  kind: string;
  state: "pending" | "active" | "completed" | "waiting" | "failed" | "cancelled";
  turns?: number;
}

export interface RunDetail {
  run: RunSummary & {
    budgets: Record<string, unknown> & { max_turns: number; max_tool_calls: number; deadline_seconds: number };
    retrieval_config: Record<string, unknown>;
    policy_version: string;
    prompt_hash: string | null;
    model_digest: string | null;
    ticket_revision: number;
    thread_id: string;
  };
  ticket: { id: string; number: number; subject: string; revision: number; status: string } | null;
  graph: GraphNode[];
  events: RunEvent[];
  evidence: Record<string, Evidence>;
  proposals: Proposal[];
  actions: { id: string; kind: string; status: string; adapter: string; receipt: Record<string, unknown>; created_at: string }[];
  last_seq: number;
}

export interface Doc {
  id: string;
  slug: string;
  title: string;
  kind: string;
  visibility: string;
  component: string | null;
  product_versions: string[];
  status: string;
  current_version: number | null;
  content_hash: string | null;
  valid_from: string | null;
  valid_to: string | null;
  customer_account_id?: string | null;
  version_count?: number;
}

export interface Issue {
  id: string;
  key: string;
  title: string;
  kind: string;
  component: string;
  status: string;
  affected_versions: string[];
  fixed_in_version: string | null;
  error_signature: string | null;
  owner_team: string;
  description: string;
  origin: string;
  linked_tickets?: number;
  updated_at: string;
}

export interface Incident {
  id: string;
  title: string;
  component: string;
  status: string;
  started_at: string;
  resolved_at: string | null;
  public_summary: string | null;
  severity?: string;
  error_signature?: string | null;
  affected_versions?: string[];
  internal_notes?: string;
  public_visible?: boolean;
  linked_tickets?: number;
  affected_accounts?: number;
}

export interface TimelineItem {
  at: string;
  lane: string;
  kind: string;
  label: string;
  source: string;
  as_of?: string;
  note?: string;
  run_id?: string;
  evidence_id?: string;
}

export interface Candidate {
  key: string;
  component: string;
  signature: string;
  product_version: string;
  ticket_count: number;
  distinct_accounts: number;
  accounts: string[];
  first_reported_at: string;
  last_reported_at: string;
  tickets: { id: string; number: number; subject: string; account: string; created_at: string; incident_id: string | null }[];
  linked_incidents: string[];
  suggested_incidents: string[];
  method: string;
}

export interface ArtifactSummary {
  id: string;
  kind: string;
  title: string;
  ticket_id: string | null;
  run_id: string | null;
  incident_id: string | null;
  review_status: string;
  current_version: number;
  verification_status: string;
  content_hash: string;
  created_at: string;
  updated_at: string;
}

export interface Overview {
  as_of: string;
  open_tickets: number;
  breached_targets: number;
  due_within_4h: number;
  restricted_open: number;
  pending_review_proposals: number;
  tickets_by_status: Record<string, number>;
  open_by_component: Record<string, number>;
  created_per_day: { day: string; count: number }[];
  runs_by_status: Record<string, number>;
}
