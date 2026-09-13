// Runs bridge/live.js against a stubbed Live API, so the Max-side logic can be
// tested without Ableton. It proves the parsing and the shape of what RDX
// reports; it cannot prove how real Live behaves, which is what the notes in
// RDX_PLAN.md are for.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const mode = process.argv[2];
const input = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const set =
  mode === "--set"
    ? input
    : {
        id: 1,
        tempo: 124,
        is_playing: 0,
        tracks: [],
        track_objects: [],
        byId: {},
      };

/** Max returns every property as a list, and splits symbols on spaces. */
function asList(value) {
  if (Array.isArray(value)) return value;
  if (typeof value === "string" && value.includes(" ")) return value.split(" ");
  return [value];
}

// Every Live API object built and every property read is a round trip into
// Live's process, and it is that count — not this harness's own speed — that
// decides whether the device is a burden on a machine trying to make music.
const cost = { built: 0, reads: 0 };
const writes = [];
const scheduled = [];
const nextId = () => Math.max(1, ...Object.keys(set.byId).map(Number)) + 1;

class FakeLiveAPI {
  constructor(_callback, pathOrId) {
    cost.built++;
    const key = String(pathOrId);
    this.id = 1;
    if (key === "live_set") this.node = set;
    else if (key.startsWith("id ")) this.node = set.byId[key.slice(3)];
    else this.node = { id: 0 };
    if (!this.node) this.node = { id: 0 };
    this.id = this.node.id ?? 0;
  }
  get(property) {
    cost.reads++;
    const value = this.node[property];
    if (value === undefined) return [0];
    // Live returns child collections as ["id", 3, "id", 5, ...].
    if (Array.isArray(value) && value.every((v) => typeof v === "number"))
      return value.flatMap((id) => ["id", id]);
    return asList(value);
  }
  set(property, value) {
    writes.push({ id: this.id, property, value });
    this.node[property] = value;
  }
  call(name, ...args) {
    writes.push({ id: this.id, call: name, args });
    if (name === "create_audio_track") {
      const id = nextId();
      set.byId[id] = { id, arrangement_clips: [], clip_slots: [], devices: [] };
      set.tracks.push(id);
    } else if (name === "create_audio_clip") {
      const id = nextId();
      set.byId[id] = { id, end_time: args[1] + 8 };
      this.node.arrangement_clips.push(id);
    } else if (name === "create_midi_clip") {
      const id = nextId();
      set.byId[id] = { id, start_time: args[0], end_time: args[0] + args[1], _notes: [] };
      this.node.arrangement_clips.push(id);
    } else if (name === "delete_clip") {
      // A clip object is passed by id, in one of several call shapes; find it.
      let cid = null;
      for (const a of args) {
        if (typeof a === "number") { cid = a; break; }
        if (typeof a === "string") { const m = a.match(/\d+/); if (m) { cid = Number(m[0]); break; } }
      }
      const clips = this.node.arrangement_clips || [];
      const at = clips.indexOf(cid);
      if (at !== -1) { clips.splice(at, 1); delete set.byId[cid]; }
    } else if (name === "add_new_notes") {
      let data = {};
      try { data = JSON.parse(args[0].stringify()); } catch (e) { data = {}; }
      if (this.node._notes) this.node._notes.push(...(data.notes || []));
    } else if (name === "get_notes_extended") {
      return JSON.stringify({ notes: this.node._notes || [] });
    }
  }
}

const captured = [];
const context = {
  LiveAPI: FakeLiveAPI,
  Dict: class {
    constructor() {
      this.name = "d1";
      this._json = "{}";
    }
    parse(text) {
      this._json = typeof text === "string" ? text : "{}";
    }
    stringify() {
      return this._json;
    }
    freepeer() {}
  },
  Task: class {
    constructor(fn) {
      this.fn = fn;
    }
    schedule() {
      scheduled.push(this.fn);
    }
    cancel() {}
  },
  File: class {
    constructor() {
      this.isopen = false;
    }
  },
  outlet: (index, ...rest) => captured.push([index, ...rest]),
  arrayfromargs: (...args) => args,
  JSON,
  Math,
  Number,
  String,
  Array,
  Object,
  Error,
  autowatch: 0,
  inlets: 1,
  outlets: 2,
};
vm.createContext(context);
vm.runInContext(
  fs.readFileSync(path.join(__dirname, "../../bridge/live.js"), "utf8"),
  context,
);

if (mode === "--notes") {
  // A clip that answers get_notes_extended with whatever the test scripted,
  // so the reply parsing can be checked against the shapes Live really sends.
  const clip = {
    call(name) {
      if (name === "get_notes_extended") return input.reply;
      return undefined;
    },
  };
  console.log(JSON.stringify(context.countNotes(clip, 16)));
  process.exit(0);
}

// Several polls, because the device scan runs on a slower cycle than the rest,
// and the per-poll cost is recorded so a test can hold it down.
const polls = [];
for (let i = 0; i < 26; i++) {
  const before = cost.built + cost.reads;
  context.snapshot();
  polls.push(cost.built + cost.reads - before);
}
const states = captured.filter(
  ([index, kind]) => index === 0 && kind === "state",
);
const errors = captured.filter(([index]) => index === 1);
if (input.command) {
  // Change Live *after* the cached sweep. command() must reread contents
  // before deciding where to put even its first audio clip.
  if (input.new_content) {
    const id = nextId();
    set.byId[id] = { id, end_time: input.new_content.end };
    set.byId[set.tracks[0]].arrangement_clips.push(id);
  }
  context.read = () => input.command;
  context.command("test-job.json");
  for (let i = 0; scheduled.length && i < 100; i++) scheduled.shift()();
}
const result = captured.find(
  ([index, kind]) => index === 0 && kind === "result",
);
console.log(
  JSON.stringify({
    polls: states.length,
    cost: polls,
    errors: errors.map((e) => e[1]),
    state: states.length ? JSON.parse(states[states.length - 1][2]) : null,
    writes,
    transfer: result ? JSON.parse(result[2]) : null,
  }),
);
