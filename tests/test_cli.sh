#!/bin/sh
set -eu

script=youtube-shorts-traffic-collector.py
python3 -m py_compile "$script"
python3 "$script" --help >/dev/null
python3 tests/test_logic.py

if python3 "$script" --watch-prob 2 >/dev/null 2>&1; then
    printf '%s\n' "Invalid watch probability was accepted." >&2
    exit 1
fi

if python3 "$script" --fallback-duration 60 --max-duration 30 >/dev/null 2>&1; then
    printf '%s\n' "Invalid duration range was accepted." >&2
    exit 1
fi

printf '%s\n' "YouTube Shorts collector CLI tests passed."
