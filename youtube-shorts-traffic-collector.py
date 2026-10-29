#!/usr/bin/env python3
"""Capture VPN traffic while Selenium watches or skips YouTube Shorts."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
import logging
import math
import os
from pathlib import Path
import random
import threading
import time

from scapy.all import sniff, wrpcap
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as expected
from selenium.webdriver.support.ui import WebDriverWait


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("youtube_shorts_traffic_collector")


@dataclass(frozen=True)
class Behavior:
    """Timing and navigation parameters for one Shorts session."""

    page_load_wait_s: tuple[float, float] = (2.0, 4.5)
    between_actions_s: tuple[float, float] = (0.8, 2.5)
    watch_probability: float = 0.35
    half_watch_probability: float = 0.45
    fallback_duration_s: float = 30.0
    max_duration_s: float = 120.0
    full_watch_grace_s: float = 10.0
    idle_probability: float = 0.12
    idle_time_s: tuple[float, float] = (2.0, 6.0)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return parsed


def probability(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError("must be between 0.0 and 1.0")
    return parsed


def random_float(bounds: tuple[float, float]) -> float:
    return random.uniform(*bounds)


def build_driver(headless: bool, chromedriver_path: str | None) -> webdriver.Chrome:
    """Create the Chrome WebDriver used for the video workload."""

    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--mute-audio")
    options.add_argument("--lang=en-US")

    service = Service(chromedriver_path) if chromedriver_path else Service()
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_window_size(1280, 720)
    return driver


def capture_packets(
    interface: str,
    filename: Path,
    bpf_filter: str,
    stop_event: threading.Event,
    errors: list[Exception],
    poll_timeout_s: float = 1.0,
) -> None:
    """Capture packets until signaled and report failures to the main thread."""

    logger.info("Starting capture on interface=%s | filter='%s'", interface, bpf_filter)
    captured_packets: list = []

    try:
        # Repeated timeouts allow the thread to stop even when no packets arrive.
        while not stop_event.is_set():
            packets = sniff(iface=interface, filter=bpf_filter, timeout=poll_timeout_s)
            captured_packets.extend(packets)

        wrpcap(str(filename), captured_packets)
        logger.info(
            "Capture finished. Saved %d packets to %s",
            len(captured_packets),
            filename,
        )
    except Exception as error:  # Scapy exposes several backend-specific errors.
        errors.append(error)
        stop_event.set()
        logger.exception("Packet capture failed: %s", error)


def maybe_idle(behavior: Behavior) -> None:
    if random.random() < behavior.idle_probability:
        duration = random_float(behavior.idle_time_s)
        logger.info("  Idle for %.2f seconds", duration)
        time.sleep(duration)


def open_shorts(driver: webdriver.Chrome, behavior: Behavior) -> None:
    """Open YouTube Shorts and wait until a video element is available."""

    logger.info("Opening YouTube Shorts")
    driver.get("https://www.youtube.com/shorts")
    time.sleep(random_float(behavior.page_load_wait_s))

    try:
        cookie_button = WebDriverWait(driver, 5).until(
            expected.element_to_be_clickable(
                (
                    By.XPATH,
                    "//button[contains(., 'Accept') or contains(., 'Aceitar')]",
                )
            )
        )
        cookie_button.click()
        time.sleep(1.5)
    except (TimeoutException, WebDriverException):
        logger.debug("No cookie consent button was handled")

    WebDriverWait(driver, 20).until(
        expected.presence_of_element_located((By.TAG_NAME, "video"))
    )
    logger.info("YouTube Shorts loaded")


def ensure_video_playing(driver: webdriver.Chrome) -> None:
    driver.execute_script(
        """
        const video = document.querySelector('video');
        if (video) {
            video.muted = true;
            try { video.play(); } catch (error) {}
        }
        """
    )


def read_video_number(driver: webdriver.Chrome, property_name: str) -> float:
    value = driver.execute_script(
        """
        const video = document.querySelector('video');
        return video ? video[arguments[0]] : 0;
        """,
        property_name,
    )
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) and parsed >= 0 else 0.0


def next_short(driver: webdriver.Chrome) -> None:
    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.PAGE_DOWN)


def watch_short(driver: webdriver.Chrome, behavior: Behavior, watch_half: bool) -> None:
    """Watch approximately half or all of the current Short."""

    ensure_video_playing(driver)
    duration = read_video_number(driver, "duration")
    if duration <= 0 or duration > behavior.max_duration_s:
        duration = behavior.fallback_duration_s

    if watch_half:
        watch_time = duration * 0.5 * random.uniform(0.8, 1.2)
        logger.info("  Watching approximately half: %.1f seconds", watch_time)
        time.sleep(watch_time)
        return

    logger.info("  Watching the full Short: up to %.1f seconds", duration)
    started_at = time.monotonic()
    maximum_wait = duration + behavior.full_watch_grace_s
    while read_video_number(driver, "currentTime") < duration - 0.5:
        if time.monotonic() - started_at > maximum_wait:
            logger.warning("  Full-watch timeout reached")
            break
        time.sleep(1.0)


def simulate_shorts(
    short_count: int,
    behavior: Behavior,
    headless: bool,
    chromedriver_path: str | None,
) -> None:
    """Generate the configured Shorts browsing workload."""

    driver = build_driver(headless, chromedriver_path)
    try:
        open_shorts(driver, behavior)
        maybe_idle(behavior)

        for short_index in range(short_count):
            logger.info("Short %d/%d", short_index + 1, short_count)
            if random.random() < behavior.watch_probability:
                watch_short(
                    driver,
                    behavior,
                    watch_half=random.random() < behavior.half_watch_probability,
                )
            else:
                logger.info("  Skipping")

            if short_index + 1 < short_count:
                next_short(driver)
                time.sleep(random_float(behavior.between_actions_s))
                maybe_idle(behavior)
    finally:
        driver.quit()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture VPN traffic while watching or skipping YouTube Shorts."
    )
    parser.add_argument("-i", "--interface", default="enp0s8", help="Network interface to capture")
    parser.add_argument("--filter", default="udp port 1194", help="BPF capture filter")
    parser.add_argument("-c", "--cycles", type=positive_int, default=5, help="Capture cycles")
    parser.add_argument("-p", "--shorts", type=positive_int, default=20, help="Shorts per cycle")
    parser.add_argument("--outdir", default="captures", help="PCAP output directory")
    parser.add_argument("--prefix", default="shorts_traffic", help="PCAP filename prefix")
    parser.add_argument("--headless", action="store_true", help="Run Chrome without a visible window")
    parser.add_argument("--chromedriver-path", help="Path to a ChromeDriver executable")
    parser.add_argument("--watch-prob", type=probability, default=0.35, help="Probability of watching a Short")
    parser.add_argument("--half-watch-prob", type=probability, default=0.45, help="Probability of a half watch")
    parser.add_argument("--max-duration", type=positive_float, default=120.0, help="Maximum accepted video duration")
    parser.add_argument("--fallback-duration", type=positive_float, default=30.0, help="Fallback video duration")
    parser.add_argument("--seed", type=int, help="Seed for repeatable random decisions")
    args = parser.parse_args(argv)

    if args.fallback_duration > args.max_duration:
        parser.error("--fallback-duration cannot exceed --max-duration")
    if not args.prefix:
        parser.error("--prefix cannot be empty")
    return args


def run_cycle(
    args: argparse.Namespace,
    behavior: Behavior,
    cycle_number: int,
) -> None:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(args.outdir) / (
        f"{args.prefix}_{timestamp}_c{cycle_number:03d}.pcap"
    )
    stop_event = threading.Event()
    capture_errors: list[Exception] = []
    capture_thread = threading.Thread(
        target=capture_packets,
        args=(args.interface, output_path, args.filter, stop_event, capture_errors),
    )

    capture_thread.start()
    try:
        time.sleep(2.0)
        simulate_shorts(
            short_count=args.shorts,
            behavior=behavior,
            headless=args.headless,
            chromedriver_path=args.chromedriver_path,
        )
    finally:
        stop_event.set()
        logger.info("Waiting for the capture thread to finish")
        capture_thread.join()

    if capture_errors:
        raise RuntimeError("The packet capture did not complete successfully") from capture_errors[0]


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)

    if os.geteuid() != 0:
        logger.error("Packet capture requires root privileges; run this command with sudo")
        return 1

    random.seed(args.seed)
    Path(args.outdir).mkdir(parents=True, exist_ok=True)
    behavior = Behavior(
        watch_probability=args.watch_prob,
        half_watch_probability=args.half_watch_prob,
        max_duration_s=args.max_duration,
        fallback_duration_s=args.fallback_duration,
    )

    try:
        for cycle_index in range(args.cycles):
            logger.info("Cycle %d/%d", cycle_index + 1, args.cycles)
            run_cycle(args, behavior, cycle_index + 1)
            logger.info("Cycle %d completed successfully", cycle_index + 1)
            if cycle_index + 1 < args.cycles:
                time.sleep(3.0)
    except KeyboardInterrupt:
        logger.warning("Interrupted by the user")
        return 130
    except Exception as error:
        logger.exception("Collection failed: %s", error)
        return 1

    logger.info("All capture cycles completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
