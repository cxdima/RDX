import { Sparkles } from "lucide-react";
import type { Section, Track } from "./types";

// These lists mirror the Python they drive. tests/test_musical.py parses this
// file and fails if either side gains a name the other does not have, because a
// control offering a melody shape the engine has never heard of is a button
// that reports success and changes nothing.
export const CELLS = [
  ["pluck", "Pluck — sixteenths with gaps"],
  ["anthem", "Anthem — long notes you can sing"],
  ["call", "Call — three notes, then silence"],
  ["drive", "Drive — straight eighths"],
  ["push", "Push — every note lands late"],
  ["roll", "Roll — sixteenths into a held note"],
  ["stab", "Stab — two long notes a bar"],
] as const;

export const SHAPES = [
  "climb",
  "fall",
  "arch",
  "turn",
  "hook",
  "leap",
  "hover",
  "ascent",
  "wave",
  "question",
  "descent",
] as const;

export const FORMS = [
  ["trance", "Trance — state, repeat, sequence up, peak, resolve"],
  ["anthem", "Anthem — the big one, for a breakdown"],
  ["answer", "Call and response — silence between the phrases"],
  ["driving", "Driving — no room to breathe"],
  ["rising", "Rising — climbs the whole way"],
  ["loop", "Loop — one bar, eight times"],
] as const;

export const BASS_PATTERNS = [
  ["offbeat", "Offbeat — between every kick (trance, house)"],
  ["rolling", "Rolling — three sixteenths after the kick (psytrance)"],
  ["driving", "Driving — straight eighths"],
  ["sustained", "Sustained — one note a bar, held"],
  ["octave", "Octave — offbeat, every other note up"],
  ["halftime", "Halftime — two long notes a bar"],
  ["sixteenth", "Sixteenth — relentless"],
] as const;

export const KITS = [
  "four_floor",
  "breakbeat",
  "halftime",
  "minimal",
  "rolling",
  "mainstage",
] as const;

export const GENRES = [
  ["trance", "Trance — 138, offbeat bass, supersaw"],
  ["psytrance", "Psytrance — 145, rolling bass, acid"],
  ["techno", "Techno — 132, hard and driving"],
  ["house", "House — 124, chords doing the work"],
  ["hardstyle", "Hardstyle — 150, halftime under a four-floor kick"],
] as const;

export const PROGRESSIONS = [
  "trance",
  "driving",
  "epic",
  "lift",
  "classic",
  "pop",
  "melancholy",
  "suspense",
  "andalusian",
] as const;

export const ANCHORS = [
  ["key", "Hold the idea still"],
  ["chord", "Move it with the chord"],
] as const;

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="write-row">
      <span>{label}</span>
      {children}
    </label>
  );
}

function Choice({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string;
  value: string;
  options: readonly (readonly [string, string] | string)[];
  onChange: (value: string) => void;
  disabled?: boolean;
}) {
  return (
    <Row label={label}>
      <select
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((option) => {
          const [name, told] =
            typeof option === "string" ? [option, option] : option;
          return (
            <option key={name} value={name}>
              {told}
            </option>
          );
        })}
      </select>
    </Row>
  );
}

/** The generators, as controls rather than as sentences to the model.
 *
 * Everything here is reachable through chat too, but chat goes through a
 * language model that has to recognise which operation was meant. These are the
 * same operations with the guessing removed, which is what makes them the right
 * way to audition a musical change and decide whether the vocabulary itself is
 * any good. */
export type MelodySettings = {
  cell: string;
  shape: string;
  form: string;
  anchor: string;
  progression: string;
};

export const DEFAULT_MELODY: MelodySettings = {
  cell: "pluck",
  shape: "wave",
  form: "trance",
  anchor: "key",
  progression: "trance",
};

/** The generators, as controls rather than as sentences to a model.
 *
 * Everything here is reachable through chat too, but chat goes through a
 * language model that has to recognise which operation was meant. These are the
 * same operations with the guessing taken out, which is what makes them the
 * right way to audition a musical change and decide whether the vocabulary
 * itself is any good.
 */
export default function Write({
  track,
  disabled,
  melody,
  setMelody,
  onAction,
}: {
  track: Track;
  disabled: boolean;
  melody: MelodySettings;
  setMelody: (next: MelodySettings) => void;
  onAction: (
    kind: string,
    params: Record<string, unknown>,
    label: string,
  ) => void;
}) {
  if (track.role === "drums")
    return (
      <div className="write-panel">
        <DrumControls disabled={disabled} onAction={onAction} />
      </div>
    );
  if (track.role === "audio") return null;
  return (
    <div className="write-panel">
      <Choice
        label="Rhythm of the idea"
        value={melody.cell}
        options={CELLS}
        disabled={disabled}
        onChange={(cell) => setMelody({ ...melody, cell })}
      />
      <Choice
        label="Shape"
        value={melody.shape}
        options={SHAPES}
        disabled={disabled}
        onChange={(shape) => setMelody({ ...melody, shape })}
      />
      <Choice
        label="Across eight bars"
        value={melody.form}
        options={FORMS}
        disabled={disabled}
        onChange={(form) => setMelody({ ...melody, form })}
      />
      <Choice
        label="When the chord moves"
        value={melody.anchor}
        options={ANCHORS}
        disabled={disabled}
        onChange={(anchor) => setMelody({ ...melody, anchor })}
      />
      <Choice
        label="Chords to follow"
        value={melody.progression}
        options={PROGRESSIONS}
        disabled={disabled}
        onChange={(progression) => setMelody({ ...melody, progression })}
      />
      <button
        className="text-button"
        disabled={disabled}
        onClick={() =>
          onAction(
            "melody",
            { ...melody },
            `Wrote a ${melody.form} melody on ${track.name}`,
          )
        }
      >
        <Sparkles size={14} /> Write the melody
      </button>
      <div className="write-divider" />
      <Choice
        label="Bassline"
        value=""
        options={[["", "Write a bassline…"], ...BASS_PATTERNS]}
        disabled={disabled}
        onChange={(pattern) =>
          pattern &&
          onAction(
            "bassline",
            { pattern, progression: melody.progression },
            `${track.name}: ${pattern} bassline`,
          )
        }
      />
      <Choice
        label="Chords"
        value=""
        options={[["", "Write a progression…"], ...PROGRESSIONS]}
        disabled={disabled}
        onChange={(progression) =>
          progression &&
          onAction(
            "harmony",
            { progression, span: 4 },
            `${track.name}: ${progression} progression`,
          )
        }
      />
    </div>
  );
}

function DrumControls({
  disabled,
  onAction,
}: {
  disabled: boolean;
  onAction: (
    kind: string,
    params: Record<string, unknown>,
    label: string,
  ) => void;
}) {
  return (
    <>
      <Choice
        label="Kit"
        value=""
        options={[["", "Choose a kit…"], ...KITS.map((k) => [k, k] as const)]}
        disabled={disabled}
        onChange={(kit) => kit && onAction("kit", { kit }, `Drums: ${kit}`)}
      />
      {/* These three add to the pattern already playing rather than replacing
          it — naming no kit and no layers is what tells the engine to decorate. */}
      <div className="write-buttons">
        <button
          className="text-button"
          disabled={disabled}
          onClick={() => onAction("kit", { crash: true }, "Added a crash")}
        >
          Crash
        </button>
        <button
          className="text-button"
          disabled={disabled}
          onClick={() => onAction("kit", { fill: true }, "Added a fill")}
        >
          Fill
        </button>
        <button
          className="text-button"
          disabled={disabled}
          onClick={() => onAction("kit", { roll: true }, "Added a roll")}
        >
          Roll
        </button>
      </div>
    </>
  );
}
