"""Domain events (19 §5): delivery, dedupe of subscribers, failure isolation."""
import sys
from collections import defaultdict
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import events  # noqa: E402


def test_match_finished_delivery_and_failing_subscriber_is_isolated(monkeypatch, caplog):
    monkeypatch.setattr(events, "_SUBSCRIBERS", defaultdict(list))
    seen = []

    def boom(payload):
        raise RuntimeError("subscriber down")

    events.subscribe("match_finished", boom)
    events.subscribe("match_finished", seen.append)
    events.subscribe("match_finished", seen.append)   # duplicate subscription ignored
    payload = SimpleNamespace(kind="pve")
    events.emit("match_finished", payload)
    assert seen == [payload]
    assert "subscriber down" in caplog.text


def test_growth_subscribes_to_match_finished():
    import growth
    assert growth._on_match_finished in events._SUBSCRIBERS["match_finished"]
