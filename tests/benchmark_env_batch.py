"""Compare scalar IPC with fused batch IPC on identical official game states.

Run: .venv/bin/python tests/benchmark_env_batch.py --output /tmp/batch.json
No HTTP, training or user traffic; reports median local latency, not capacity.
"""
import argparse
import json
from pathlib import Path
import statistics
import sys
import time

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from ugc_proxy import ProxyAdapter
import ugc_runner


def benchmark():
    results = []
    try:
        for directory in sorted((ROOT / "packaged-games").iterdir()):
            if not (directory / "game.yaml").exists():
                continue
            meta = yaml.safe_load((directory / "game.yaml").read_text())
            adapter = ProxyAdapter(meta["slug"], directory, meta)
            info = adapter.info()
            mode, rewards = info["obs_modes"][0], info["default_rewards"]
            for n in (16, 256):
                states = [r["state"] for r in adapter.new_batch(list(range(n)))]
                actions = [adapter.sample_action(s) for s in states]
                def scalar():
                    result = []
                    for s, a in zip(states, actions):
                        adapter.validate_state(s)
                        adapter.validate_action(a, s)
                        nxt = adapter.step_state(s, a, rewards)
                        result.append((nxt, adapter.obs(nxt, mode)))
                    return result
                def batch():
                    return [(r["state"], r["obs"]) for r in adapter.step_batch(states, actions, rewards, mode)]
                assert scalar() == batch()
                timings = {"scalar": [], "batch": []}
                for _ in range(5):
                    for name, call in (("scalar", scalar), ("batch", batch)):
                        start = time.perf_counter()
                        call()
                        timings[name].append((time.perf_counter() - start) * 1000)
                old = statistics.median(timings["scalar"])
                new = statistics.median(timings["batch"])
                results.append({"game": meta["slug"], "batch_size": n,
                                "scalar_ipc_calls": n * 4, "batch_ipc_calls": 1,
                                "scalar_ms": round(old, 3), "batch_ms": round(new, 3),
                                "speedup": round(old / new, 2)})
    finally:
        ugc_runner.stop_all()
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = benchmark()
    text = json.dumps(result, indent=2)
    print(text)
    if args.output:
        args.output.write_text(text + "\n")
