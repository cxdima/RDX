// Runs bridge/live.js against a stubbed Live API, so the Max-side logic can be
// tested without Ableton. It proves the parsing and the shape of what RDX
// reports; it cannot prove how real Live behaves, which is what the notes in
// RDX_PLAN.md are for.
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const mode = process.argv[2];
const input = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const set = mode === "--set" ? input : { id: 1, tempo: 124, is_playing: 0, tracks: [], track_objects: [], byId: {} };

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
  set() {}
  call() {}
}

const captured = [];
const context = {
  LiveAPI: FakeLiveAPI,
  Dict: class {
    constructor() { this.name = "d1"; }
    parse() {}
    stringify() { return "{}"; }
    freepeer() {}
  },
  Task: class { constructor(fn) { this.fn = fn; } schedule() {} cancel() {} },
  File: class { constructor() { this.isopen = false; } },
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
vm.runInContext(fs.readFileSync(path.join(__dirname, "../../bridge/live.js"), "utf8"), context);

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
const states = captured.filter(([index, kind]) => index === 0 && kind === "state");
const errors = captured.filter(([index]) => index === 1);
console.log(JSON.stringify({
  polls: states.length,
  cost: polls,
  errors: errors.map((e) => e[1]),
  state: states.length ? JSON.parse(states[states.length - 1][2]) : null,
}));
