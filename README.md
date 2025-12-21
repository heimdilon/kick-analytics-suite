# Kick Analytics Suite

This folder contains two programs that monitor Kick chat activity and viewer counts.

Vibe coded with Codex.

- kick_live_cli.py: a Python CLI that logs live stats and messages to JSONL, with optional screenshots via ffmpeg.
- kick-live-analytics.html: a standalone web dashboard for live charts, chat feed, exports, and in-browser screenshots.

## Contents

- kick_live_cli.py
- kick-live-analytics.html
- README.md

## Requirements

CLI
- Python 3.9+
- websockets (pip install websockets)
- Optional: ffmpeg on PATH for screenshots (or pass --ffmpeg-path)

Web
- A modern browser (Chrome/Edge/Safari)
- HLS.js (loaded via CDN in the HTML)
- A Kick API proxy if CORS blocks direct Kick API access

## Quick Start

CLI
1) Install dependencies:
   python -m pip install websockets
2) Run:
   python kick_live_cli.py run --channel xqc

Web
1) Open kick-live-analytics.html in a browser.
2) Enter a channel (or a chatroom id), then Connect.

## CLI Usage

Run (live stats)
- python kick_live_cli.py run --channel xqc
- python kick_live_cli.py run --chatroom-id 668
- python kick_live_cli.py run --channel xqc --proxy http://localhost:3456

Optional run flags
- --duration N            Stop after N seconds
- --inactivity N          Stop after N seconds without messages
- --log PATH              Write JSONL log to PATH
- --screenshot-interval N Capture a screenshot every N seconds
- --screenshot-on-snapshot Capture on each 1s snapshot tick
- --screenshot-dir PATH   Directory for screenshots
- --screenshot-max N      Max screenshots to keep
- --screenshot-format jpg|png
- --screenshot-embed      Embed base64 thumbnail in JSONL
- --screenshot-embed-width N
- --stream-url URL        Explicit m3u8 stream URL
- --ffmpeg-path PATH      Explicit ffmpeg path

Export
- python kick_live_cli.py export-csv --input session.jsonl
- python kick_live_cli.py export-messages --input session.jsonl

## Web App Features

- Live viewer count, messages per minute/second, unique chatters
- Top chatters (top 3)
- Chart window selection (including All stream)
- Recent chat feed
- Export session CSV, messages CSV, and session JSONL
- Optional screenshots from a stream URL:
  - Interval-based or per-snapshot capture
  - Preview + download
  - Optional base64 thumbnail embed in JSONL

## Notes on Viewer Count and CORS

- The Kick API may be blocked by CORS in the browser.
- If viewer count or stream URL is unavailable, run a local proxy (see kick-chat-analytics/server.py in the repo root) and set the proxy field in the web app.

## Data Formats

JSONL entries (CLI and Web JSONL export)
- session_start: session metadata
- snapshot: per-second aggregates
- message: raw chat messages

CSV export fields
- timestamp, channel, messages_per_minute, messages_per_second, unique_per_minute, unique_per_second, total_messages, unique_total, viewer_count, screenshot_path

## Troubleshooting

- If screenshots show CORS errors, try a different stream URL or use a proxy.
- If HLS is not supported, use Chrome/Edge or provide a native HLS source.
- For manual chatroom ID, you can use the Chatroom ID field in the web app or pass --chatroom-id in the CLI.
