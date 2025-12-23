# Kick Analytics Suite

This folder contains a standalone web dashboard for monitoring Kick chat activity and viewer counts.

## Contents

- kick-live-analytics.html
- README.md

## Requirements

Web
- A modern browser (Chrome/Edge/Safari)
- HLS.js (loaded via CDN in the HTML)
- A Kick API proxy if CORS blocks direct Kick API access

## Quick Start

Web
1) Open kick-live-analytics.html in a browser.
2) Enter a channel (or a chatroom id), then Connect.

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
- If viewer count or stream URL is unavailable, run a local proxy and set the proxy field in the web app.

## Data Formats

JSONL entries (web JSONL export)
- session_start: session metadata
- snapshot: per-second aggregates
- message: raw chat messages

CSV export fields
- timestamp, channel, messages_per_minute, messages_per_second, unique_per_minute, unique_per_second, total_messages, unique_total, viewer_count, screenshot_path

## Troubleshooting

- If screenshots show CORS errors, try a different stream URL or use a proxy.
- If HLS is not supported, use Chrome/Edge or provide a native HLS source.
- For manual chatroom ID, you can use the Chatroom ID field in the web app.
