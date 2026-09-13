autowatch = 1;
inlets = 1;
outlets = 2;

// Reported in every poll so the studio knows which build of this file is
// actually running in Max. autowatch does not reliably reload it — with Live
// in the background it does not fire at all — and a stale script that looks
// connected is the hardest kind of failure to see. Bump this whenever the
// behaviour changes, and the studio will say when the device needs reloading.
var DEVICE_VERSION = 5;

var busy = false;
var completed = {};
var task = null;

function api(path) { return new LiveAPI(null, path); }
function ids(value) {
    var result = [];
    for (var i = 0; i < value.length; i++) if (value[i] === 'id' && Number(value[i + 1])) result.push(Number(value[++i]));
    return result;
}
function number(object, property) { return Number(object.get(property)[0]); }
function text(object, property) {
    // Max hands back a list, and a name containing spaces may arrive split
    // across several symbols. Joining covers both without losing the spaces.
    var value = object.get(property);
    return (value && value.join ? value.join(' ') : String(value)).trim();
}

// This device runs inside Live's own process, so every Live API object it
// builds and every property it reads is CPU taken from the music.
//
// Reading the whole Set on every poll — each track, its devices, their
// parameters, its clips — costs over a thousand round trips in a Set RDX has
// transferred into. Doing that every 1.5 seconds put Live at 137% CPU with
// nothing playing, and a burst that size inside Live's process is also how you
// get an audible dropout.
//
// So a poll reads three properties, and the expensive picture is rebuilt by a
// sweep that walks one track per poll and then rests. The cost per poll is one
// track's worth, there is no burst, and the picture is never older than a
// sweep. A transfer starts a new sweep immediately, because it has just made
// the old one wrong.
//
// What a transfer appends after is never read from here — see command().
var REST_POLLS = 12;   // roughly 18 seconds of quiet between sweeps
var PARAMETERS = 24;   // enough to recognise a device, cheap enough to ask for

var published = null;  // the last complete picture; what a poll reports
var sweeping = null;   // the one being built
var cursor = 0;
var resting = 0;

function scanTrack(id) {
    var track = api('id ' + id);
    var deviceIds = ids(track.get('devices'));
    var listed = [];
    for (var d = 0; d < deviceIds.length; d++) {
        var device = api('id ' + deviceIds[d]);
        // Parameter names are what a sound mapping is built from, and for a
        // plugin they can only be discovered at runtime.
        var parameterIds = ids(device.get('parameters'));
        var parameters = [];
        for (var q = 0; q < parameterIds.length && q < PARAMETERS; q++) {
            var parameter = api('id ' + parameterIds[q]);
            parameters.push({
                name: text(parameter, 'name'),
                min: number(parameter, 'min'),
                max: number(parameter, 'max'),
                value: number(parameter, 'value')
            });
        }
        listed.push({
            name: text(device, 'name'),
            // PluginDevice means a VST or AU: RDX can drive its parameters but
            // can never insert it, which is the whole template-Set idea.
            plugin: text(device, 'class_name') === 'PluginDevice',
            kind: text(device, 'class_display_name'),
            parameter_count: parameterIds.length,
            parameters: parameters
        });
    }
    return {name: text(track, 'name'), midi: !!number(track, 'has_midi_input'), devices: listed};
}

function trackContent(id) {
    var track = api('id ' + id);
    var clips = ids(track.get('arrangement_clips'));
    var end = 0;
    for (var c = 0; c < clips.length; c++) end = Math.max(end, number(api('id ' + clips[c]), 'end_time'));
    if (clips.length) return {content: true, end: end};
    var slots = ids(track.get('clip_slots'));
    for (var s = 0; s < slots.length; s++) if (number(api('id ' + slots[s]), 'has_clip')) return {content: true, end: 0};
    return {content: false, end: 0};
}

function advance(trackIds) {
    if (sweeping === null) {
        if (resting > 0) {resting--;return;}
        sweeping = {tracks: [], has_content: false, arrangement_end: 0};
        cursor = 0;
    }
    if (cursor < trackIds.length) {
        var id = trackIds[cursor++];
        sweeping.tracks.push(scanTrack(id));
        var found = trackContent(id);
        if (found.content) sweeping.has_content = true;
        sweeping.arrangement_end = Math.max(sweeping.arrangement_end, found.end);
    }
    if (cursor >= trackIds.length) {
        published = sweeping;
        sweeping = null;
        resting = REST_POLLS;
    }
}

// The exact state of the arrangement, read now rather than remembered. A
// transfer decides where to append from this, so a stale answer would write
// RDX's tracks on top of the user's music.
function contents() {
    var trackIds = ids(api('live_set').get('tracks'));
    var picture = {has_content: false, arrangement_end: 0};
    for (var i = 0; i < trackIds.length; i++) {
        var found = trackContent(trackIds[i]);
        if (found.content) picture.has_content = true;
        picture.arrangement_end = Math.max(picture.arrangement_end, found.end);
    }
    return picture;
}

function state() {
    var song = api('live_set');
    if (!Number(song.id)) throw new Error('Open this device inside Ableton Live');
    var trackIds = ids(song.get('tracks'));
    try {advance(trackIds);} catch (error) {sweeping = null;resting = REST_POLLS;}
    var picture = published || {tracks: null, has_content: false, arrangement_end: 0};
    return {
        tempo: number(song, 'tempo'),
        has_content: picture.has_content,
        arrangement_end: picture.arrangement_end,
        track_count: trackIds.length,
        playing: !!number(song, 'is_playing'),
        busy: busy,
        tracks: picture.tracks,
        // Null until the first sweep finishes, so the studio can tell "still
        // reading the Set" apart from "the Set is empty".
        scanned: published !== null,
        device_version: DEVICE_VERSION
    };
}

function refresh() {
    // A transfer just changed the Set, so start a fresh sweep on the next poll
    // rather than reporting what was there before it.
    published = null;
    sweeping = null;
    resting = 0;
}

function read(filename) {
    var file = new File(filename, 'read');
    if (!file.isopen) throw new Error('Transfer file is missing');
    var text = '';
    while (file.position < file.eof) text += file.readstring(Math.min(8192, file.eof - file.position));
    file.close();
    return JSON.parse(text);
}
function countNotes(clip, length) {
    // get_notes_extended answers with the dictionary's *contents* as JSON, not
    // with a name to look up. Parsing it as a name silently yields an empty
    // dictionary, which reads as "Live kept 0 notes" even when the notes are
    // sitting right there. Confirmed against Live 12.4.5 on 10 September 2026.
    var raw;
    try {
        raw = String(clip.call('get_notes_extended', 0, 127, 0, length));
    } catch (error) {
        return {count: -1, detail: 'get_notes_extended threw: ' + error.message};
    }
    try {
        var parsed = JSON.parse(raw);
        return {count: (parsed.notes || []).length, detail: ''};
    } catch (error) {
        return {count: -1, detail: 'unreadable reply: ' + raw.slice(0, 80)};
    }
}
function addNotes(clip, notes, length) {
    // Pass the Dict itself. The documented-looking form
    // clip.call('add_new_notes', 'dictionary', dict.name) throws nothing and
    // adds nothing, which is the worst combination; it was silently losing
    // every note until a read-back proved the clip was empty afterwards.
    var dict = new Dict();
    dict.parse(JSON.stringify({notes: notes}));
    try {
        clip.call('add_new_notes', dict);
    } catch (error) {
        dict.freepeer();
        return {ok: false, detail: 'add_new_notes threw: ' + error.message};
    }
    dict.freepeer();
    var got = countNotes(clip, length);
    if (got.count >= notes.length) return {ok: true, count: got.count};
    return {ok: false, detail: 'Live kept ' + got.count + ' of ' + notes.length + (got.detail ? ' (' + got.detail + ')' : '')};
}
// Native Live instruments for RDX's roles. Only native devices can be
// inserted — plugins cannot, whatever the user owns — so this is deliberately
// a short list of things every Live 12 Suite install has.
var INSTRUMENTS = {drums: 'Drum Rack', bass: 'Wavetable', chords: 'Wavetable', lead: 'Wavetable', pad: 'Wavetable'};

function addInstrument(track, role) {
    // insert_device arrived in Live 12.3 and its exact call shape is not
    // something to assume, so both documented forms are tried and the result
    // is reported rather than trusted. An instrument is a bonus on top of the
    // transfer; failing to add one must never lose the notes.
    var wanted = INSTRUMENTS[role];
    if (!wanted) return 'no instrument for ' + role;
    var before = ids(track.get('devices')).length;
    var attempts = [];
    var forms = [
        function () { track.call('insert_device', wanted, -1); },
        function () { track.call('insert_device', wanted); }
    ];
    for (var i = 0; i < forms.length; i++) {
        try {
            forms[i]();
        } catch (error) {
            attempts.push(error.message);
            continue;
        }
        if (ids(track.get('devices')).length > before) return wanted;
        attempts.push('form ' + (i + 1) + ' added nothing');
    }
    return 'no instrument (' + attempts.join('; ') + ')';
}

function snapshot() {
    try {outlet(0, 'state', JSON.stringify(state()));}
    catch (error) {outlet(1, String(error.message));}
}
function connection() {
    if (!busy) outlet(1, arrayfromargs(arguments).join(' '));
}
function command(filename) {
    var job;
    try {job = read(filename);} catch (error) {outlet(1, String(error.message));return;}
    if (completed[job.id]) {outlet(0, 'result', JSON.stringify(completed[job.id]));return;}
    if (busy) return;
    busy = true;
    var song = api('live_set');
    var created = [];
    var undoOpen = false;
    var index = 0;
    var start = 0;
    var tasks = [];
    var instruments = [];
    function finish(ok, message) {
        if (undoOpen) {song.call('end_undo_step');undoOpen = false;}
        busy = false;
        refresh();
        var result = {id:job.id,ok:ok,message:message,created_tracks:created,start_beat:start};
        completed[job.id] = result;
        outlet(0, 'result', JSON.stringify(result));
        outlet(1, message);
        if (task) {task.cancel();task = null;}
    }
    function makeTrack(source, midi) {
        var before = ids(song.get('tracks'));
        song.call(midi ? 'create_midi_track' : 'create_audio_track', -1);
        var after = ids(song.get('tracks'));
        if (after.length !== before.length + 1) throw new Error('Live could not create a track');
        var id = after[after.length - 1];
        created.push(id);
        var track = api('id ' + id);
        track.set('name', 'RDX ' + source.name + (midi ? ' MIDI' : ' Audio') + ' r' + job.project.revision);
        track.set('color', parseInt(source.color.slice(1), 16));
        track.set('mute', midi ? 1 : (source.mute || (job.project.tracks.some(function(t) {return t.solo;}) && !source.solo) ? 1 : 0));
        track.set('arm', 0);
        return track;
    }
    try {
        // RDX places a native device on a track and reads it back in full. This
        // is the first native-Ableton capability: no stems, no undo step, just
        // insert and scan every parameter so a sound recipe can target real
        // knob names. insert_device is native-only (Live 12.3+); a VST cannot
        // be placed this way, only driven once present.
        if (job.kind === 'insert_device') {
            var before = ids(song.get('tracks'));
            song.call('create_midi_track', -1);
            var after = ids(song.get('tracks'));
            if (after.length !== before.length + 1) throw new Error('Live could not create a MIDI track');
            var target = api('id ' + after[after.length - 1]);
            target.set('name', 'RDX ' + job.device);
            var had = ids(target.get('devices')).length;
            var tries = [];
            var placed = false;
            var forms = [function () { target.call('insert_device', job.device, -1); }, function () { target.call('insert_device', job.device); }];
            for (var f = 0; f < forms.length && !placed; f++) {
                try { forms[f](); } catch (e) { tries.push(e.message); continue; }
                if (ids(target.get('devices')).length > had) placed = true; else tries.push('form ' + (f + 1) + ' added nothing');
            }
            var deviceIds = ids(target.get('devices'));
            var scanned = [];
            for (var d = 0; d < deviceIds.length; d++) {
                var dev = api('id ' + deviceIds[d]);
                var pids = ids(dev.get('parameters'));
                var params = [];
                for (var q = 0; q < pids.length; q++) {
                    var par = api('id ' + pids[q]);
                    params.push({name: text(par, 'name'), min: number(par, 'min'), max: number(par, 'max'), value: number(par, 'value')});
                }
                scanned.push({name: text(dev, 'name'), kind: text(dev, 'class_display_name'), plugin: text(dev, 'class_name') === 'PluginDevice', parameter_count: pids.length, parameters: params});
            }
            busy = false;
            refresh();
            var probe = {id: job.id, ok: placed, message: placed ? ('Placed ' + job.device + ' on a new MIDI track') : ('Could not place ' + job.device + ': ' + tries.join('; ')), devices: scanned};
            completed[job.id] = probe;
            outlet(0, 'result', JSON.stringify(probe));
            outlet(1, probe.message);
            return;
        }
        if (job.kind !== 'append_project') throw new Error('Unsupported transfer');
        if (number(song, 'is_playing')) throw new Error('Stop Live playback before transferring');
        // Read fresh: appending after a remembered end would land on top of
        // whatever the user has added since the last sweep.
        var current = contents();
        if (current.has_content && Math.abs(number(song, 'tempo') - job.project.tempo) > 0.01) throw new Error('Live tempo changed; match it to RDX before transferring');
        start = Math.ceil(current.arrangement_end / 4) * 4;
        song.call('begin_undo_step');undoOpen = true;
        if (!current.has_content) song.set('tempo', job.project.tempo);
        job.project.tracks.forEach(function(source) {
            tasks.push(function() {
                var track = makeTrack(source, false);
                track.call('create_audio_clip', job.stems[source.id], start);
                var clips = ids(track.get('arrangement_clips'));
                if (clips.length !== 1) throw new Error('Audio clip creation did not complete');
                var clip = api('id ' + clips[0]);
                clip.set('name', source.name + ' - rendered sound');
                clip.set('warping', 0);
                clip.set('looping', 0);
            });
            if (source.role !== 'audio') tasks.push(function() {
                var track = makeTrack(source, true);
                instruments.push(source.name + ': ' + addInstrument(track, source.role));
                var offset = start;
                job.project.sections.forEach(function(section) {
                    var sourceClip = source.clips.filter(function(c) {return c.section_id === section.id;})[0];
                    if (sourceClip && sourceClip.notes.length) {
                        var before = ids(track.get('arrangement_clips'));
                        track.call('create_midi_clip', offset, section.bars * 4);
                        var after = ids(track.get('arrangement_clips'));
                        var added = after.filter(function(id) {return before.indexOf(id) === -1;});
                        if (added.length !== 1) throw new Error('MIDI clip creation did not complete');
                        var clip = api('id ' + added[0]);
                        clip.set('name', section.name + ' - ' + source.name);
                        var payload = sourceClip.notes.map(function(n) {return {pitch:n.pitch,start_time:n.start,duration:n.duration,velocity:n.velocity,mute:0};});
                        var written = addNotes(clip, payload, section.bars * 4);
                        if (!written.ok) throw new Error(written.detail + ' notes in ' + section.name);
                    }
                    offset += section.bars * 4;
                });
            });
        });
        task = new Task(function() {
            try {
                if (index < tasks.length) {
                    outlet(1, 'Transferring ' + (index + 1) + '/' + tasks.length);
                    tasks[index++]();
                    task.schedule(100);
                } else {
                    api('live_app view').call('show_view', 'Arranger');
                    song.set('current_song_time', start);
                    finish(true, 'Added ' + created.length + ' tracks at bar ' + (start / 4 + 1) + '. MIDI source tracks are muted; sounds and automation are in the audio stems. Instruments: ' + instruments.join(' | '));
                }
            } catch (error) {finish(false, 'Transfer stopped: ' + error.message + '. ' + created.length + ' new RDX tracks remain. Live Undo can remove this transfer.');}
        }, this);
        task.schedule(1);
    } catch (error) {finish(false, 'Transfer not completed: ' + error.message);}
}
