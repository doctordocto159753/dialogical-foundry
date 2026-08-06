export type OutputFormat = "json" | "md" | "both";
export type RunStatus = "pending" | "running" | "completed" | "failed" | "interrupted";
export type Provider = "mock" | "mock_notopk" | "anthropic" | "openai" | "gemini";
export type ModelMode = "standard" | "deep_research";
export type OpenAIAPI = "chat_completions" | "responses";
export type SearchProvider = "mock" | "tavily";

export interface LoopCounts {
  ideation: number;
  architecture: number;
  workpackage: number;
}

export interface TokenUsage {
  input: number;
  output: number;
  total: number;
}

export interface OutputEntry {
  name: string;
  layer: string;
  format: "json" | "md";
  bytes: number;
  url: string;
}

export interface FoundryRun {
  id: string;
  status: RunStatus;
  format: OutputFormat;
  brief: string;
  loops: LoopCounts;
  tokens: TokenUsage;
  completed_layers: string[];
  error: string | null;
  created_at: string;
  updated_at: string;
  outputs: OutputEntry[];
}

export interface CreateRunInput {
  brief: string;
  pastedText: string;
  githubUrl: string;
  outputFormat: OutputFormat;
  loopCounts: LoopCounts;
  files: File[];
}

export interface CreateRunResult {
  id: string;
  status: "pending";
  events_url: string;
}

export interface AppSettings {
  default_format: OutputFormat;
  loops: LoopCounts;
  search_provider: SearchProvider;
  search_key_ref: string | null;
}

export interface NodeSettings {
  id: string;
  role: string;
  provider: Provider;
  model: string;
  base_url?: string | null;
  openai_api: OpenAIAPI;
  mode: ModelMode;
  normalization_model?: string | null;
  research_timeout_seconds: number;
  research_poll_interval_seconds: number;
  research_max_tool_calls: number;
  research_thinking_summaries: boolean;
  research_visualization: boolean;
  api_key_ref?: string | null;
  temperature?: number;
  top_k?: number | null;
  top_p?: number | null;
  max_tokens?: number | null;
  tools: string[];
}

export interface SavedKey {
  id: string;
  provider: string;
  label: string;
  fingerprint: string;
  created_at: string;
  updated_at: string;
}

export const RUN_EVENT_TYPES = [
  "run.started",
  "run.interrupted",
  "layer.started",
  "node.started",
  "node.research.started",
  "node.research.poll",
  "node.research.completed",
  "node.retry",
  "node.completed",
  "tokens.updated",
  "layer.completed",
  "run.failed",
  "run.completed",
] as const;

export type RunEventType = (typeof RUN_EVENT_TYPES)[number];

export interface RunEventPayload {
  run_id?: string;
  layer_id?: string;
  name?: string;
  node_id?: string;
  node?: string;
  role?: string;
  iteration?: number | null;
  attempt?: number;
  error?: string;
  tokens?: TokenUsage;
  outputs?: string[] | string;
  canonical?: string;
  ms?: number;
  input_refs?: string[];
  prompt_variant?: string;
  tokens_in?: number;
  tokens_out?: number;
  resumed?: boolean;
  provider?: string;
  remote_id?: string;
  remote_status?: string;
  continuation?: number;
}

export interface RunEventEnvelope {
  seq: number;
  type: RunEventType;
  payload: RunEventPayload;
  at?: string;
}

export interface Health {
  status: "ok";
  version: string;
  data_dir: string;
}

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, init);
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string | Array<{ msg?: string }> };
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail)) message = body.detail.map((item) => item.msg).filter(Boolean).join("; ") || message;
    } catch {
      // Keep the status-based fallback for non-JSON failures.
    }
    throw new ApiError(message, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function createRun(input: CreateRunInput): Promise<CreateRunResult> {
  const form = new FormData();
  form.set("brief", input.brief);
  form.set("pasted_text", input.pastedText);
  form.set("github_url", input.githubUrl);
  form.set("output_format", input.outputFormat);
  form.set("loop_counts", JSON.stringify(input.loopCounts));
  input.files.forEach((file) => form.append("files", file));
  return request<CreateRunResult>("/api/runs", { method: "POST", body: form });
}

export const api = {
  health: () => request<Health>("/api/health"),
  runs: () => request<FoundryRun[]>("/api/runs"),
  run: (id: string) => request<FoundryRun>(`/api/runs/${encodeURIComponent(id)}`),
  resumeRun: (id: string) => request<{ id: string; status: "pending" }>(`/api/runs/${encodeURIComponent(id)}/resume`, { method: "POST" }),
  deleteRun: (id: string) => request<void>(`/api/runs/${encodeURIComponent(id)}`, { method: "DELETE" }),
  outputText: async (url: string) => {
    const response = await fetch(url);
    if (!response.ok) throw new ApiError(`Output could not be loaded (${response.status})`, response.status);
    return response.text();
  },
  settings: () => request<AppSettings>("/api/settings"),
  saveSettings: (value: AppSettings) => request<AppSettings>("/api/settings", jsonRequest("PUT", value)),
  nodes: () => request<NodeSettings[]>("/api/settings/nodes"),
  saveNode: (id: string, value: Omit<NodeSettings, "id" | "role">) => request<NodeSettings>(`/api/settings/nodes/${encodeURIComponent(id)}`, jsonRequest("PUT", value)),
  keys: () => request<SavedKey[]>("/api/keys"),
  createKey: (value: { provider: string; label: string; value: string }) => request<SavedKey>("/api/keys", jsonRequest("POST", value)),
  deleteKey: (id: string) => request<void>(`/api/keys/${encodeURIComponent(id)}`, { method: "DELETE" }),
};

function jsonRequest(method: "POST" | "PUT", body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export function countWords(value: string): number {
  const normalized = value.trim();
  return normalized ? normalized.split(/\s+/u).length : 0;
}

export function isCanonicalGithubUrl(value: string): boolean {
  return value === "" || /^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+(?:\.git)?\/?$/.test(value.trim());
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
