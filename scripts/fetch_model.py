import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ["HF_HOME"] = str(ROOT / ".cache" / "huggingface")
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

from huggingface_hub import HfApi, snapshot_download

repo = "mlx-community/Qwen3-4B-Instruct-2507-4bit"
revision = "50d427756c6b1b2fe0c0a10f67fbda1fc8e82c1b"
destination = ROOT / "data/models/qwen3-4b"
snapshot_download(repo, revision=revision, local_dir=destination, allow_patterns=["*.json", "*.jinja", "*.safetensors", "*.txt", "*.model", "README.md", "LICENSE*"], max_workers=3)
(destination / "rdx-source.json").write_text(json.dumps({"repository": repo, "revision": revision}, indent=2))
print(f"Model downloaded: {repo} at {revision}", flush=True)
