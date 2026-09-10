"""Capture the tested local environment without resolving or downloading packages."""
import hashlib
import importlib.metadata
import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
packages = sorted((d.metadata['Name'], d.version) for d in importlib.metadata.distributions() if d.metadata['Name'].lower() != 'rdx-studio')
requirements = '# Installed environment snapshot: CPython 3.12, macOS arm64. Not a cross-platform lock.\n'
requirements += ''.join(f'{name}=={version}\n' for name, version in packages)
(root / 'requirements-macos.lock').write_text(requirements)
record_path = root / 'data/models/rdx-v1/training-record.json'
if record_path.exists():
    record = json.loads(record_path.read_text())
    record['environment_snapshot'] = dict(packages)
    record['dataset_sha256'] = {split:hashlib.sha256((root / f'data/training/{split}.jsonl').read_bytes()).hexdigest() for split in ('train','valid','test')}
    record_path.write_text(json.dumps(record, indent=2))
print(f'Captured {len(packages)} installed packages')
