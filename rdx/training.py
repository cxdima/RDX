"""Run a reproducible local adapter training job and retain the complete log.

The adapter directory comes from RDX_ADAPTER so a new version can be trained
while the active one stays in place and protected.
"""
import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time

from .model import ADAPTER, DATA, MODEL, ROOT, SYSTEM


def longest_example(path) -> int:
    """The longest example in the dataset, in tokens the model will actually see."""
    import json

    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(str(MODEL))
    longest = 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        text = tokenizer.apply_chat_template(json.loads(line)["messages"], tokenize=False)
        longest = max(longest, len(tokenizer(text)["input_ids"]))
    return longest


def main(argv: list[str] | None = None):
    # The protection check runs before anything else, including argument
    # parsing, so no invocation can slip past it.
    if (ADAPTER / "approved.json").exists():
        raise RuntimeError("The active adapter is protected. Set RDX_ADAPTER to a new version before training again.")
    parser = argparse.ArgumentParser()
    parser.add_argument("--iters", type=int, default=600)
    parser.add_argument("--batch-size", type=int, default=2)
    parser.add_argument("--layers", type=int, default=8)
    parser.add_argument("--rank", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=5e-5)
    parser.add_argument("--warmup", type=int, default=40)
    # Examples cluster near 1616 tokens; a tight cap keeps peak memory down.
    parser.add_argument("--max-seq-length", type=int, default=1536)
    parser.add_argument("--no-grad-checkpoint", action="store_true")
    args = parser.parse_args(argv)
    directory = DATA / "training"
    directory.mkdir(parents=True, exist_ok=True)
    config = {
        "model": str(MODEL), "train": True, "data": str(directory), "fine_tune_type": "lora", "num_layers": args.layers, "batch_size": args.batch_size, "iters": args.iters, "val_batches": 8, "learning_rate": args.learning_rate,
        # Constant 1e-4 diverged at iteration 120 (loss 0.374 -> 6.848).
        # Warm up, then decay, so a late batch cannot throw the run.
        "lr_schedule": {"name": "cosine_decay", "warmup": args.warmup, "warmup_init": 1e-6, "arguments": [args.learning_rate, args.iters, args.learning_rate / 10]}, "steps_per_report": 20, "steps_per_eval": 100, "adapter_path": str(ADAPTER), "save_every": 100, "max_seq_length": args.max_seq_length, "grad_checkpoint": not args.no_grad_checkpoint, "mask_prompt": True, "seed": 2026, "lora_parameters": {"rank": args.rank, "dropout": 0.0, "scale": 32.0}}
    longest = longest_example(directory / "train.jsonl")
    if longest > args.max_seq_length:
        # A run that trains on truncated answers looks exactly like a run: the
        # loss is computed only over the assistant's JSON, so when the cut lands
        # there the target is empty and the validation loss comes back nan.
        # This has happened twice. It cannot happen quietly again.
        raise RuntimeError(
            f"The longest training example is {longest} tokens and the cap is {args.max_seq_length}. "
            f"Truncation would fall on the answer, which is the only part the loss covers. "
            f"Re-run with --max-seq-length {((longest + 127) // 128) * 128} or shorten the system prompt."
        )
    import yaml
    config_path = directory / "train.yaml"
    config_path.write_text(yaml.safe_dump(config))
    started = time.time()
    status = {"state": "training", "step": 0, "steps": args.iters, "started": started, "adapter": str(ADAPTER)}
    status_path = directory / "status.json"

    def save():
        temporary = status_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(status))
        temporary.replace(status_path)

    # Read at the start, not the end: the dataset on disk can change while a
    # run is in flight, and a record of data the model never saw is worse than
    # no record.
    dataset_report = json.loads((directory / "dataset.json").read_text())
    save()
    environment = {**os.environ, "HF_HUB_OFFLINE": "1", "HF_HUB_DISABLE_TELEMETRY": "1", "TOKENIZERS_PARALLELISM": "false", "PYTHONUNBUFFERED": "1"}
    with (directory / "train.log").open("w") as log:
        # Its own process group, so terminating this script takes the trainer
        # with it. An orphaned trainer holds gigabytes and starves everything.
        process = subprocess.Popen([sys.executable, "-m", "mlx_lm.lora", "--config", str(config_path)], cwd=ROOT, env=environment, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True)

        def stop(*_):
            raise KeyboardInterrupt

        for received in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(received, stop)
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
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            status["state"] = "interrupted"
            save()
            raise
    status.update(state="trained" if code == 0 else "failed", elapsed_seconds=round(time.time() - started), exit_code=code)
    save()
    if code == 0:
        (ADAPTER / "training-record.json").write_text(json.dumps({
            "config": config,
            "status": status,
            "base": json.loads((MODEL / "rdx-source.json").read_text()),
            "dataset": dataset_report,
            "longest_example_tokens": longest,
            # Every example embeds the system prompt, so an adapter trained
            # against one prompt and used with another is quietly mismatched.
            # promote.py refuses to activate an adapter whose prompt has moved.
            "system_sha256": hashlib.sha256(SYSTEM.encode()).hexdigest(),
        }, indent=2))
    sys.exit(code)


if __name__ == "__main__":
    main()
