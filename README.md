# YouTube Shorts VPN Traffic Collector

Captures VPN-encrypted network traffic while Selenium generates a configurable watch-and-skip workload on YouTube Shorts. The resulting PCAP files are intended for authorized encrypted-traffic research and dataset construction.

> [!IMPORTANT]
> Capture only traffic and networks for which you have explicit authorization. Packet capture normally requires root privileges.

## How it works

Each cycle starts two coordinated activities:

1. Scapy captures packets from a selected interface using a BPF filter.
2. Selenium opens YouTube Shorts and chooses whether to skip, watch half, or watch all of each video.

The capture loop uses short polling intervals so it can stop even when the interface is idle. Capture failures are propagated to the main process and produce a nonzero exit status.

## Requirements

- Linux
- Python 3.10 or newer
- Google Chrome or Chromium
- A compatible ChromeDriver available on `PATH`
- Root privileges for packet capture

Create an isolated environment and install the Python packages:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Check the browser tools before collecting data:

```bash
chromedriver --version
google-chrome --version
```

## Usage

```bash
sudo .venv/bin/python youtube-shorts-traffic-collector.py [OPTIONS]
```

Common options:

| Option | Default | Description |
| --- | --- | --- |
| `-i`, `--interface` | `enp0s8` | Network interface to capture |
| `--filter` | `udp port 1194` | BPF capture filter |
| `-c`, `--cycles` | `5` | Number of capture cycles |
| `-p`, `--shorts` | `20` | Shorts processed per cycle |
| `--outdir` | `captures` | PCAP output directory |
| `--headless` | disabled | Run Chrome without a visible window |
| `--seed` | unset | Seed for repeatable random decisions |

Behavior options:

| Option | Description |
| --- | --- |
| `--watch-prob` | Probability of watching instead of skipping (`0.0`–`1.0`) |
| `--half-watch-prob` | Probability that a watched Short is watched halfway |
| `--max-duration` | Longest reported duration accepted from the player |
| `--fallback-duration` | Duration used when the player reports no valid duration |

Run `python youtube-shorts-traffic-collector.py --help` for the complete reference.

Example:

```bash
sudo .venv/bin/python youtube-shorts-traffic-collector.py \
  --interface enp0s8 \
  --cycles 3 \
  --shorts 20 \
  --watch-prob 0.6 \
  --half-watch-prob 0.4 \
  --max-duration 120 \
  --fallback-duration 30 \
  --seed 2026 \
  --headless
```

PCAP files are written as `captures/shorts_traffic_<timestamp>_c<cycle>.pcap`.

> [!NOTE]
> A seed repeats the script's pseudo-random choices, but it cannot make live web content, browser timing, or network conditions deterministic. Record the command, software versions, VPN configuration, and collection time with every dataset.

## Validation

```bash
sh tests/test_cli.sh
```

The validation checks Python syntax, command-line help, and rejection of invalid values. It does not start a browser or capture packets.

## Project structure

```text
.
├── youtube-shorts-traffic-collector.py
├── requirements.txt
├── tests/test_cli.sh
└── captures/                         # Generated locally; ignored by Git
```
