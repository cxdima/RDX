import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowUp,
  AudioLines,
  Check,
  ChevronDown,
  Circle,
  Copy,
  Disc3,
  Drum,
  FolderOpen,
  History as HistoryIcon,
  Layers3,
  LockKeyhole,
  Mic,
  MoreHorizontal,
  Music2,
  Pause,
  Piano,
  Play,
  PlugZap,
  Plus,
  Redo2,
  Repeat2,
  Send,
  SlidersHorizontal,
  Sparkles,
  Square,
  Trash2,
  Undo2,
  UnlockKeyhole,
  Volume2,
  Waves,
  X,
} from "lucide-react";
import {
  api,
  post,
  type Action,
  type Clip,
  type History,
  type Message,
  type MixReport,
  type Project,
  type Proposal,
  type Sound,
  type Status,
} from "./types";
import { studioAudio } from "./audio";
import PianoRoll from "./PianoRoll";

const roleIcons = {
  drums: Drum,
  bass: AudioLines,
  chords: Piano,
  lead: Music2,
  pad: Waves,
  audio: Mic,
};

const MELODIC_PRESETS = [
  "supersaw",
  "saw",
  "pluck",
  "sine",
  "sub",
  "pad",
  "strings",
  "choir",
  "bell",
  "fm",
  "noise",
] as const;
/** Named sounds, mirroring PATCHES in rdx/musical/design.py. */
const PATCHES = [
  { name: "reese", roles: ["bass"] },
  { name: "acid", roles: ["bass", "lead"] },
  { name: "supersaw_lead", roles: ["lead", "chords"] },
  { name: "hoover", roles: ["lead"] },
  { name: "pluck_stab", roles: ["lead", "chords"] },
  { name: "sub_bass", roles: ["bass"] },
  { name: "donk", roles: ["lead", "bass"] },
  { name: "wobble", roles: ["bass"] },
  { name: "warm_pad", roles: ["pad", "chords"] },
  { name: "glass_pad", roles: ["pad", "chords"] },
  { name: "bell_lead", roles: ["lead"] },
  { name: "organ", roles: ["chords", "pad"] },
  { name: "gritty_bass", roles: ["bass"] },
  { name: "vibrato_lead", roles: ["lead"] },
  { name: "tremolo_keys", roles: ["chords", "pad"] },
  { name: "riser_noise", roles: ["pad", "lead"] },
];
const WAVES = ["preset", "saw", "square", "triangle", "sine", "pulse"];
/** Mirrors SCALE_STEPS in rdx/domain.py; a scale offered here must exist there. */
const SCALES = ["major", "minor", "dorian", "phrygian", "lydian", "mixolydian"];
const LFO_TARGETS = ["off", "cutoff", "pitch", "volume"];

const PRESET_LABELS: Record<string, string> = {
  supersaw: "SUPERSAW",
  saw: "SAW",
  pluck: "PLUCK",
  sine: "SINE",
  sub: "SUB BASS",
  pad: "PAD",
  strings: "STRINGS",
  choir: "CHOIR",
  bell: "BELL",
  fm: "FM",
  noise: "NOISE / RISER",
};

function IconButton({
  title,
  onClick,
  children,
  active = false,
  disabled = false,
  className = "",
}: {
  title: string;
  onClick: () => void;
  children: React.ReactNode;
  active?: boolean;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button
      className={`icon-button ${active ? "active" : ""} ${className}`}
      aria-label={title}
      title={title}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </button>
  );
}

function Slider({
  label,
  value,
  min,
  max,
  step = 1,
  unit = "",
  onCommit,
  disabled = false,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  onCommit: (value: number) => void;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState(value);
  const committed = useRef(value);
  useEffect(() => {
    setDraft(value);
    committed.current = value;
  }, [value]);
  function commit() {
    if (draft !== value && draft !== committed.current) {
      committed.current = draft;
      onCommit(draft);
    }
  }
  return (
    <label className="parameter">
      <span>
        {label}
        <output>
          {Number.isInteger(draft) ? draft : draft.toFixed(step < 0.01 ? 3 : 2)}
          {unit}
        </output>
      </span>
      <input
        aria-label={label}
        type="range"
        min={min}
        max={max}
        step={step}
        value={draft}
        disabled={disabled}
        onChange={(e) => setDraft(Number(e.target.value))}
        onPointerUp={commit}
        onKeyUp={commit}
        onBlur={commit}
      />
    </label>
  );
}

/** Ducking depth as the decibels a producer reads, matching depth_db in Python. */
function duckLabel(amount: number) {
  return `${(20 * Math.log10(Math.max(1 - amount, 1e-4))).toFixed(1)} dB`;
}

function Meter({
  trackId,
  vertical = false,
}: {
  trackId: string;
  vertical?: boolean;
}) {
  const fill = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    let frame = 0;
    const tick = () => {
      const db = studioAudio.meter(trackId);
      if (fill.current) {
        const percent = Math.max(0, Math.min(100, ((db + 60) / 60) * 100));
        fill.current.style[vertical ? "height" : "width"] = `${percent}%`;
        fill.current.style.background = db > -1 ? "#f48d7a" : "";
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [trackId, vertical]);
  return (
    <div className={vertical ? "meter vertical" : "meter"}>
      <span ref={fill} />
    </div>
  );
}

function MiniNotes({ clip, color }: { clip: Clip; color: string }) {
  const sample = clip.notes.filter(
    (_, i) => i % Math.max(1, Math.floor(clip.notes.length / 35)) === 0,
  );
  const end = Math.max(4, ...clip.notes.map((n) => n.start + n.duration));
  const low = Math.min(36, ...sample.map((n) => n.pitch));
  const high = Math.max(low + 12, ...sample.map((n) => n.pitch));
  return (
    <div className="mini-notes" aria-hidden="true">
      {sample.map((note) => (
        <i
          key={note.id}
          style={{
            left: `${(note.start / end) * 98}%`,
            top: `${((high - note.pitch) / (high - low)) * 22}px`,
            width: `${Math.max(1.4, (note.duration / end) * 98)}%`,
            background: color,
          }}
        />
      ))}
    </div>
  );
}

function Waveform({ assetId }: { assetId: string }) {
  const [peaks, setPeaks] = useState<number[]>([]);
  useEffect(() => {
    api<{ waveform: number[] }>(`/audio/${assetId}/info`)
      .then((d) => setPeaks(d.waveform))
      .catch(() => {});
  }, [assetId]);
  return (
    <div className="waveform" aria-label="Recorded audio waveform">
      {peaks.map((peak, i) => (
        <i key={i} style={{ height: `${Math.max(2, peak * 95)}%` }} />
      ))}
    </div>
  );
}

export default function App() {
  const [project, setProject] = useState<Project | null>(null);
  const [projectList, setProjectList] = useState<
    { id: string; name: string }[]
  >([]);
  const [selectedTrack, setSelectedTrack] = useState("");
  const [selectedSection, setSelectedSection] = useState("");
  const [status, setStatus] = useState<Status | null>(null);
  const [history, setHistory] = useState<History | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [audition, setAudition] = useState(true);
  const [view, setView] = useState("arrange");
  const [chatOpen, setChatOpen] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [loop, setLoop] = useState(true);
  const [beat, setBeat] = useState(0);
  const [busy, setBusy] = useState(false);
  const [thinking, setThinking] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [prompt, setPrompt] = useState("");
  const [modal, setModal] = useState<string | null>(null);
  const [newName, setNewName] = useState("Untitled 02");
  const [recordMode, setRecordMode] = useState("hum");
  const [recording, setRecording] = useState(false);
  const [recordSeconds, setRecordSeconds] = useState(0);
  const [variation, setVariation] = useState(1);
  const [feedback, setFeedback] = useState("");
  const [mixReport, setMixReport] = useState<MixReport | null>(null);
  const uploadRef = useRef<HTMLInputElement>(null);
  const archiveRef = useRef<HTMLInputElement>(null);
  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const messageEnd = useRef<HTMLDivElement>(null);
  const active = proposal && audition ? proposal.preview : project;
  const track =
    active?.tracks.find((t) => t.id === selectedTrack) || active?.tracks[0];
  const section =
    active?.sections.find((s) => s.id === selectedSection) ||
    active?.sections[0];
  const clip = track?.clips.find((c) => c.section_id === section?.id);
  const locked = !!track?.locked || !!proposal || busy;
  useEffect(() => {
    if (view !== "record" || recording || !active || !track) return;
    const role = recordMode === "rhythm" ? "drums" : "lead";
    if (
      recordMode !== "audio" &&
      (recordMode === "rhythm"
        ? track.role !== "drums"
        : ["drums", "audio"].includes(track.role))
    ) {
      const target = active.tracks.find((t) => t.role === role && !t.locked);
      if (target) setSelectedTrack(target.id);
    }
  }, [view, recordMode, recording]);

  const refreshHistory = useCallback((id: string) => {
    api<History>(`/projects/${id}/history`)
      .then(setHistory)
      .catch(() => {});
  }, []);
  // A measurement is pinned to the revision that produced it, so a stale one
  // is shown as stale rather than quietly reused for a different arrangement.
  useEffect(() => {
    if (!project) return;
    api<MixReport>(`/projects/${project.id}/mix`)
      .then(setMixReport)
      .catch(() => {});
  }, [project?.id, project?.revision]);
  async function load(id: string) {
    studioAudio.stop();
    setPlaying(false);
    setProposal(null);
    setError("");
    const data = await api<Project>(`/projects/${id}`);
    setProject(data);
    setSelectedTrack(data.tracks[0]?.id || "");
    setSelectedSection(
      data.sections.find((s) => s.name === "Main")?.id || data.sections[0].id,
    );
    setMessages(await api<Message[]>(`/projects/${id}/messages`));
    refreshHistory(id);
  }
  useEffect(() => {
    api<{ id: string; name: string }[]>("/projects")
      .then(async (list) => {
        setProjectList(list);
        if (list.length) await load(list[0].id);
      })
      .catch((e) => setError(e.message));
    const check = () =>
      api<Status>("/status")
        .then(setStatus)
        .catch(() => {});
    check();
    const timer = setInterval(check, 3000);
    return () => {
      clearInterval(timer);
      studioAudio.stop();
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);
  useEffect(() => {
    let frame = 0;
    const tick = () => {
      setBeat((studioAudio.seconds * (active?.tempo || 124)) / 60);
      setPlaying(studioAudio.playing);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [active?.tempo]);
  useEffect(() => {
    if (project) studioAudio.updateMix(project);
  }, [project]);
  useEffect(() => {
    messageEnd.current?.scrollIntoView({
      block: "nearest",
      behavior: "smooth",
    });
  }, [messages, thinking]);
  useEffect(() => {
    if (!recording) return;
    const start = Date.now();
    const timer = setInterval(() => {
      const seconds = (Date.now() - start) / 1000;
      setRecordSeconds(seconds);
      if (seconds >= (recordMode === "audio" ? 300 : 30))
        recorderRef.current?.stop();
    }, 150);
    return () => clearInterval(timer);
  }, [recording, recordMode]);

  async function edit(actions: Action[], label: string) {
    if (!project || busy || proposal || thinking || recording) return;
    setBusy(true);
    setError("");
    try {
      const updated = await post<Project>(`/projects/${project.id}/edits`, {
        revision: project.revision,
        actions,
        label,
      });
      setProject(updated);
      refreshHistory(updated.id);
      if (
        playing &&
        !actions.every((a) => ["mix", "protect"].includes(a.kind))
      ) {
        studioAudio.stop();
        setPlaying(false);
      }
      return updated;
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function action(
    kind: string,
    params: Record<string, unknown>,
    label: string,
    target = track?.id,
    scope = section?.id,
  ) {
    return edit([{ kind, track: target, section: scope, params }], label);
  }
  async function undo(direction: string) {
    if (!project || busy || proposal || thinking || recording) return;
    setBusy(true);
    setProposal(null);
    studioAudio.stop();
    try {
      const updated = await post<Project>(
        `/projects/${project.id}/${direction}`,
        { revision: project.revision },
      );
      setProject(updated);
      refreshHistory(updated.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.target as HTMLElement).matches("input,textarea,select")) return;
      if (e.code === "Space") {
        e.preventDefault();
        void togglePlay();
      }
      if ((e.metaKey || e.ctrlKey) && e.key === "z") {
        e.preventDefault();
        void undo(e.shiftKey ? "redo" : "undo");
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [project, active, section, playing, loop, busy]);
  async function togglePlay() {
    if (busy || recording) return;
    if (playing) {
      studioAudio.stop();
      setPlaying(false);
      return;
    }
    if (!active || !section) return;
    setBusy(true);
    setError("");
    try {
      await studioAudio.play(active, section.id, loop);
      setPlaying(true);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function ask(text = prompt) {
    if (!project || !text.trim() || thinking || proposal || busy || recording)
      return;
    setThinking(true);
    setPrompt("");
    setError("");
    setMessages((previous) => [...previous, { role: "user", content: text }]);
    try {
      const result = await post<Proposal>(`/projects/${project.id}/chat`, {
        revision: project.revision,
        message: text,
        track_id: track?.id,
        section_id: section?.id,
      });
      setMessages((previous) => [
        ...previous,
        { role: "assistant", content: result.summary },
      ]);
      if (result.plan.actions.length) {
        studioAudio.stop();
        setProposal(result);
        setAudition(true);
      }
    } catch (e) {
      setMessages((previous) => [
        ...previous,
        { role: "assistant", content: (e as Error).message },
      ]);
    } finally {
      setThinking(false);
    }
  }
  async function decide(keep: boolean) {
    if (!proposal || !project) return;
    setBusy(true);
    studioAudio.stop();
    try {
      const updated = await post<Project>(`/proposals/${proposal.id}`, {
        revision: project.revision,
        keep,
        comment: feedback,
      });
      setProject(updated);
      setProposal(null);
      setFeedback("");
      refreshHistory(updated.id);
    } catch (e) {
      setError((e as Error).message);
      setProposal(null);
    } finally {
      setBusy(false);
    }
  }
  async function newProject() {
    setBusy(true);
    try {
      const created = await post<Project>("/projects", {
        name: newName,
        starter: true,
      });
      setProjectList(await api("/projects"));
      await load(created.id);
      setModal(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function importProject(file: File) {
    setBusy(true);
    setError("");
    try {
      const form = new FormData();
      form.set("file", file);
      const created = await api<Project>("/projects/import", {
        method: "POST",
        body: form,
      });
      setProjectList(await api("/projects"));
      await load(created.id);
      setModal(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (archiveRef.current) archiveRef.current.value = "";
    }
  }
  async function upload(file: File, mode = recordMode) {
    if (!project || !section) return;
    setBusy(true);
    setError("");
    try {
      const data = new FormData();
      data.set("file", file);
      data.set("revision", String(project.revision));
      data.set("section_id", section.id);
      data.set("track_id", track?.id || "");
      data.set("mode", /\.midi?$/i.test(file.name) ? "midi" : mode);
      const updated = await api<Project>(`/projects/${project.id}/audio`, {
        method: "POST",
        body: data,
      });
      setProject(updated);
      refreshHistory(updated.id);
      setNotice(
        mode === "audio"
          ? "Recording added"
          : "Recording converted to editable notes",
      );
      if (mode === "audio") setSelectedTrack(updated.tracks.at(-1)!.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (uploadRef.current) uploadRef.current.value = "";
    }
  }
  async function toggleRecord() {
    if (recording) {
      recorderRef.current?.stop();
      return;
    }
    setError("");
    studioAudio.stop();
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
        },
      });
      streamRef.current = stream;
      const recorder = new MediaRecorder(stream);
      recorderRef.current = recorder;
      const chunks: BlobPart[] = [];
      recorder.ondataavailable = (e) => {
        if (e.data.size) chunks.push(e.data);
      };
      recorder.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        streamRef.current = null;
        setRecording(false);
        void upload(
          new File(chunks, `Recording-${Date.now()}.webm`, {
            type: recorder.mimeType,
          }),
          recordMode,
        );
      };
      recorder.start();
      setRecording(true);
      setRecordSeconds(0);
    } catch (e) {
      setError((e as Error).message);
    }
  }
  async function exportWav() {
    if (!active) return;
    setBusy(true);
    setModal(null);
    setNotice("Rendering audio...");
    try {
      const blob = await studioAudio.render(active);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${active.name}.wav`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      setNotice("WAV render complete");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  /** Render every track, upload the stems and let the server measure them. */
  async function analyseMix() {
    if (!project || busy) return;
    setBusy(true);
    setError("");
    setNotice("Rendering the mix to measure it...");
    try {
      const stems: Record<string, string> = {};
      for (const source of project.tracks) {
        const solo = {
          ...project,
          tracks: [{ ...source, mute: false, solo: false }],
          master: {
            ...project.master,
            volume_db: 0,
            compression: 0,
            ceiling: 0,
          },
        };
        stems[source.id] = await uploadRender(await studioAudio.render(solo));
      }
      const master = await uploadRender(await studioAudio.render(project));
      setMixReport(
        await post<MixReport>(`/projects/${project.id}/mix`, {
          revision: project.revision,
          stems,
          master,
        }),
      );
      setNotice("");
    } catch (e) {
      setError((e as Error).message);
      setNotice("");
    } finally {
      setBusy(false);
    }
  }
  async function uploadRender(blob: Blob) {
    const form = new FormData();
    form.set("file", new File([blob], "stem.wav", { type: "audio/wav" }));
    const result = await api<{ id: string }>("/renders", {
      method: "POST",
      body: form,
    });
    return result.id;
  }
  async function sendAbleton() {
    if (!project) return;
    setBusy(true);
    setError("");
    setNotice("Rendering stems for Ableton...");
    try {
      const stems: Record<string, string> = {};
      for (const source of project.tracks) {
        const stemProject = {
          ...project,
          tracks: [{ ...source, mute: false, solo: false }],
          master: {
            ...project.master,
            volume_db: 0,
            compression: 0,
            ceiling: 0,
          },
        };
        stems[source.id] = await uploadRender(
          await studioAudio.render(stemProject),
        );
      }
      await post(`/projects/${project.id}/ableton`, {
        revision: project.revision,
        stems,
      });
      setNotice("Transfer queued. Waiting for confirmation from Ableton.");
    } catch (e) {
      setError((e as Error).message);
      setNotice("");
    } finally {
      setBusy(false);
    }
  }

  if (!active || !track || !section)
    return (
      <div className="boot">
        <strong>RDX</strong>
        <span>{error || "Opening studio..."}</span>
        {error && <button onClick={() => location.reload()}>Reconnect</button>}
      </div>
    );
  const totalBars = active.sections.reduce((sum, s) => sum + s.bars, 0);
  const hasFutureHistory = history?.entries.some(
    (e) => e.position > history.cursor,
  );
  const modelLabel =
    status?.model.training.state === "training"
      ? `Training ${status.model.training.step || 0}/${status.model.training.steps || 120}`
      : status?.model.trained
        ? "RDX local"
        : status?.model.downloaded
          ? "Local base model"
          : "Model not installed";
  let sectionOffset = 0;

  return (
    <div className="studio">
      <header className="topbar">
        <div className="brand">
          RDX<span>STUDIO</span>
        </div>
        <button
          className="project-switch"
          disabled={busy || thinking || recording || !!proposal}
          onClick={() => setModal("projects")}
        >
          <span>{active.name}</span>
          <ChevronDown size={14} />
        </button>
        <div className="transport">
          <IconButton
            title={playing ? "Stop playback" : "Play"}
            active={playing}
            disabled={busy}
            onClick={() => void togglePlay()}
          >
            {playing ? <Pause size={18} /> : <Play size={18} />}
          </IconButton>
          <IconButton
            title="Stop"
            disabled={busy && !playing}
            onClick={() => {
              studioAudio.stop();
              setPlaying(false);
            }}
          >
            <Square size={14} />
          </IconButton>
          <IconButton
            title="Loop selected section"
            disabled={busy || recording}
            active={loop}
            onClick={() => {
              studioAudio.stop();
              setLoop(!loop);
            }}
          >
            <Repeat2 size={17} />
          </IconButton>
          <span className="position">
            {String(Math.floor(beat / 4) + 1).padStart(2, "0")}.
            {Math.floor(beat % 4) + 1}
          </span>
        </div>
        <label className="tempo">
          <input
            key={active.tempo}
            aria-label="Tempo"
            disabled={busy || thinking || recording || !!proposal}
            type="number"
            min={40}
            max={240}
            defaultValue={active.tempo}
            onBlur={(e) => {
              if (Number(e.target.value) !== active.tempo)
                void action(
                  "project",
                  { tempo: Number(e.target.value) },
                  "Changed tempo",
                );
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter") e.currentTarget.blur();
            }}
          />
          <span>BPM</span>
        </label>
        <select
          aria-label="Project key"
          value={active.key}
          disabled={busy || !!proposal}
          onChange={(e) =>
            void action(
              "project",
              { key: e.target.value },
              "Changed project key",
            )
          }
        >
          {[
            "C",
            "C#",
            "D",
            "D#",
            "E",
            "F",
            "F#",
            "G",
            "G#",
            "A",
            "A#",
            "B",
          ].map((k) => (
            <option key={k}>{k}</option>
          ))}
        </select>
        <select
          aria-label="Scale"
          value={active.scale}
          disabled={busy || !!proposal}
          onChange={(e) =>
            void action(
              "project",
              { scale: e.target.value },
              "Changed project scale",
            )
          }
        >
          {SCALES.map((name) => (
            <option key={name} value={name}>
              {name[0].toUpperCase() + name.slice(1)}
            </option>
          ))}
        </select>
        <span className="push" />
        <span className="local-status">
          <i className={status?.model.downloaded ? "online" : ""} />
          {modelLabel}
        </span>
        <IconButton
          title="Project history"
          active={modal === "history"}
          onClick={() => setModal("history")}
        >
          <HistoryIcon size={17} />
        </IconButton>
        <IconButton
          title="Undo"
          disabled={
            busy ||
            thinking ||
            recording ||
            !!proposal ||
            !history ||
            history.cursor === 0
          }
          onClick={() => void undo("undo")}
        >
          <Undo2 size={17} />
        </IconButton>
        <IconButton
          title="Redo"
          disabled={
            busy || thinking || recording || !!proposal || !hasFutureHistory
          }
          onClick={() => void undo("redo")}
        >
          <Redo2 size={17} />
        </IconButton>
        <button
          className="export-button"
          disabled={busy || !!proposal || recording}
          onClick={() => setModal("export")}
        >
          <ArrowDownToLine size={15} />
          <span>Export</span>
        </button>
      </header>

      <nav className="rail">
        {[
          { id: "arrange", icon: Layers3, label: "Arrangement" },
          { id: "mix", icon: SlidersHorizontal, label: "Mixer" },
          { id: "sound", icon: Disc3, label: "Sound design" },
          { id: "record", icon: Mic, label: "Recordings" },
        ].map(({ id, icon: Icon, label }) => (
          <IconButton
            key={id}
            title={label}
            active={view === id}
            onClick={() => {
              setView(id);
              setChatOpen(false);
            }}
          >
            <Icon size={20} />
          </IconButton>
        ))}
        <span className="rail-divider" />
        <IconButton
          title="Co-producer"
          active={chatOpen}
          className="mobile-chat"
          onClick={() => setChatOpen(!chatOpen)}
        >
          <Sparkles size={19} />
        </IconButton>
        <span className="push" />
        <IconButton
          title="Ableton connection"
          active={status?.bridge.connected}
          onClick={() => setModal("ableton")}
        >
          <PlugZap size={19} />
        </IconButton>
      </nav>

      <main className={`workspace ${chatOpen ? "mobile-hidden" : ""}`}>
        <div className="workspace-heading">
          <div>
            <span className="eyebrow">
              {view === "arrange"
                ? "ARRANGEMENT"
                : view === "mix"
                  ? "MIXER"
                  : view === "sound"
                    ? "SOUND DESIGN"
                    : "RECORDINGS"}
            </span>
            <h1>
              {view === "mix"
                ? "Balance & space"
                : view === "sound"
                  ? track.name
                  : view === "record"
                    ? "Capture an idea"
                    : "Your session"}
            </h1>
          </div>
          <span className="session-meta">
            {active.tracks.length} tracks
            <span /> {totalBars} bars
            <span /> {Math.floor((totalBars * 4 * 60) / active.tempo / 60)}:
            {String(
              Math.round(((totalBars * 4 * 60) / active.tempo) % 60),
            ).padStart(2, "0")}
          </span>
          <div className="push" />
          <button
            className="text-button"
            disabled={busy || !!proposal}
            onClick={() => setModal("track")}
          >
            <Plus size={15} />
            Add track
          </button>
        </div>
        {(error || notice) && (
          <div
            className={`notice ${error ? "error" : ""}`}
            role={error ? "alert" : "status"}
          >
            <span>{error || notice}</span>
            <IconButton
              title="Dismiss message"
              onClick={() => {
                setError("");
                setNotice("");
              }}
            >
              <X size={13} />
            </IconButton>
          </div>
        )}
        {proposal && (
          <div className="audition-band">
            <span className="live-dot" />
            Alternative ready
            <div className="segmented">
              <button
                className={!audition ? "selected" : ""}
                onClick={() => {
                  studioAudio.stop();
                  setAudition(false);
                }}
              >
                Original
              </button>
              <button
                className={audition ? "selected" : ""}
                onClick={() => {
                  studioAudio.stop();
                  setAudition(true);
                }}
              >
                Alternative
              </button>
            </div>
            <span className="push" />
            <button onClick={() => void decide(false)}>Discard</button>
            <button className="primary" onClick={() => void decide(true)}>
              <Check size={14} />
              Keep
            </button>
          </div>
        )}

        {view === "arrange" && (
          <>
            <div className="arrangement-scroll">
              <div
                className="arrangement"
                style={{
                  gridTemplateColumns: `170px ${active.sections.map((s) => `${s.bars}fr`).join(" ")}`,
                  minWidth: Math.max(600, active.sections.length * 115 + 170),
                }}
              >
                <div className="track-column-heading">
                  TRACKS <span>{active.tracks.length}</span>
                </div>
                {active.sections.map((s) => {
                  const start = sectionOffset + 1;
                  sectionOffset += s.bars;
                  return (
                    <button
                      key={s.id}
                      className={`section-heading ${section.id === s.id ? "chosen" : ""}`}
                      onClick={() => setSelectedSection(s.id)}
                    >
                      <span>
                        {s.name}
                        <small>{String(start).padStart(2, "0")}</small>
                      </span>
                      <small>{s.bars} bars</small>
                    </button>
                  );
                })}
                {active.tracks.map((t) => {
                  const Icon =
                    roleIcons[t.role as keyof typeof roleIcons] || Music2;
                  return (
                    <div className="track-row" key={t.id}>
                      <div
                        className={`track-heading ${t.id === track.id ? "chosen" : ""}`}
                        style={{ borderLeftColor: t.color }}
                      >
                        <button
                          className="track-name"
                          onClick={() => setSelectedTrack(t.id)}
                        >
                          <Icon size={15} style={{ color: t.color }} />
                          <span>{t.name}</span>
                          {t.locked && <LockKeyhole size={11} />}
                        </button>
                        <div className="track-controls">
                          <button
                            title={`Mute ${t.name}`}
                            aria-label={`Mute ${t.name}`}
                            className={t.mute ? "enabled" : ""}
                            onClick={() =>
                              void action(
                                "mix",
                                { mute: !t.mute },
                                `Mute ${t.name}`,
                                t.id,
                              )
                            }
                            disabled={busy || !!proposal || t.locked}
                          >
                            M
                          </button>
                          <button
                            title={`Solo ${t.name}`}
                            aria-label={`Solo ${t.name}`}
                            className={t.solo ? "enabled" : ""}
                            onClick={() =>
                              void action(
                                "mix",
                                { solo: !t.solo },
                                `Solo ${t.name}`,
                                t.id,
                              )
                            }
                            disabled={busy || !!proposal || t.locked}
                          >
                            S
                          </button>
                          <Meter trackId={t.id} />
                        </div>
                      </div>
                      {active.sections.map((s) => {
                        const c = t.clips.find((c) => c.section_id === s.id);
                        return (
                          <button
                            aria-label={`${t.name}, ${s.name}${c ? ", clip" : ", empty"}`}
                            className={`clip-cell ${track.id === t.id && section.id === s.id ? "selected-cell" : ""}`}
                            key={s.id}
                            onClick={() => {
                              setSelectedTrack(t.id);
                              setSelectedSection(s.id);
                            }}
                          >
                            {c ? (
                              <div
                                className="clip"
                                style={{
                                  background: `${t.color}18`,
                                  borderColor: `${t.color}66`,
                                }}
                              >
                                <span style={{ color: t.color }}>{c.name}</span>
                                {c.audio_id ? (
                                  <Waveform assetId={c.audio_id} />
                                ) : (
                                  <MiniNotes clip={c} color={t.color} />
                                )}
                              </div>
                            ) : (
                              <span className="empty-cell">+</span>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  );
                })}
                <div className="timeline-footer">
                  <span>4/4</span>
                  <button
                    onClick={() => setModal("section")}
                    disabled={busy || !!proposal}
                  >
                    <Plus size={13} />
                    Section
                  </button>
                </div>
                <div
                  className="playhead"
                  style={{
                    left: `calc(170px + (100% - 170px) * ${beat / (totalBars * 4)})`,
                    opacity: playing ? 1 : 0,
                  }}
                />
              </div>
            </div>
            <div className="part-toolbar">
              <div className="part-title">
                <span style={{ background: track.color }} />
                {track.name}
                <span className="muted">/</span>
                {section.name}
              </div>
              <span className="push" />
              <IconButton
                title={track.locked ? "Unprotect track" : "Protect track"}
                active={track.locked}
                disabled={busy || !!proposal}
                onClick={() =>
                  void action(
                    "protect",
                    { locked: !track.locked },
                    `${track.locked ? "Unprotected" : "Protected"} ${track.name}`,
                  )
                }
              >
                {track.locked ? (
                  <LockKeyhole size={15} />
                ) : (
                  <UnlockKeyhole size={15} />
                )}
              </IconButton>
              <IconButton
                title="Part settings"
                disabled={busy || !!proposal}
                onClick={() => setModal("part")}
              >
                <MoreHorizontal size={16} />
              </IconButton>
              <IconButton
                title="Duplicate section"
                disabled={locked}
                onClick={() =>
                  void action(
                    "arrange",
                    { operation: "duplicate" },
                    `Repeated ${section.name}`,
                  )
                }
              >
                <Copy size={15} />
              </IconButton>
              <button
                className="text-button"
                disabled={locked || track.role === "audio"}
                onClick={() => {
                  void action(
                    track.role === "drums" ? "drums" : "compose",
                    { density: 0.65, variation },
                    `New ${track.name} phrase`,
                  );
                  setVariation(variation + 1);
                }}
              >
                <Sparkles size={14} />
                {clip ? "New variation" : "Create phrase"}
              </button>
            </div>
            {track.role === "audio" ? (
              <div className="audio-editor">
                {clip?.audio_id ? (
                  <>
                    <Waveform assetId={clip.audio_id} />
                    <Slider
                      label="Audio start"
                      value={clip.audio_offset}
                      min={0}
                      max={60}
                      step={0.05}
                      unit=" s"
                      onCommit={(value) =>
                        void action(
                          "notes",
                          { operation: "audio_offset", audio_offset: value },
                          "Trimmed audio start",
                        )
                      }
                      disabled={locked}
                    />
                  </>
                ) : (
                  <span>No recording in this section</span>
                )}
              </div>
            ) : (
              <PianoRoll
                disabled={locked || thinking || recording}
                track={track}
                section={section}
                clip={clip}
                onChange={(notes) =>
                  void action(
                    "notes",
                    { operation: "replace", notes },
                    `Edited ${track.name} notes`,
                  )
                }
              />
            )}
          </>
        )}

        {view === "sound" && (
          <div className="sound-view">
            <div className="track-tabs">
              {active.tracks.map((t) => (
                <button
                  key={t.id}
                  className={track.id === t.id ? "selected" : ""}
                  onClick={() => setSelectedTrack(t.id)}
                >
                  <i style={{ background: t.color }} />
                  {t.name}
                </button>
              ))}
            </div>
            <div className="sound-title">
              <div className="sound-icon" style={{ color: track.color }}>
                <AudioLines size={38} />
              </div>
              <div>
                <h2>{track.name}</h2>
                <span className="muted">
                  {track.role === "drums"
                    ? "Drum kit"
                    : track.role === "audio"
                      ? "Recorded audio"
                      : "Instrument"}
                </span>
              </div>
              <select
                aria-label="Instrument preset"
                value={track.sound.preset}
                disabled={locked || ["drums", "audio"].includes(track.role)}
                onChange={(e) =>
                  void action(
                    "sound",
                    { preset: e.target.value },
                    `Changed ${track.name} instrument`,
                  )
                }
              >
                {MELODIC_PRESETS.map((p) => (
                  <option key={p} value={p}>
                    {PRESET_LABELS[p]}
                  </option>
                ))}
                {["drumkit", "audio"].includes(track.sound.preset) && (
                  <option value={track.sound.preset}>
                    {track.sound.preset.toUpperCase()}
                  </option>
                )}
              </select>
            </div>
            <div className="sound-patches">
              <label className="parameter">
                <span>sound</span>
                <select
                  aria-label="Patch"
                  value=""
                  disabled={locked || ["drums", "audio"].includes(track.role)}
                  onChange={(e) =>
                    e.target.value &&
                    void action(
                      "sound",
                      { patch: e.target.value },
                      `${track.name}: ${e.target.value.replace("_", " ")}`,
                    )
                  }
                >
                  <option value="">choose a sound...</option>
                  {PATCHES.filter((p) => p.roles.includes(track.role)).map(
                    (p) => (
                      <option key={p.name} value={p.name}>
                        {p.name.replace("_", " ")}
                      </option>
                    ),
                  )}
                </select>
              </label>
              <label className="parameter">
                <span>wave</span>
                <select
                  aria-label="Waveform"
                  value={track.sound.wave}
                  disabled={locked || ["drums", "audio"].includes(track.role)}
                  onChange={(e) =>
                    void action(
                      "sound",
                      { wave: e.target.value },
                      `${track.name} waveform`,
                    )
                  }
                >
                  {WAVES.map((w) => (
                    <option key={w} value={w}>
                      {w}
                    </option>
                  ))}
                </select>
              </label>
              <label className="parameter">
                <span>LFO to</span>
                <select
                  aria-label="LFO destination"
                  value={track.sound.lfo_target}
                  disabled={locked || ["drums", "audio"].includes(track.role)}
                  onChange={(e) =>
                    void action(
                      "sound",
                      { lfo_target: e.target.value },
                      `${track.name} LFO`,
                    )
                  }
                >
                  {LFO_TARGETS.map((target) => (
                    <option key={target} value={target}>
                      {target}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <div className="sound-controls">
              {[
                {
                  name: "Tone",
                  controls: [
                    ["cutoff", "Filter cutoff", 60, 20000, 10, " Hz"],
                    ["resonance", "Resonance", 0.1, 15, 0.1, ""],
                    ["drive", "Drive", 0, 0.8, 0.01, ""],
                  ],
                },
                {
                  name: "Envelope",
                  controls: [
                    ["attack", "Attack", 0.001, 4, 0.001, " s"],
                    ["decay", "Decay", 0.005, 4, 0.005, " s"],
                    ["sustain", "Sustain", 0, 1, 0.01, ""],
                    ["release", "Release", 0.01, 8, 0.01, " s"],
                  ],
                },
                {
                  name: "Oscillator",
                  controls: [
                    ["unison", "Voices", 1, 7, 1, ""],
                    ["spread", "Detune", 0, 100, 1, " c"],
                    ["sub", "Sub", 0, 1, 0.01, ""],
                    ["octave", "Octave", -2, 2, 1, ""],
                    ["crush", "Bit crush", 0, 1, 0.01, ""],
                  ],
                },
                {
                  name: "Filter envelope",
                  controls: [
                    ["filter_env", "Amount", -1, 1, 0.01, ""],
                    ["filter_decay", "Decay", 0.01, 4, 0.01, " s"],
                  ],
                },
                {
                  name: "Space",
                  controls: [
                    ["reverb", "Reverb", 0, 1, 0.01, ""],
                    ["delay", "Delay", 0, 0.8, 0.01, ""],
                  ],
                },
                {
                  name: "Equalizer",
                  controls: [
                    ["low", "Low", -24, 12, 0.5, " dB"],
                    ["mid", "Mid", -24, 12, 0.5, " dB"],
                    ["high", "High", -24, 12, 0.5, " dB"],
                  ],
                },
                {
                  name: "Motion",
                  controls: [
                    ["chorus", "Chorus", 0, 1, 0.01, ""],
                    ["flanger", "Flanger", 0, 1, 0.01, ""],
                    ["phaser", "Phaser", 0, 1, 0.01, ""],
                    ["autopan", "Auto-pan", 0, 1, 0.01, ""],
                    ["motion_rate", "Rate", 0.02, 8, 0.01, " Hz"],
                    ["width", "Width", 0, 1, 0.01, ""],
                    ["glide", "Glide", 0, 0.5, 0.005, " s"],
                  ],
                },
                {
                  name: "LFO",
                  controls: [
                    ["lfo_depth", "Depth", 0, 1, 0.01, ""],
                    ["lfo_rate", "Rate", 0.05, 20, 0.05, " Hz"],
                  ],
                },
              ].map((group) => (
                <section className="sound-group" key={group.name}>
                  <h3>{group.name}</h3>
                  {group.controls.map(
                    ([field, label, min, max, step, unit]) => (
                      <Slider
                        key={field}
                        label={label as string}
                        value={Number(track.sound[field as keyof Sound])}
                        min={min as number}
                        max={max as number}
                        step={step as number}
                        unit={unit as string}
                        disabled={locked}
                        onCommit={(value) =>
                          void action(
                            "sound",
                            { [field]: value },
                            `Adjusted ${label}`,
                          )
                        }
                      />
                    ),
                  )}
                </section>
              ))}
            </div>
            <section className="automation-controls">
              <h3>
                Automation <span className="muted">/ {section.name}</span>
              </h3>
              <div className="automation-presets">
                <button
                  disabled={locked}
                  onClick={() =>
                    void action(
                      "automation",
                      {
                        parameter: "cutoff",
                        points: [
                          [0, 400],
                          [section.bars * 4, 14000],
                        ],
                      },
                      "Added filter rise",
                    )
                  }
                >
                  <ArrowUp size={15} />
                  Filter rise
                </button>
                <button
                  disabled={locked}
                  onClick={() =>
                    void action(
                      "automation",
                      {
                        parameter: "volume_db",
                        points: [
                          [0, -36],
                          [section.bars * 4, track.volume_db],
                        ],
                      },
                      "Added fade in",
                    )
                  }
                >
                  <Volume2 size={15} />
                  Fade in
                </button>
                <button
                  disabled={locked}
                  onClick={() =>
                    void action(
                      "automation",
                      {
                        parameter: "volume_db",
                        points: [
                          [0, track.volume_db],
                          [section.bars * 4, -60],
                        ],
                      },
                      "Added fade out",
                    )
                  }
                >
                  <Volume2 size={15} />
                  Fade out
                </button>
              </div>
              {track.automation
                .filter((a) => a.section_id === section.id)
                .map((lane) => (
                  <div className="automation-line" key={lane.parameter}>
                    <Activity size={15} />
                    {lane.parameter}
                    <span className="push" />
                    {lane.points.map((p) => p[1]).join(" → ")}
                  </div>
                ))}
            </section>
          </div>
        )}

        {view === "mix" && (
          <>
            <div className="mixer">
              {active.tracks.map((t) => (
                <section
                  className={`channel-strip ${track.id === t.id ? "chosen" : ""}`}
                  key={t.id}
                  style={{ borderTopColor: t.color }}
                >
                  <button
                    className="channel-name"
                    onClick={() => setSelectedTrack(t.id)}
                  >
                    {t.name}
                  </button>
                  <div className="channel-pan">
                    <Slider
                      label={`${t.name} pan`}
                      value={t.pan}
                      min={-1}
                      max={1}
                      step={0.01}
                      disabled={busy || !!proposal || t.locked}
                      onCommit={(value) =>
                        void action(
                          "mix",
                          { pan: value },
                          `${t.name} pan`,
                          t.id,
                        )
                      }
                    />
                  </div>
                  <div className="fader-area">
                    <input
                      aria-label={`${t.name} volume`}
                      type="range"
                      min={-48}
                      max={6}
                      step={0.5}
                      defaultValue={t.volume_db}
                      key={`${t.volume_db}-${t.id}`}
                      disabled={busy || !!proposal || t.locked}
                      onPointerUp={(e) =>
                        void action(
                          "mix",
                          { volume_db: Number(e.currentTarget.value) },
                          `${t.name} level`,
                          t.id,
                        )
                      }
                      onKeyUp={(e) =>
                        void action(
                          "mix",
                          { volume_db: Number(e.currentTarget.value) },
                          `${t.name} level`,
                          t.id,
                        )
                      }
                    />
                    <Meter trackId={t.id} vertical />
                  </div>
                  <output className="fader-value">
                    {t.volume_db.toFixed(1)}
                    <small>dB</small>
                  </output>
                  <div className="channel-buttons">
                    <button
                      className={t.mute ? "enabled" : ""}
                      disabled={busy || !!proposal || t.locked}
                      onClick={() =>
                        void action(
                          "mix",
                          { mute: !t.mute },
                          `${t.name} mute`,
                          t.id,
                        )
                      }
                    >
                      M
                    </button>
                    <button
                      className={t.solo ? "enabled" : ""}
                      disabled={busy || !!proposal || t.locked}
                      onClick={() =>
                        void action(
                          "mix",
                          { solo: !t.solo },
                          `${t.name} solo`,
                          t.id,
                        )
                      }
                    >
                      S
                    </button>
                  </div>
                  <Slider
                    label={`${t.name} reverb`}
                    value={t.sound.reverb}
                    min={0}
                    max={1}
                    step={0.01}
                    disabled={busy || !!proposal || t.locked}
                    onCommit={(value) =>
                      void action(
                        "sound",
                        { reverb: value },
                        `${t.name} space`,
                        t.id,
                      )
                    }
                  />
                  <div className="channel-duck">
                    <label className="parameter">
                      <span>
                        duck to
                        {t.sidechain && (
                          <output>{duckLabel(t.sidechain.amount)}</output>
                        )}
                      </span>
                      <select
                        aria-label={`${t.name} ducking source`}
                        value={t.sidechain?.source ?? ""}
                        disabled={busy || !!proposal || t.locked}
                        onChange={(e) =>
                          void action(
                            "sidechain",
                            e.target.value
                              ? { source: e.target.value, shape: "pump" }
                              : { operation: "remove" },
                            e.target.value
                              ? `${t.name} ducks to ${active.tracks.find((o) => o.id === e.target.value)?.name}`
                              : `${t.name} ducking off`,
                            t.id,
                          )
                        }
                      >
                        <option value="">nothing</option>
                        {active.tracks
                          .filter((o) => o.id !== t.id && o.role !== "audio")
                          .map((o) => (
                            <option key={o.id} value={o.id}>
                              {o.name}
                            </option>
                          ))}
                      </select>
                    </label>
                    {t.sidechain && (
                      <Slider
                        label={`${t.name} ducking depth`}
                        value={t.sidechain.amount}
                        min={0}
                        max={1}
                        step={0.01}
                        disabled={busy || !!proposal || t.locked}
                        onCommit={(value) =>
                          void action(
                            "sidechain",
                            { amount: value },
                            `${t.name} ducking depth`,
                            t.id,
                          )
                        }
                      />
                    )}
                  </div>
                </section>
              ))}
              <section className="channel-strip master-strip">
                <strong>MASTER</strong>
                <div className="fader-area">
                  <input
                    aria-label="Master volume"
                    disabled={busy || !!proposal}
                    type="range"
                    min={-30}
                    max={0}
                    step={0.5}
                    defaultValue={active.master.volume_db}
                    key={active.master.volume_db}
                    onKeyUp={(e) =>
                      void action(
                        "master",
                        { volume_db: Number(e.currentTarget.value) },
                        "Master level",
                      )
                    }
                    onPointerUp={(e) =>
                      void action(
                        "master",
                        { volume_db: Number(e.currentTarget.value) },
                        "Master level",
                      )
                    }
                  />
                  <Meter trackId="master" vertical />
                </div>
                <output className="fader-value">
                  {active.master.volume_db.toFixed(1)}
                  <small>dB</small>
                </output>
                <Slider
                  label="Limiter ceiling"
                  disabled={busy || !!proposal}
                  value={active.master.ceiling}
                  min={-12}
                  max={0}
                  step={0.5}
                  unit=" dB"
                  onCommit={(value) =>
                    void action("master", { ceiling: value }, "Limiter ceiling")
                  }
                />
                <Slider
                  label="Compression"
                  disabled={busy || !!proposal}
                  value={active.master.compression}
                  min={-60}
                  max={0}
                  step={1}
                  unit=" dB"
                  onCommit={(value) =>
                    void action(
                      "master",
                      { compression: value },
                      "Master compression",
                    )
                  }
                />
              </section>
            </div>
            <section className="mix-report">
              <header>
                <div>
                  <h3>Mix analysis</h3>
                  <p>
                    RDX renders every track and measures it. It will not name a
                    problem it has not heard.
                  </p>
                </div>
                <button
                  className="primary"
                  disabled={busy || !!proposal}
                  onClick={() => void analyseMix()}
                >
                  {mixReport?.measured && mixReport.revision === active.revision
                    ? "Measure again"
                    : "Analyse the mix"}
                </button>
              </header>
              {mixReport?.measured && mixReport.revision === active.revision ? (
                <>
                  <div className="mix-numbers">
                    <span>
                      <output>{mixReport.mix!.loudness_lufs.toFixed(1)}</output>
                      LUFS
                    </span>
                    <span>
                      <output>{mixReport.mix!.crest_db.toFixed(1)}</output>
                      dB dynamic range
                    </span>
                    {Object.entries(mixReport.mix!.bands).map(
                      ([band, share]) => (
                        <span key={band}>
                          <output>{Math.round(share * 100)}%</output>
                          {band}
                        </span>
                      ),
                    )}
                  </div>
                  {mixReport.findings?.length ? (
                    <ul className="mix-findings">
                      {mixReport.findings.map((finding) => (
                        <li key={finding.problem + finding.headline}>
                          <div>
                            <strong>{finding.headline}</strong>
                            <p>{finding.detail}</p>
                          </div>
                          <button
                            disabled={busy || !!proposal}
                            onClick={() =>
                              void edit(finding.actions, finding.headline)
                            }
                          >
                            Fix
                          </button>
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="mix-clear">
                      Nothing in this mix measures as a problem.
                    </p>
                  )}
                </>
              ) : (
                <p className="mix-clear">
                  {mixReport?.stale_revision != null
                    ? "The arrangement has changed since the last measurement. Analyse it again."
                    : "Not measured yet."}
                </p>
              )}
            </section>
          </>
        )}

        {view === "record" && (
          <div className="record-view">
            <div className="record-console">
              <div className={`record-symbol ${recording ? "recording" : ""}`}>
                <AudioLines size={54} />
              </div>
              <h2>
                {recording
                  ? "Recording"
                  : recordMode === "hum"
                    ? "Melody"
                    : recordMode === "rhythm"
                      ? "Rhythm"
                      : "Audio"}
              </h2>
              <span className="record-clock">
                {String(Math.floor(recordSeconds / 60)).padStart(2, "0")}:
                {String(Math.floor(recordSeconds % 60)).padStart(2, "0")}
              </span>
              <div className="segmented">
                <button
                  className={recordMode === "hum" ? "selected" : ""}
                  disabled={recording}
                  onClick={() => setRecordMode("hum")}
                >
                  Hum
                </button>
                <button
                  className={recordMode === "rhythm" ? "selected" : ""}
                  disabled={recording}
                  onClick={() => {
                    setRecordMode("rhythm");
                    const drums = active.tracks.find((t) => t.role === "drums");
                    if (drums) setSelectedTrack(drums.id);
                  }}
                >
                  Rhythm
                </button>
                <button
                  className={recordMode === "audio" ? "selected" : ""}
                  disabled={recording}
                  onClick={() => setRecordMode("audio")}
                >
                  Audio
                </button>
              </div>
              <div className="record-target">
                <select
                  aria-label="Recording target"
                  value={track.id}
                  disabled={recording}
                  onChange={(e) => setSelectedTrack(e.target.value)}
                >
                  {active.tracks.map((t) => (
                    <option value={t.id} key={t.id}>
                      {t.name}
                    </option>
                  ))}
                </select>
                <select
                  aria-label="Recording section"
                  value={section.id}
                  disabled={recording}
                  onChange={(e) => setSelectedSection(e.target.value)}
                >
                  {active.sections.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </select>
              </div>
              <button
                className={`record-button ${recording ? "recording" : ""}`}
                disabled={busy || !!proposal}
                onClick={() => void toggleRecord()}
              >
                {recording ? <Square size={20} /> : <Mic size={22} />}
                <span>{recording ? "Finish recording" : "Record"}</span>
              </button>
              <button
                className="text-button"
                disabled={busy || recording || !!proposal}
                onClick={() => uploadRef.current?.click()}
              >
                <FolderOpen size={16} />
                Import audio or MIDI
              </button>
            </div>
            <div className="recording-list">
              <h3>In this project</h3>
              {active.tracks.flatMap((t) =>
                t.clips
                  .filter((c) => c.audio_id)
                  .map((c) => (
                    <div className="recording-item" key={c.id}>
                      <Mic size={16} />
                      <span>{c.name}</span>
                      <Waveform assetId={c.audio_id!} />
                      <button
                        onClick={() => {
                          setSelectedTrack(t.id);
                          setSelectedSection(c.section_id);
                          setView("arrange");
                        }}
                      >
                        Open
                      </button>
                    </div>
                  )),
              )}
              {!active.tracks.some((t) => t.clips.some((c) => c.audio_id)) && (
                <span className="muted">No audio recordings</span>
              )}
            </div>
          </div>
        )}
        <input
          ref={uploadRef}
          type="file"
          accept="audio/*,.mid,.midi"
          hidden
          onChange={(e) => {
            if (e.target.files?.[0]) void upload(e.target.files[0]);
          }}
        />
        <footer className="workspace-footer">
          <span>
            <i className="online-dot" />
            {busy
              ? "Working..."
              : proposal
                ? "Unsaved alternative"
                : "Saved locally"}
          </span>
          <span className="push" />
          <button onClick={() => setModal("ableton")}>
            <PlugZap size={13} />
            {status?.bridge.connected
              ? "Ableton connected"
              : "Ableton disconnected"}
          </button>
          <span>RDX 0.1</span>
        </footer>
      </main>

      <aside className={`coproducer ${chatOpen ? "mobile-open" : ""}`}>
        <div className="coproducer-heading">
          <Sparkles size={18} />
          <h2>Co-producer</h2>
          <span className="push" />
          <span className="offline-pill">
            <i />
            LOCAL
          </span>
        </div>
        <div className="target-context">
          <span style={{ background: track.color }} />
          {track.name}
          <span className="muted">/</span>
          {section.name}
          {track.locked && <LockKeyhole size={12} />}
        </div>
        <div className="messages">
          {!messages.length && (
            <div className="conversation-start">
              <div className="rdx-mark">
                <AudioLines size={26} />
              </div>
              <h3>What do you hear next?</h3>
              <div className="musical-requests">
                {[
                  "Write a different lead melody",
                  "Add more space to the lead",
                  "Repeat the main section",
                  "Lower the bass by 2 dB",
                ].map((text) => (
                  <button
                    key={text}
                    disabled={thinking || !!proposal}
                    onClick={() => void ask(text)}
                  >
                    {text}
                    <ArrowUp size={12} />
                  </button>
                ))}
              </div>
            </div>
          )}
          {messages.map((message, i) => (
            <div key={i} className={`message ${message.role}`}>
              <span className="message-author">
                {message.role === "user" ? "YOU" : "RDX"}
              </span>
              <p>{message.content}</p>
            </div>
          ))}
          {thinking && (
            <div className="message assistant thinking">
              <span />
              <span />
              <span />
            </div>
          )}
          {proposal && (
            <div className="proposal-details">
              <span>
                {proposal.plan.actions.length} proposed{" "}
                {proposal.plan.actions.length === 1 ? "change" : "changes"}
              </span>
              <input
                aria-label="Feedback on alternative"
                placeholder="What feels right or wrong?"
                value={feedback}
                onChange={(e) => setFeedback(e.target.value)}
              />
              <div>
                <button disabled={busy} onClick={() => void decide(false)}>
                  <X size={14} />
                  Discard
                </button>
                <button
                  className="primary"
                  disabled={busy}
                  onClick={() => void decide(true)}
                >
                  <Check size={14} />
                  Keep
                </button>
              </div>
            </div>
          )}
          <div ref={messageEnd} />
        </div>
        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            void ask();
          }}
        >
          <textarea
            aria-label="Musical direction"
            placeholder="Describe the change you hear..."
            value={prompt}
            disabled={thinking || !!proposal}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void ask();
              }
            }}
          />
          <div>
            <IconButton
              title="Record a musical idea"
              onClick={() => {
                setView("record");
                setChatOpen(false);
              }}
            >
              <Mic size={17} />
            </IconButton>
            <span>{thinking ? "Preparing your edit..." : modelLabel}</span>
            <button
              className="send-button"
              aria-label="Send musical direction"
              disabled={!prompt.trim() || thinking || !!proposal}
            >
              <ArrowUp size={17} />
            </button>
          </div>
        </form>
      </aside>

      {modal && (
        <div className="modal-backdrop" onClick={() => setModal(null)}>
          <section
            className={`modal ${modal === "history" ? "history-modal" : ""}`}
            role="dialog"
            aria-modal="true"
            aria-label={modal}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-heading">
              <h2>
                {modal === "part"
                  ? "Part settings"
                  : modal === "projects"
                    ? "Projects"
                    : modal === "track"
                      ? "Add track"
                      : modal === "section"
                        ? "Add section"
                        : modal === "history"
                          ? "Project history"
                          : modal === "ableton"
                            ? "Ableton Live"
                            : "Export"}
              </h2>
              <IconButton title="Close dialog" onClick={() => setModal(null)}>
                <X size={18} />
              </IconButton>
            </div>
            {modal === "projects" && (
              <>
                <div className="project-list">
                  {projectList.map((p) => (
                    <button
                      key={p.id}
                      onClick={() => {
                        void load(p.id);
                        setModal(null);
                      }}
                    >
                      <Music2 size={16} />
                      {p.name}
                      {p.id === project?.id && <Check size={15} />}
                    </button>
                  ))}
                </div>
                <label>
                  Project name
                  <input
                    value={newName}
                    onChange={(e) => setNewName(e.target.value)}
                  />
                </label>
                <button
                  className="primary"
                  disabled={busy || !newName.trim()}
                  onClick={() => void newProject()}
                >
                  <Plus size={15} />
                  New project
                </button>
                <button
                  className="text-button"
                  disabled={busy}
                  onClick={() => archiveRef.current?.click()}
                >
                  <FolderOpen size={15} />
                  Open project archive
                </button>
                <input
                  ref={archiveRef}
                  type="file"
                  accept=".zip"
                  hidden
                  onChange={(e) => {
                    if (e.target.files?.[0])
                      void importProject(e.target.files[0]);
                  }}
                />
              </>
            )}
            {modal === "part" && (
              <div className="part-settings">
                <h3>Track</h3>
                <label>
                  Name
                  <input
                    aria-label="Track name"
                    defaultValue={track.name}
                    maxLength={60}
                    disabled={locked}
                    onBlur={(e) => {
                      if (
                        e.target.value.trim() &&
                        e.target.value !== track.name
                      )
                        void action(
                          "mix",
                          { name: e.target.value },
                          "Renamed track",
                        );
                    }}
                  />
                </label>
                <div>
                  <button
                    disabled={locked}
                    onClick={async () => {
                      const updated = await action(
                        "duplicate_track",
                        {},
                        "Duplicated track",
                      );
                      if (updated) setSelectedTrack(updated.tracks.at(-1)!.id);
                      setModal(null);
                    }}
                  >
                    <Copy size={14} />
                    Duplicate track
                  </button>
                  <button
                    disabled={locked || active.tracks.length === 1}
                    onClick={async () => {
                      await action("remove_track", {}, `Removed ${track.name}`);
                      setModal(null);
                    }}
                  >
                    <Trash2 size={14} />
                    Remove track
                  </button>
                </div>
                <h3>Section</h3>
                <label>
                  Name
                  <input
                    aria-label="Section name"
                    defaultValue={section.name}
                    maxLength={60}
                    disabled={busy || !!proposal}
                    onBlur={(e) => {
                      if (
                        e.target.value.trim() &&
                        e.target.value !== section.name
                      )
                        void action(
                          "arrange",
                          { operation: "update", name: e.target.value },
                          "Renamed section",
                        );
                    }}
                  />
                </label>
                <label>
                  Bars
                  <input
                    aria-label="Section bars"
                    type="number"
                    defaultValue={section.bars}
                    min={1}
                    max={64}
                    disabled={busy || !!proposal}
                    onBlur={(e) => {
                      if (Number(e.target.value) !== section.bars)
                        void action(
                          "arrange",
                          { operation: "update", bars: Number(e.target.value) },
                          "Resized section",
                        );
                    }}
                  />
                </label>
                <div>
                  <button
                    disabled={busy || active.sections.indexOf(section) === 0}
                    onClick={() =>
                      void action(
                        "arrange",
                        {
                          operation: "move",
                          index: active.sections.indexOf(section) - 1,
                        },
                        "Moved section earlier",
                      )
                    }
                  >
                    <Undo2 size={14} />
                    Earlier
                  </button>
                  <button
                    disabled={
                      busy ||
                      active.sections.indexOf(section) ===
                        active.sections.length - 1
                    }
                    onClick={() =>
                      void action(
                        "arrange",
                        {
                          operation: "move",
                          index: active.sections.indexOf(section) + 1,
                        },
                        "Moved section later",
                      )
                    }
                  >
                    <Redo2 size={14} />
                    Later
                  </button>
                  <button
                    disabled={busy || active.sections.length === 1}
                    onClick={async () => {
                      await action(
                        "arrange",
                        { operation: "remove" },
                        `Removed ${section.name}`,
                      );
                      setModal(null);
                    }}
                  >
                    <Trash2 size={14} />
                    Remove section
                  </button>
                </div>
              </div>
            )}
            {modal === "track" && (
              <div className="role-list">
                {Object.entries(roleIcons).map(([role, Icon]) => (
                  <button
                    key={role}
                    disabled={busy}
                    onClick={async () => {
                      const updated = await action(
                        "add_track",
                        { role },
                        `Added ${role} track`,
                      );
                      if (updated) setSelectedTrack(updated.tracks.at(-1)!.id);
                      setModal(null);
                    }}
                  >
                    <Icon size={22} />
                    {role}
                  </button>
                ))}
              </div>
            )}
            {modal === "section" && (
              <div className="role-list">
                {["Intro", "Build", "Main", "Breakdown", "Outro"].map(
                  (name) => (
                    <button
                      key={name}
                      disabled={busy}
                      onClick={async () => {
                        const updated = await action(
                          "arrange",
                          { operation: "add", name, bars: 8 },
                          `Added ${name}`,
                        );
                        if (updated)
                          setSelectedSection(updated.sections.at(-1)!.id);
                        setModal(null);
                      }}
                    >
                      <Layers3 size={20} />
                      {name}
                    </button>
                  ),
                )}
              </div>
            )}
            {modal === "history" && (
              <div className="history-list">
                {history?.entries.map((entry) => (
                  <div
                    key={entry.position}
                    className={
                      entry.position === history.cursor ? "current" : ""
                    }
                  >
                    <span>
                      {entry.position === history.cursor ? (
                        <Circle size={10} />
                      ) : (
                        <Check size={12} />
                      )}
                    </span>
                    <p>{entry.label}</p>
                    <time>
                      {new Date(entry.created * 1000).toLocaleTimeString([], {
                        hour: "2-digit",
                        minute: "2-digit",
                      })}
                    </time>
                  </div>
                ))}
              </div>
            )}
            {modal === "export" && (
              <div className="export-options">
                <button disabled={busy} onClick={() => void exportWav()}>
                  <Waves size={22} />
                  <span>
                    WAV audio<small>Full mix, 44.1 kHz / 16-bit</small>
                  </span>
                  <ArrowDownToLine size={16} />
                </button>
                <a href={`/api/projects/${active.id}/export/midi`} download>
                  <Piano size={22} />
                  <span>
                    MIDI arrangement
                    <small>All MIDI parts, tempo and sections</small>
                  </span>
                  <ArrowDownToLine size={16} />
                </a>
                <a href={`/api/projects/${active.id}/export/project`} download>
                  <FolderOpen size={22} />
                  <span>
                    Project archive
                    <small>RDX project, audio sources and MIDI</small>
                  </span>
                  <ArrowDownToLine size={16} />
                </a>
              </div>
            )}
            {modal === "ableton" && (
              <div className="connection-panel">
                <div
                  className={`connection-state ${status?.bridge.connected ? "connected" : ""}`}
                >
                  <PlugZap size={26} />
                  <span>
                    {status?.bridge.connected ? "Connected" : "Not connected"}
                  </span>
                </div>
                <p>
                  {status?.bridge.connected
                    ? "Transfer rendered audio with editable MIDI tracks. Each transfer adds new tracks to the open Set."
                    : "The RDX bridge device needs to be open in your Live Set."}
                </p>
                <a className="text-button" href="/api/bridge/device" download>
                  <ArrowDownToLine size={15} />
                  RDX bridge device
                </a>
                <button
                  className="primary"
                  disabled={
                    !status?.bridge.connected ||
                    status.bridge.pending ||
                    busy ||
                    !!proposal
                  }
                  onClick={() => {
                    setModal(null);
                    void sendAbleton();
                  }}
                >
                  <Send size={15} />
                  Send audio + MIDI
                </button>
                {status?.bridge.result && <p>{status.bridge.result.message}</p>}
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
