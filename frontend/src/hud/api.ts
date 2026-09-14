import { getBase } from '../lib/api';

async function j<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getBase()}${path}`, init);
  if (!res.ok) throw new Error(`${path} -> HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

// -- Vitals / Conduits / Tools -------------------------------------------------

export interface VitalRow {
  label: string;
  value: string;
  pct: string;
}
export const fetchVitals = () => j<{ vitals: VitalRow[]; draw_watts: number | null }>('/v1/hud/vitals');

export interface AffectState {
  urgency: 'emergency' | 'important' | 'normal';
  momentum: number;
  familiarity: number;
  label: 'alert' | 'focused' | 'cautious' | 'warm' | 'confident' | 'steady';
}
export const fetchAffect = (text = '') =>
  j<AffectState>(`/v1/hud/affect${text ? `?text=${encodeURIComponent(text)}` : ''}`);

export const fetchChannelStatus = () => j<{ status: string }>('/v1/channels/status');

// -- WhatsApp pairing --------------------------------------------------------

export const fetchWhatsAppQr = () => j<{ status: string; qr: string | null }>('/v1/channels/whatsapp/qr');
export const connectWhatsApp = () =>
  j<{ status: string }>('/v1/channels/whatsapp/connect', { method: 'POST' });

// -- Self-improvement (auto-learning) -------------------------------------------

export interface LearningStatus {
  enabled: boolean;
  active: boolean;
  running: boolean;
  idle_seconds?: number;
  minimum_idle_seconds?: number;
  last_run_at?: number | null;
  last_result?: LearningResult | null;
  trace_count: number;
  reason?: string;
}
export interface LearningResult {
  timestamp: number;
  status: 'skipped' | 'completed' | 'rejected';
  reason?: string;
  sft_pairs?: number;
  web_sft_pairs?: number;
  routing_classes?: number;
  agent_classes?: number;
  baseline_score?: number | null;
  post_score?: number | null;
  improvement?: number | null;
  accepted?: boolean;
}
export const fetchLearningStatus = () => j<LearningStatus>('/v1/hud/learning-status');
export const runLearningCycle = () =>
  j<LearningResult>('/v1/hud/learning-run', { method: 'POST' });

export interface ToolRow {
  name: string;
  enabled: boolean;
  description: string;
}
export const fetchTools = () => j<{ tools: ToolRow[]; enabled_count: number }>('/v1/config/tools');
export const toggleTool = (name: string, enabled: boolean) =>
  j('/v1/config/tools', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, enabled }),
  });

// -- Generated tools (dynamic tool creation) ---------------------------------

export interface GeneratedToolRow {
  name: string;
  description: string;
  registered: boolean;
  created_at: number | null;
}
export const fetchGeneratedTools = () =>
  j<{ tools: GeneratedToolRow[]; count: number }>('/v1/hud/generated-tools');
export const removeGeneratedTool = (name: string) =>
  j<{ status: string; name: string; restart: string }>(
    `/v1/hud/generated-tools/${encodeURIComponent(name)}/remove`,
    { method: 'POST' }
  );

// -- Reckoning (savings) ------------------------------------------------------------

export interface ProviderSavings {
  provider: string;
  label: string;
  total_cost: number;
  energy_wh: number;
}
export interface SavingsSummary {
  total_calls: number;
  total_tokens: number;
  local_cost: number;
  per_provider: ProviderSavings[];
  session_duration_hours: number;
}
export const fetchSavingsSummary = () => j<SavingsSummary>('/v1/savings');

// -- Governance (config) -------------------------------------------------------------

export interface OrionConfigView {
  model: string;
  engine: string;
  temperature: number;
  max_tokens: number;
  obsidian_dir: string;
  learning_enabled: boolean;
}
export const fetchConfig = () => j<OrionConfigView>('/v1/config');

// -- Auto-reply --------------------------------------------------------------

export interface AutoReplySettings {
  enabled: boolean;
  allowlist: string[];
}
export const fetchAutoReply = () => j<AutoReplySettings>('/v1/config/auto-reply');
export const updateAutoReply = (patch: Partial<AutoReplySettings>) =>
  j<AutoReplySettings>('/v1/config/auto-reply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(patch),
  });

// -- Recollection (memory) -----------------------------------------------------------

export interface MemoryResult {
  content: string;
  score: number;
  metadata: Record<string, unknown>;
}
export const searchMemory = (query: string, top_k = 6) =>
  j<{ results: MemoryResult[] }>('/v1/memory/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ query, top_k }),
  });

export interface MemoryGraphNode {
  id: string;
  type: string;
  label: string;
  created_at: number;
}
export interface MemoryGraphEdge {
  source: string;
  target: string;
  type: string;
  weight: number;
}
export const fetchMemoryGraph = (limit = 150) =>
  j<{ nodes: MemoryGraphNode[]; edges: MemoryGraphEdge[]; note?: string }>(
    `/v1/hud/memory-graph?limit=${limit}`,
  );

export interface RelationshipSummary {
  total_memories: number;
  days_active: number;
  recurring_topics: string[];
  acceptance_rate: number | null;
  text: string;
}
export const fetchRelationship = () => j<RelationshipSummary>('/v1/hud/relationship');

// -- Delegates (agents) ---------------------------------------------------------------

export interface ManagedAgent {
  id: string;
  name: string;
  agent_type: string;
  status: string;
  summary_memory: string;
  total_runs?: number;
  total_cost?: number;
  total_tokens?: number;
}
export const fetchAgents = async () => {
  const data = await j<{ agents?: ManagedAgent[] }>('/v1/managed-agents');
  return data.agents || [];
};

// -- The Chronicle (traces) ------------------------------------------------------------

export interface TraceRow {
  trace_id: string;
  query: string;
  agent: string;
  model: string;
  outcome: string;
  started_at: number;
  total_tokens: number;
  total_latency_seconds: number;
}
export const fetchTraces = (limit = 40) => j<{ traces: TraceRow[]; note?: string }>(`/v1/traces?limit=${limit}`);

// -- Anatomy ----------------------------------------------------------------------------

export interface ModelAnatomy {
  available: boolean;
  reason?: string;
  model?: string;
  family?: string;
  parameter_size?: string;
  quantization_level?: string;
  format?: string;
  context_length?: number | null;
  layer_count?: number | null;
  embedding_length?: number | null;
  attention_heads?: number | null;
  capabilities?: string[];
  adapters?: string[];
}
export const fetchAnatomy = () => j<ModelAnatomy>('/v1/model/anatomy');

// -- Data console -------------------------------------------------------------------------

export interface StoreRow {
  name: string;
  detail: string;
}
export const fetchStores = () => j<{ stores: StoreRow[] }>('/v1/dataconsole/stores');
export const runQuery = (store: string, sql: string) =>
  j<{ columns: string[]; rows: unknown[][]; row_count: number; elapsed_ms: number }>('/v1/dataconsole/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ store, sql }),
  });

// -- The Council --------------------------------------------------------------------------

export interface CouncilSeat {
  key: string;
  name: string;
  status: string;
  tokens: number;
  text?: string;
  elapsed_s?: number;
  error?: string;
}
export interface CouncilRun {
  run_id: string;
  directive: string;
  status: string;
  seats: CouncilSeat[];
  concord?: number | null;
  error?: string;
}
export const startCouncilRun = (directive: string) =>
  j<{ run_id: string; status: string }>('/v1/council/run', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ directive }),
  });
export const fetchCouncilStatus = (runId: string) => j<CouncilRun>(`/v1/council/status?run_id=${runId}`);

// -- Connections (accounts, keys and services) -----------------------------------

export interface ConnectionField {
  key: string;
  label: string;
  secret: boolean;
  required: boolean;
  placeholder: string;
  help: string;
  /** Whether a value is stored. Secret values are never sent to the browser. */
  set: boolean;
  value: string;
}

export interface Connection {
  id: string;
  name: string;
  category: string;
  unlocks: string;
  kind: 'credentials' | 'connector' | 'oauth' | 'whatsapp';
  fields: ConnectionField[];
  status: 'connected' | 'ready' | 'not_connected' | 'coming_soon';
  /** Non-empty = listed but not usable yet; explains why. */
  coming_soon?: string;
  setup_url: string;
  setup_steps: string;
  restart_required: boolean;
  cloud: boolean;
  can_verify: boolean;
  oauth?: { state: 'waiting' | 'done' | 'error'; message: string } | null;
  /** A browser sign-in works without the user creating an OAuth client. */
  one_click?: boolean;
}

export interface ConnectionResult {
  ok: boolean;
  saved?: boolean;
  message: string;
  connection?: Connection;
}

/** Like j(), but surfaces the server's `detail` message instead of a bare status. */
async function jd<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${getBase()}${path}`, init);
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error((body as { detail?: string }).detail || `HTTP ${res.status}`);
  return body as T;
}

export const fetchConnections = () => jd<{ connections: Connection[] }>('/v1/connections');
export const saveConnection = (id: string, values: Record<string, string>) =>
  jd<ConnectionResult>(`/v1/connections/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ values }),
  });
export const verifyConnection = (id: string) =>
  jd<ConnectionResult>(`/v1/connections/${id}/verify`, { method: 'POST' });
export const authorizeConnection = (id: string) =>
  jd<{ state: string; message: string }>(`/v1/connections/${id}/authorize`, { method: 'POST' });
export const disconnectConnection = (id: string) =>
  jd<ConnectionResult>(`/v1/connections/${id}`, { method: 'DELETE' });
export const restartBackend = () => jd<{ restart: string }>('/v1/connections/restart', { method: 'POST' });

/** Readable tool label: "browser_navigate" -> "Browser navigate", "kg_query" -> "Knowledge graph query". */
const TOOL_WORDS: Record<string, string> = {
  kg: 'Knowledge graph',
  llm: 'LLM',
  pdf: 'PDF',
  db: 'Database',
  http: 'HTTP',
  repl: 'Python REPL',
  axtree: 'accessibility tree',
};
export function toolLabel(name: string): string {
  const words = name.split('_').map((w) => TOOL_WORDS[w] ?? w);
  const text = words.join(' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}
