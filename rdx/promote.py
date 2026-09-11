"""Activate a measured adapter, retaining the comparison and its limitations."""
import hashlib
import json
from datetime import datetime, timezone

from .model import ADAPTER, DATA, SYSTEM


def main():
    base = json.loads((DATA / 'training/base-evaluation.json').read_text())
    adapter = json.loads((DATA / 'training/adapter-evaluation.json').read_text())
    weights = ADAPTER / 'adapters.safetensors'
    if base.get('benchmark_version') != adapter.get('benchmark_version') or base['total'] != adapter['total']:
        raise ValueError('Compare both models using the same evaluation version')
    if adapter['passed'] / adapter['total'] < .7 or adapter['passed'] <= base['passed']:
        raise ValueError('Keep the current model; the candidate has not met the initial instruction-following check')
    if adapter.get('leaked_into_training'):
        raise ValueError('Benchmark phrasings leaked into training; the comparison is not measuring generalisation')
    record_path = ADAPTER / 'training-record.json'
    if record_path.exists():
        trained_on = json.loads(record_path.read_text()).get('system_sha256')
        if trained_on and trained_on != hashlib.sha256(SYSTEM.encode()).hexdigest():
            raise ValueError(
                'The system prompt has changed since this adapter was trained. Every training example embeds it, '
                'so the adapter is tuned to a prompt the model no longer receives. Rebuild the dataset and train again.'
            )
    record = {'activated_at':datetime.now(timezone.utc).isoformat(), 'adapter_sha256':hashlib.sha256(weights.read_bytes()).hexdigest(), 'base_passed':base['passed'], 'adapter_passed':adapter['passed'], 'total':adapter['total'], 'benchmark_version':adapter['benchmark_version'], 'limits':adapter['limits'], 'by_category':adapter.get('by_category'), 'adapter_path':str(ADAPTER), 'review':'Initial development adapter. Preview and explicit acceptance remain required. Known instruction failures are retained in adapter-evaluation.json.'}
    (ADAPTER / 'approved.json').write_text(json.dumps(record, indent=2))
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
