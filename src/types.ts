export interface Note {
  id: string;
  pitch: number;
  start: number;
  duration: number;
  velocity: number;
}
export interface Clip {
  id: string;
  name: string;
  section_id: string;
  notes: Note[];
  audio_id: string | null;
  audio_offset: number;
}
export interface Section {
  id: string;
  name: string;
  bars: number;
  energy: number;
}
export interface Sound {
  preset: string;
  cutoff: number;
  resonance: number;
  attack: number;
  release: number;
  reverb: number;
  delay: number;
  drive: number;
  low: number;
  mid: number;
  high: number;
}
export interface Automation {
  parameter: "cutoff" | "volume_db" | "pan" | "reverb";
  section_id: string;
  points: [number, number][];
}
export interface Track {
  id: string;
  name: string;
  role: string;
  color: string;
  volume_db: number;
  pan: number;
  mute: boolean;
  solo: boolean;
  locked: boolean;
  sound: Sound;
  clips: Clip[];
  automation: Automation[];
}
export interface Project {
  id: string;
  name: string;
  revision: number;
  tempo: number;
  key: string;
  scale: string;
  seed: number;
  sections: Section[];
  tracks: Track[];
  master: { volume_db: number; ceiling: number; compression: number };
}
export interface Action {
  kind: string;
  track?: string;
  section?: string;
  params: Record<string, unknown>;
}
export interface Proposal {
  id: string;
  plan: { summary: string; actions: Action[] };
  preview: Project;
}
export interface Status {
  model: {
    downloaded: boolean;
    trained: boolean;
    name: string;
    offline: boolean;
    training: { state?: string; step?: number; steps?: number };
  };
  bridge: {
    connected: boolean;
    pending: boolean;
    result: null | { ok: boolean; message: string };
    live: Record<string, unknown>;
  };
}
export interface History {
  cursor: number;
  entries: { position: number; label: string; created: number }[];
}
export interface Message {
  role: string;
  content: string;
}

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: {
      ...(options?.body instanceof FormData
        ? {}
        : { "Content-Type": "application/json" }),
      ...options?.headers,
    },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      typeof error.detail === "string"
        ? error.detail
        : "The request could not be completed",
    );
  }
  return response.json();
}
export function post<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, { method: "POST", body: JSON.stringify(body) });
}
