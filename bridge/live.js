autowatch = 1;
inlets = 1;
outlets = 2;

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

// Reading every device on every track is far heavier than reading the tempo,
// so it happens on its own slower cycle and the answer is cached between.
var scanned = null;
var pollsSinceScan = 99;

function devices() {
    var song = api('live_set');
    var trackIds = ids(song.get('tracks'));
    var summary = [];
    for (var i = 0; i < trackIds.length; i++) {
        var track = api('id ' + trackIds[i]);
        var deviceIds = ids(track.get('devices'));
        var listed = [];
        for (var d = 0; d < deviceIds.length; d++) {
            var device = api('id ' + deviceIds[d]);
            listed.push({
                name: text(device, 'name'),
                // PluginDevice means a VST or AU: RDX can drive its parameters
                // but can never insert it, which is the whole template-Set idea.
                plugin: text(device, 'class_name') === 'PluginDevice',
                kind: text(device, 'class_display_name')
            });
        }
        summary.push({
            name: text(track, 'name'),
            midi: !!number(track, 'has_midi_input'),
            devices: listed
        });
    }
    return summary;
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
function state() {
    var song = api('live_set');
    if (!Number(song.id)) throw new Error('Open this device inside Ableton Live');
    var tracks = ids(song.get('tracks'));
    var end = 0;
    var content = false;
    for (var i = 0; i < tracks.length; i++) {
        var track = api('id ' + tracks[i]);
        var clips = ids(track.get('arrangement_clips'));
        for (var c = 0; c < clips.length; c++) {
            content = true;
            end = Math.max(end, number(api('id ' + clips[c]), 'end_time'));
        }
        var slots = ids(track.get('clip_slots'));
        for (var s = 0; s < slots.length; s++) if (number(api('id ' + slots[s]), 'has_clip')) content = true;
    }
    if (++pollsSinceScan >= 8) {
        try { scanned = devices(); } catch (error) { scanned = null; }
        pollsSinceScan = 0;
    }
    return {tempo:number(song, 'tempo'), has_content:content, arrangement_end:end, track_count:tracks.length, playing:!!number(song, 'is_playing'), busy:busy, tracks:scanned};
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
    function finish(ok, message) {
        if (undoOpen) {song.call('end_undo_step');undoOpen = false;}
        busy = false;
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
        if (job.kind !== 'append_project') throw new Error('Unsupported transfer');
        var current = state();
        if (current.playing) throw new Error('Stop Live playback before transferring');
        if (current.has_content && Math.abs(current.tempo - job.project.tempo) > 0.01) throw new Error('Live tempo changed; match it to RDX before transferring');
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
                    finish(true, 'Added ' + created.length + ' tracks at bar ' + (start / 4 + 1) + '. MIDI source tracks are muted; sounds and automation are in the audio stems.');
                }
            } catch (error) {finish(false, 'Transfer stopped: ' + error.message + '. ' + created.length + ' new RDX tracks remain. Live Undo can remove this transfer.');}
        }, this);
        task.schedule(1);
    } catch (error) {finish(false, 'Transfer not completed: ' + error.message);}
}
