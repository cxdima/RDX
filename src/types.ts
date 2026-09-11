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
  decay: number;
  sustain: number;
  release: number;
  filter_env: number;
  filter_decay: number;
  wave: string;
  unison: number;
  spread: number;
  sub: number;
  octave: number;
  reverb: number;
  delay: number;
  drive: number;
  crush: number;
  low: number;
  mid: number;
  high: number;
  chorus: number;
  flanger: number;
  phaser: number;
  autopan: number;
  motion_rate: number;
  width: number;
  glide: number;
  lfo_target: string;
  lfo_depth: number;
  lfo_rate: number;
}
export interface Automation {
  parameter:
    | "cutoff"
    | "resonance"
    | "volume_db"
    | "pan"
    | "reverb"
    | "flanger"
    | "chorus";
  section_id: string;
  points: [number, number][];
}
export interface Kit {
  kick_tune: number;
  kick_decay: number;
  kick_click: number;
  snare_tone: number;
  snare_decay: number;
  clap_spread: number;
  hat_tone: number;
  hat_decay: number;
  open_decay: number;
}
export interface Sidechain {
  /** The id of the track whose notes trigger the duck. */
  source: string;
  /** Depth as a fraction of the level: 0.75 leaves a quarter of it. */
  amount: number;
  attack: number;
  release: number;
  curve: string;
  trigger: string;
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
  kit: Kit | null;
  sidechain: Sidechain | null;
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
  plan: { summary: string; note: string; actions: Action[] };
  /** Generated from the real diff by the server, not written by the model. */
  summary: string;
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
    live: {
      tempo?: number;
      track_count?: number;
      has_content?: boolean;
      playing?: boolean;
      tracks?: {
        name: string;
        midi: boolean;
        devices: {
          name: string;
          kind: string;
          plugin: boolean;
          parameter_count: number;
          parameters: { name: string; min: number; max: number; value: number }[];
        }[];
      }[];
    };
    /** The live.js build running in Max, and the one this studio expects. */
    device_version: number | null;
    device_current: number;
  };
}
export interface MixFinding {
  problem: string;
  headline: string;
  detail: string;
  tracks: string[];
  actions: Action[];
}
export interface MixReport {
  measured: boolean;
  revision: number;
  /** Set when an older revision was measured, so "out of date" can be said. */
  stale_revision?: number | null;
  /** Absent until the mix has been rendered and measured at this revision. */
  mix?: {
    bands: Record<string, number>;
    crest_db: number;
    peak_db: number;
    loudness_lufs: number;
  };
  findings?: MixFinding[];
  summary?: string;
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
