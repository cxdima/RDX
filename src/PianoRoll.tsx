import { useEffect, useRef, useState } from "react";
import { MousePointer2, Pencil, Eraser } from "lucide-react";
import type { Clip, Note, Section, Track } from "./types";

const names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
export const noteName = (pitch: number) =>
  `${names[pitch % 12]}${Math.floor(pitch / 12) - 1}`;

export default function PianoRoll({
  track,
  section,
  clip,
  onChange,
  disabled = false,
}: {
  track: Track;
  section: Section;
  clip?: Clip;
  onChange: (notes: Note[]) => void;
  disabled?: boolean;
}) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const [tool, setTool] = useState("select");
  const [selected, setSelected] = useState<string | null>(null);
  const [length, setLength] = useState(0.5);
  const [drag, setDrag] = useState<{
    id: string;
    pitch: number;
    start: number;
  } | null>(null);
  const notes = clip?.notes || [];
  const low =
    track.role === "drums"
      ? 34
      : Math.max(12, Math.min(48, ...notes.map((n) => n.pitch)) - 2);
  const high =
    track.role === "drums"
      ? 48
      : Math.min(108, Math.max(low + 24, ...notes.map((n) => n.pitch)) + 2);
  const rows = high - low + 1;
  const selectedNote = notes.find((n) => n.id === selected);
  useEffect(() => {
    setSelected(null);
    setDrag(null);
  }, [clip?.id]);
  useEffect(() => {
    const element = canvas.current;
    if (!element) return;
    const draw = () => {
      const width = element.clientWidth,
        height = element.clientHeight,
        dpr = devicePixelRatio;
      element.width = width * dpr;
      element.height = height * dpr;
      const ctx = element.getContext("2d")!;
      ctx.scale(dpr, dpr);
      ctx.fillStyle = "#17191c";
      ctx.fillRect(0, 0, width, height);
      const gutter = 42,
        top = 24,
        cellH = (height - top) / rows,
        beatW = (width - gutter) / (section.bars * 4);
      ctx.font = "10px ui-monospace, monospace";
      for (let p = low; p <= high; p++) {
        const y = top + (high - p) * cellH;
        ctx.fillStyle = [1, 3, 6, 8, 10].includes(p % 12)
          ? "#121416"
          : "#1b1d20";
        ctx.fillRect(0, y, width, cellH);
        ctx.strokeStyle = "#25272b";
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
        ctx.fillStyle = "#777d82";
        if (
          p % 12 === 0 ||
          (track.role === "drums" && [36, 38, 42, 46].includes(p))
        )
          ctx.fillText(
            track.role === "drums"
              ? { 36: "Kick", 38: "Snare", 42: "Hat", 46: "Open" }[p] || ""
              : noteName(p),
            4,
            y + cellH - 2,
          );
      }
      for (let b = 0; b <= section.bars * 4; b++) {
        const x = gutter + b * beatW;
        ctx.strokeStyle = b % 4 === 0 ? "#393c40" : "#24272a";
        ctx.beginPath();
        ctx.moveTo(x, top);
        ctx.lineTo(x, height);
        ctx.stroke();
        if (b % 4 === 0) {
          ctx.fillStyle = "#858b90";
          ctx.fillText(String(b / 4 + 1), x + 5, 15);
        }
      }
      for (const note of notes) {
        const n = drag?.id === note.id ? { ...note, ...drag } : note;
        ctx.fillStyle = n.id === selected ? "#e4f5cc" : track.color;
        ctx.globalAlpha = 0.4 + n.velocity / 215;
        ctx.fillRect(
          gutter + n.start * beatW + 1,
          top + (high - n.pitch) * cellH + 1,
          Math.max(3, n.duration * beatW - 2),
          Math.max(2, cellH - 2),
        );
      }
      ctx.globalAlpha = 1;
    };
    const observer = new ResizeObserver(draw);
    observer.observe(element);
    draw();
    return () => observer.disconnect();
  }, [
    notes,
    high,
    low,
    rows,
    track.color,
    track.role,
    section.bars,
    selected,
    drag,
  ]);
  function position(event: React.PointerEvent<HTMLCanvasElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    return {
      start: Math.max(
        0,
        Math.min(
          section.bars * 4 - 0.25,
          Math.floor(
            ((event.clientX - rect.left - 42) / (rect.width - 42)) *
              section.bars *
              16,
          ) / 4,
        ),
      ),
      pitch: Math.max(
        low,
        Math.min(
          high,
          high -
            Math.floor(
              ((event.clientY - rect.top - 24) / (rect.height - 24)) * rows,
            ),
        ),
      ),
    };
  }
  function down(event: React.PointerEvent<HTMLCanvasElement>) {
    if (track.locked || disabled) return;
    const pos = position(event);
    const found = notes.find(
      (n) =>
        n.pitch === pos.pitch &&
        n.start <= pos.start &&
        n.start + n.duration > pos.start,
    );
    if (tool === "erase") {
      if (found) onChange(notes.filter((n) => n.id !== found.id));
      return;
    }
    if (found) {
      setSelected(found.id);
      setDrag({ id: found.id, ...pos });
      event.currentTarget.setPointerCapture(event.pointerId);
    } else if (tool === "draw") {
      const n = {
        id: crypto.randomUUID().replaceAll("-", "").slice(0, 12),
        ...pos,
        duration: Math.min(length, section.bars * 4 - pos.start),
        velocity: 90,
      };
      onChange([...notes, n]);
      setSelected(n.id);
    } else setSelected(null);
  }
  return (
    <section className="editor">
      <div className="editor-toolbar">
        <strong>{track.name}</strong>
        <span className="muted">{section.name}</span>
        <div className="segmented">
          {[
            { Icon: MousePointer2, key: "select" },
            { Icon: Pencil, key: "draw" },
            { Icon: Eraser, key: "erase" },
          ].map(({ Icon, key }) => (
            <button
              key={key}
              title={key}
              aria-label={`${key} notes`}
              className={tool === key ? "selected" : ""}
              onClick={() => setTool(key)}
            >
              <Icon size={14} />
            </button>
          ))}
        </div>
        <label>
          Length
          <select
            aria-label="New note length"
            value={length}
            onChange={(e) => setLength(Number(e.target.value))}
          >
            <option value={0.25}>1/16</option>
            <option value={0.5}>1/8</option>
            <option value={1}>1/4</option>
            <option value={2}>1/2</option>
            <option value={4}>1 bar</option>
          </select>
        </label>
        <span className="push muted">{notes.length} notes</span>
      </div>
      <canvas
        ref={canvas}
        aria-label={`${track.name} piano roll`}
        onPointerDown={down}
        onPointerMove={(e) => {
          if (drag) {
            const p = position(e);
            const n = notes.find((n) => n.id === drag.id)!;
            setDrag({
              ...drag,
              ...p,
              start: Math.min(p.start, section.bars * 4 - n.duration),
            });
          }
        }}
        onPointerUp={() => {
          if (drag) {
            onChange(
              notes.map((n) => (n.id === drag.id ? { ...n, ...drag } : n)),
            );
            setDrag(null);
          }
        }}
        onPointerCancel={() => setDrag(null)}
      />
      <div className="note-inspector">
        <span>
          {selectedNote ? noteName(selectedNote.pitch) : "No note selected"}
        </span>
        {(["pitch", "velocity", "duration"] as const).map((field) => (
          <label key={field}>
            {field}
            <input
              aria-label={`Note ${field}`}
              type="number"
              disabled={!selectedNote || track.locked || disabled}
              min={field === "duration" ? 0.125 : field === "pitch" ? 0 : 1}
              max={field === "duration" ? section.bars * 4 : 127}
              step={field === "duration" ? 0.125 : 1}
              key={`${selectedNote?.id}-${field}-${selectedNote?.[field]}`}
              defaultValue={selectedNote?.[field] ?? ""}
              onKeyDown={(e) => {
                if (e.key === "Enter") e.currentTarget.blur();
              }}
              onBlur={(e) => {
                if (
                  selectedNote &&
                  (!e.currentTarget.value || !e.currentTarget.checkValidity())
                ) {
                  e.currentTarget.value = String(selectedNote[field]);
                  return;
                }
                if (
                  selectedNote &&
                  Number(e.currentTarget.value) !== selectedNote[field]
                )
                  onChange(
                    notes.map((n) =>
                      n.id === selectedNote.id
                        ? { ...n, [field]: Number(e.target.value) }
                        : n,
                    ),
                  );
              }}
            />
          </label>
        ))}
      </div>
    </section>
  );
}
