"""Package the Max patch using the installed Live audio-device container format."""
import json
import shutil
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = Path('/Applications/Ableton Live 12 Suite.app/Contents/App-Resources/Misc/Max Devices/Max Audio Effect.amxd')


def build():
    source = TEMPLATE.read_bytes()
    if source[:4] != b'ampf' or source[24:28] != b'ptch':
        raise ValueError('Unrecognized installed Max device format')
    patch = json.loads(source[32:].rstrip(b'\0'))
    p = patch['patcher']
    p.update(rect=[0, 0, 680, 460], openinpresentation=1, devicewidth=300, openrect=[0, 0, 300, 169])
    boxes, lines = [], []

    def box(id, text, rect, **options):
        boxes.append({'box': {'id': id, 'maxclass': 'newobj', 'text': text, 'patching_rect': rect, **options}})

    def wire(source, outlet, target, inlet=0):
        lines.append({'patchline': {'source': [source, outlet], 'destination': [target, inlet]}})

    box('input', 'plugin~', [20, 330, 60, 22], numinlets=2, numoutlets=2, outlettype=['signal', 'signal'])
    box('output', 'plugout~', [20, 390, 60, 22], numinlets=2, numoutlets=2)
    wire('input', 0, 'output');wire('input', 1, 'output', 1)
    box('live', f'js "{ROOT / "bridge/live.js"}"', [20, 200, 400, 22], numinlets=1, numoutlets=2)
    box('node', f'node.script "{ROOT / "bridge/connection.js"}" @autostart 1', [20, 260, 620, 22], numinlets=1, numoutlets=2)
    box('defer', 'deferlow', [470, 200, 65, 22], numinlets=1, numoutlets=1)
    wire('live', 0, 'node');wire('node', 0, 'defer');wire('defer', 0, 'live')
    box('device', 'live.thisdevice', [20, 20, 100, 22], numinlets=1, numoutlets=3)
    box('start', '1', [20, 60, 30, 22], maxclass='message', numinlets=2, numoutlets=1)
    box('metro', 'metro 1500', [20, 105, 90, 22], numinlets=2, numoutlets=1)
    box('snapshot', 'snapshot', [20, 150, 70, 22], maxclass='message', numinlets=2, numoutlets=1)
    wire('device', 0, 'start');wire('start', 0, 'metro');wire('metro', 0, 'snapshot');wire('snapshot', 0, 'live')
    box('set', 'prepend set', [440, 260, 85, 22], numinlets=1, numoutlets=1)
    box('title', 'RDX / LIVE', [160, 20, 140, 24], maxclass='comment', fontsize=19, presentation=1, presentation_rect=[16, 14, 240, 26])
    box('status', 'Connecting to RDX...', [160, 60, 250, 60], maxclass='comment', linecount=4, fontsize=11, presentation=1, presentation_rect=[16, 56, 268, 80])
    box('local', 'LOCAL BRIDGE  /  0.1', [160, 130, 200, 20], maxclass='comment', fontsize=9, presentation=1, presentation_rect=[16, 141, 260, 18])
    wire('live', 1, 'set');wire('set', 0, 'status')
    p['boxes'], p['lines'] = boxes, lines
    p['dependency_cache'] = []
    serialized = json.dumps(patch, indent=2).encode() + b'\0'
    output = ROOT / 'artifacts'
    output.mkdir(exist_ok=True)
    (output / 'RDX Bridge.maxpat').write_text(json.dumps(patch, indent=2))
    destination = output / 'RDX Bridge.amxd'
    destination.write_bytes(source[:28] + struct.pack('<I', len(serialized)) + serialized)
    assert json.loads(destination.read_bytes()[32:].rstrip(b'\0')) == patch
    print(f'Built {destination}')
    install(destination)


# Live's own browser reads this folder, so a device copied here appears under
# Places > User Library > Presets > Audio Effects > Max Audio Effect and can be
# dragged onto a track without leaving Ableton. Reloading it after a change
# still means dragging it off the track and back on — `autowatch` does not fire
# with Live in the background — but at least Finder is out of the loop.
LIBRARY = Path.home() / 'Music/Ableton/User Library/Presets/Audio Effects/Max Audio Effect'


def install(device: Path):
    if not LIBRARY.parent.parent.parent.exists():
        print('No Ableton User Library found, so the device was not installed into it.')
        return
    LIBRARY.mkdir(parents=True, exist_ok=True)
    shutil.copy2(device, LIBRARY / device.name)
    print(f'Installed into the Live browser: User Library > Presets > Audio Effects > Max Audio Effect > {device.stem}')


if __name__ == '__main__':
    build()
