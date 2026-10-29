#!/usr/bin/env python3
"""Exercise collector behavior without opening a browser or capturing packets."""

import importlib.util
from pathlib import Path
import logging
import sys
import threading
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "youtube_shorts_traffic_collector",
    ROOT / "youtube-shorts-traffic-collector.py",
)
assert SPEC is not None and SPEC.loader is not None
collector = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = collector
SPEC.loader.exec_module(collector)

logging.disable(logging.CRITICAL)


def test_nonfinite_video_value() -> None:
    driver = MagicMock()
    driver.execute_script.return_value = float("nan")
    assert collector.read_video_number(driver, "duration") == 0.0


def test_exact_short_count() -> None:
    driver = MagicMock()
    behavior = collector.Behavior(
        page_load_wait_s=(0.0, 0.0),
        between_actions_s=(0.0, 0.0),
        watch_probability=0.0,
        idle_probability=0.0,
    )

    with (
        patch.object(collector, "build_driver", return_value=driver),
        patch.object(collector, "open_shorts"),
        patch.object(collector, "next_short") as advance,
        patch.object(collector.time, "sleep"),
    ):
        collector.simulate_shorts(3, behavior, headless=True, chromedriver_path=None)

    assert advance.call_count == 2, "The collector advanced after the final Short."
    driver.quit.assert_called_once()


def test_capture_error_propagation() -> None:
    stop_event = threading.Event()
    errors: list[Exception] = []

    with patch.object(collector, "sniff", side_effect=RuntimeError("capture failed")):
        collector.capture_packets(
            "test0",
            Path("unused.pcap"),
            "udp",
            stop_event,
            errors,
        )

    assert stop_event.is_set()
    assert len(errors) == 1
    assert isinstance(errors[0], RuntimeError)


if __name__ == "__main__":
    test_nonfinite_video_value()
    test_exact_short_count()
    test_capture_error_propagation()
    print("YouTube Shorts collector logic tests passed.")
