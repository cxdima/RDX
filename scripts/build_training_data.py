"""Entry point for regenerating the instruction dataset."""
import json

from rdx.dataset.build import build

if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
