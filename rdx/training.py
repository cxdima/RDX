"""Run a reproducible local adapter training job and retain the complete log."""
import json
import os
import re
import subprocess
import sys
import time

from .model import ADAPTER, DATA, MODEL, ROOT


def main():
    if (ADAPTER / "approved.json").exists():
        raise RuntimeError("The active adapter is protected. Configure a new adapter version before training again.")
    directory = DATA / "training"
    directory.mkdir(parents=True, exist_ok=True)
    config = {"model": str(MODEL), "train": True, "data": str(directory), "fine_tune_type": "lora", "num_layers": 4, "batch_size": 1, "iters": 120, "val_batches": 6, "learning_rate": 0.0001, "steps_per_report": 10, "steps_per_eval": 40, "adapter_path": str(ADAPTER), "save_every": 40, "max_seq_length": 2048, "grad_checkpoint": True, "mask_prompt": True, "seed": 2026, "lora_parameters": {"rank": 8, "dropout": 0.0, "scale": 16.0}}
    import yaml
    config_path = directory / "train.yaml"
    config_path.write_text(yaml.safe_dump(config))
    started = time.time()
    status = {"state": "training", "step": 0, "steps": 120, "started": started}
    status_path = directory / "status.json"

    def save():
        temporary = status_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(status))
        temporary.replace(status_path)

    save()
    environment = {**os.environ, "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "TOKENIZERS_PARALLELISM": "false", "PYTHONUNBUFFERED": "1"}
    with (directory / "train.log").open("w") as log:
        process = subprocess.Popen([sys.executable, "-m", "mlx_lm.lora", "--config", str(config_path)], cwd=ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        try:
            for line in process.stdout:
                log.write(line)
                log.flush()
                print(line, end="", flush=True)
                step = re.search(r"Iter (\d+)", line)
                if step:
                    status["step"] = int(step[1])
                    status["last_report"] = line.strip()
                    save()
            code = process.wait()
        except BaseException:
            process.terminate()
            process.wait()
            status["state"] = "interrupted"
            save()
            raise
    status.update(state="trained" if code == 0 else "failed", elapsed_seconds=round(time.time() - started), exit_code=code)
    save()
    if code == 0:
        (ADAPTER / "training-record.json").write_text(json.dumps({"config": config, "status": status, "base": json.loads((MODEL / "rdx-source.json").read_text()), "dataset": json.loads((directory / "dataset.json").read_text())}, indent=2))
    sys.exit(code)


if __name__ == "__main__":
    main()
