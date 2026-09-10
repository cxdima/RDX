import json
import os
import sys

os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from mlx_lm import generate, load
from mlx_lm.sample_utils import make_sampler

from .model import ADAPTER, MODEL, SYSTEM


def main():
    model, tokenizer = load(str(MODEL), adapter_path=str(ADAPTER) if sys.argv[-1] == "adapter" else None)
    for line in sys.stdin:
        try:
            data = json.loads(line)
            messages = [{"role": "system", "content": SYSTEM}]
            for previous in data.get("previous", []):
                messages.append({"role": previous["role"], "content": previous["content"]})
            messages.append({"role": "user", "content": json.dumps(data["context"], separators=(",", ":")) + "\nRequest: " + data["request"]})
            prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
            result = generate(model, tokenizer, prompt=prompt, max_tokens=900, sampler=make_sampler(temp=0.15), verbose=False)
            print(json.dumps({"text": result}), flush=True)
        except Exception as error:
            print(json.dumps({"error": str(error)}), flush=True)


if __name__ == "__main__":
    main()
