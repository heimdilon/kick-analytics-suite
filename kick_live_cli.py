import argparse
import asyncio
import base64
import json
import os
import sys
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from shutil import which
from subprocess import PIPE
from urllib.request import urlopen, Request

PUSHER_URL = "wss://ws-us2.pusher.com/app/32cbd69e4b950bf97679?protocol=7&client=py&version=1.0&flash=false"


def fetch_json(url, timeout=10):
    req = Request(url, headers={"User-Agent": "kick-cli"})
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read().decode("utf-8")
    return json.loads(data)


def resolve_chatroom_id(channel, proxy=None):
    if proxy:
        base = proxy.rstrip("/")
        data = fetch_json(f"{base}/channel?name={channel}")
        return data.get("chatroomId"), None

    data = fetch_json(f"https://kick.com/api/v2/channels/{channel}")
    chatroom_id = None
    viewer_count = None
    if isinstance(data, dict):
        chatroom = data.get("chatroom") or {}
        chatroom_id = chatroom.get("id")
        livestream = data.get("livestream") or {}
        viewer_count = livestream.get("viewer_count", livestream.get("viewerCount"))
    return chatroom_id, viewer_count


def fetch_viewer_count(channel):
    data = fetch_json(f"https://kick.com/api/v2/channels/{channel}")
    if isinstance(data, dict):
        livestream = data.get("livestream") or {}
        return livestream.get("viewer_count", livestream.get("viewerCount"))
    return None


def resolve_stream_url(channel):
    data = fetch_json(f"https://kick.com/api/v2/channels/{channel}")
    if not isinstance(data, dict):
        return None
    livestream = data.get("livestream") or {}
    candidates = [
        livestream.get("playback_url"),
        livestream.get("playbackUrl"),
        livestream.get("hls"),
        data.get("playback_url"),
        data.get("playbackUrl"),
    ]
    for value in candidates:
        if value:
            return value
    return None


def timestamp_label():
    return datetime.utcnow().strftime("%Y%m%d-%H%M%S")


def resolve_ffmpeg_path(explicit_path=None):
    if explicit_path:
        return explicit_path
    found = which("ffmpeg")
    if found:
        return found
    user_choco = Path(os.environ.get("LOCALAPPDATA", "")) / "Chocolatey" / "bin" / "ffmpeg.exe"
    if user_choco.exists():
        return str(user_choco)
    system_choco = Path("C:/ProgramData/chocolatey/bin/ffmpeg.exe")
    if system_choco.exists():
        return str(system_choco)
    return None


def jsonl_write(fp, record):
    fp.write(json.dumps(record, ensure_ascii=False) + "\n")
    fp.flush()


def format_number(value):
    if value is None:
        return "n/a"
    return f"{value:,}"

def color(text, code, enabled=True):
    if not enabled:
        return text
    return f"\x1b[{code}m{text}\x1b[0m"

def pad(text, width):
    text = str(text)
    if len(text) >= width:
        return text[:width]
    return text + (" " * (width - len(text)))


async def run_live(args):
    try:
        import websockets
    except ImportError:
        print("Missing dependency: websockets. Install with: pip install websockets")
        return 1

    if not args.channel and not args.chatroom_id:
        print("Provide --channel or --chatroom-id")
        return 1

    channel = (args.channel or "").lower()
    viewer_count = None

    if args.chatroom_id:
        chatroom_id = int(args.chatroom_id)
    else:
        try:
            chatroom_id, viewer_count = resolve_chatroom_id(channel, args.proxy)
        except Exception as exc:
            print(f"Failed to resolve channel: {exc}")
            return 1

    if not chatroom_id:
        print("Chatroom id not found")
        return 1

    log_path = Path(args.log) if args.log else None
    if not log_path:
        stamp = timestamp_label()
        name = channel or f"chatroom-{chatroom_id}"
        log_path = Path(f"kick-session-{name}-{stamp}.jsonl")

    screenshot_interval = args.screenshot_interval
    screenshot_on_snapshot = args.screenshot_on_snapshot
    screenshot_format = (args.screenshot_format or "jpg").lower()
    screenshot_max = args.screenshot_max
    screenshot_embed = args.screenshot_embed
    screenshot_embed_width = args.screenshot_embed_width
    screenshot_dir = None
    stream_url = None
    ffmpeg_path = None
    if screenshot_on_snapshot and screenshot_interval:
        print("Use either --screenshot-interval or --screenshot-on-snapshot, not both.")
        return 1
    if screenshot_format not in {"jpg", "png"}:
        print("Screenshot format must be jpg or png.")
        return 1
    if screenshot_max is not None and screenshot_max <= 0:
        print("Screenshot max must be a positive number.")
        return 1
    if screenshot_embed_width is not None and screenshot_embed_width <= 0:
        print("Screenshot embed width must be a positive number.")
        return 1
    if screenshot_interval or screenshot_on_snapshot:
        if screenshot_interval is not None and screenshot_interval <= 0:
            print("Screenshot interval must be a positive number of seconds.")
            return 1
        stream_url = args.stream_url or (channel and resolve_stream_url(channel))
        if not stream_url:
            print("Screenshot enabled but stream URL is missing. Use --stream-url.")
            return 1
        if args.screenshot_dir:
            screenshot_dir = Path(args.screenshot_dir)
        else:
            screenshot_dir = log_path.with_name(log_path.stem + "-screenshots")
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        ffmpeg_path = resolve_ffmpeg_path(args.ffmpeg_path)
        if not ffmpeg_path:
            print("ffmpeg not found. Install it or pass --ffmpeg-path to the executable.")
            return 1

    events = deque()
    screenshot_paths = deque()
    unique_users = set()
    user_counts = {}
    total_messages = 0
    current_viewers = viewer_count
    latest_screenshot = None
    latest_screenshot_b64 = None
    lock = asyncio.Lock()
    start_time = time.time()
    last_message_time = start_time
    stop_event = asyncio.Event()

    def snapshot(now, per_min, per_sec, uniq_min, uniq_sec):
        return {
            "type": "snapshot",
            "ts": datetime.utcnow().isoformat() + "Z",
            "channel": channel or "manual",
            "messages_per_minute": per_min,
            "messages_per_second": per_sec,
            "unique_per_minute": uniq_min,
            "unique_per_second": uniq_sec,
            "total_messages": total_messages,
            "unique_total": len(unique_users),
            "viewer_count": current_viewers,
            "screenshot_path": latest_screenshot,
            "screenshot_base64": latest_screenshot_b64 if screenshot_embed else None,
        }

    use_color = sys.stdout.isatty()
    print(f"Logging to {log_path}")

    with log_path.open("w", encoding="utf-8") as fp:
        jsonl_write(fp, {
            "type": "session_start",
            "ts": datetime.utcnow().isoformat() + "Z",
            "channel": channel or "manual",
            "chatroom_id": chatroom_id,
        })

        async def poll_viewers():
            nonlocal current_viewers
            if not channel:
                return
            while not stop_event.is_set():
                try:
                    count = fetch_viewer_count(channel)
                    async with lock:
                        current_viewers = count
                except Exception:
                    async with lock:
                        current_viewers = None
                await asyncio.sleep(20)

        async def stats_loop():
            screenshot_task = None
            while not stop_event.is_set():
                now = time.time()
                async with lock:
                    while events and events[0][0] < now - 60:
                        events.popleft()
                    per_min = len(events)
                    per_sec = sum(1 for t, _ in events if t >= now - 1)
                    uniq_min = len({u for _, u in events})
                    uniq_sec = len({u for t, u in events if t >= now - 1})
                    msg_total = total_messages
                    uniq_total = len(unique_users)
                    top_users = sorted(user_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]
                    top_display = ", ".join([f"{name}({count})" for name, count in top_users]) or "n/a"
                    viewers = current_viewers
                    last_msg = last_message_time

                viewers_text = pad(format_number(viewers), 9)
                msg_s = pad(f"{per_sec:.1f}", 6)
                msg_m = pad(per_min, 6)
                uniq_s = pad(uniq_sec, 6)
                uniq_m = pad(uniq_min, 6)
                total = pad(msg_total, 9)
                uniq_total = pad(uniq_total, 9)
                top_disp = pad(top_display, 32)

                line = (
                    color("viewers", "36", use_color) + "=" + color(viewers_text, "96", use_color) + "  "
                    + color("msg/s", "33", use_color) + "=" + color(msg_s, "93", use_color) + "  "
                    + color("msg/min", "33", use_color) + "=" + color(msg_m, "93", use_color) + "  "
                    + color("uniq/s", "35", use_color) + "=" + color(uniq_s, "95", use_color) + "  "
                    + color("uniq/min", "35", use_color) + "=" + color(uniq_m, "95", use_color) + "  "
                    + color("total", "32", use_color) + "=" + color(total, "92", use_color) + "  "
                    + color("uniq_total", "32", use_color) + "=" + color(uniq_total, "92", use_color) + "  "
                    + color("top", "34", use_color) + "=" + color(top_disp, "94", use_color)
                )
                sys.stdout.write("\r" + line + " " * 4)
                sys.stdout.flush()

                jsonl_write(fp, snapshot(now, per_min, per_sec, uniq_min, uniq_sec))

                if screenshot_on_snapshot and (screenshot_task is None or screenshot_task.done()):
                    screenshot_task = asyncio.create_task(capture_once())
                if args.inactivity and (now - last_msg) >= args.inactivity:
                    print(f"\nStopping after {args.inactivity}s inactivity.")
                    stop_event.set()
                    break
                if args.duration and (time.time() - start_time) >= args.duration:
                    stop_event.set()
                    break
                await asyncio.sleep(1)

        async def capture_once():
            nonlocal latest_screenshot, latest_screenshot_b64
            if not stream_url or not screenshot_dir:
                return
            ts = timestamp_label()
            filename = f"{(channel or f'chatroom-{chatroom_id}')}-{ts}.{screenshot_format}"
            output_path = screenshot_dir / filename
            cmd = [
                ffmpeg_path,
                "-y",
                "-loglevel",
                "error",
                "-i",
                stream_url,
                "-frames:v",
                "1",
                "-vf",
                "scale=-2:480",
                str(output_path),
            ]
            proc = None
            try:
                proc = await asyncio.create_subprocess_exec(*cmd, stdout=PIPE, stderr=PIPE)
                await asyncio.wait_for(proc.communicate(), timeout=15)
                if proc.returncode == 0:
                    async with lock:
                        latest_screenshot = str(output_path)
                        if screenshot_embed:
                            latest_screenshot_b64 = None
                        if screenshot_max:
                            screenshot_paths.append(output_path)
                            while len(screenshot_paths) > screenshot_max:
                                old_path = screenshot_paths.popleft()
                                try:
                                    old_path.unlink()
                                except Exception:
                                    pass
                if proc.returncode == 0 and screenshot_embed:
                    thumb_cmd = [
                        ffmpeg_path,
                        "-loglevel",
                        "error",
                        "-i",
                        str(output_path),
                        "-frames:v",
                        "1",
                        "-vf",
                        f"scale={screenshot_embed_width}:-2",
                        "-f",
                        "image2pipe",
                        "-vcodec",
                        "mjpeg",
                        "-",
                    ]
                    thumb_proc = await asyncio.create_subprocess_exec(
                        *thumb_cmd, stdout=PIPE, stderr=PIPE
                    )
                    stdout, _ = await asyncio.wait_for(thumb_proc.communicate(), timeout=10)
                    if thumb_proc.returncode == 0 and stdout:
                        async with lock:
                            latest_screenshot_b64 = base64.b64encode(stdout).decode("ascii")
            except FileNotFoundError:
                print("\nffmpeg not found. Install ffmpeg or disable screenshots.")
                stop_event.set()
                return
            except asyncio.TimeoutError:
                if proc:
                    proc.kill()
                    await proc.communicate()
            except Exception:
                pass

        async def capture_screenshots():
            while not stop_event.is_set():
                await capture_once()
                await asyncio.sleep(screenshot_interval)

        async def listen():
            nonlocal total_messages, last_message_time
            async with websockets.connect(PUSHER_URL) as ws:
                await ws.send(json.dumps({
                    "event": "pusher:subscribe",
                    "data": {"auth": "", "channel": f"chatrooms.{chatroom_id}.v2"},
                }))

                while not stop_event.is_set():
                    try:
                        message = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        payload = json.loads(message)
                    except asyncio.TimeoutError:
                        continue
                    except json.JSONDecodeError:
                        continue

                    if payload.get("event") != "App\\Events\\ChatMessageEvent":
                        continue

                    try:
                        data = json.loads(payload.get("data") or "{}")
                    except json.JSONDecodeError:
                        continue

                    now = time.time()
                    username = (data.get("sender") or {}).get("username") or "anon"
                    content = data.get("content") or ""

                    async with lock:
                        events.append((now, username))
                        total_messages += 1
                        unique_users.add(username)
                        user_counts[username] = user_counts.get(username, 0) + 1
                        last_message_time = now

                    jsonl_write(fp, {
                        "type": "message",
                        "ts": datetime.utcnow().isoformat() + "Z",
                        "channel": channel or "manual",
                        "username": username,
                        "message": content,
                    })

        tasks = [asyncio.create_task(stats_loop()), asyncio.create_task(listen())]
        if channel:
            tasks.append(asyncio.create_task(poll_viewers()))
        if screenshot_interval:
            tasks.append(asyncio.create_task(capture_screenshots()))
        if args.duration:
            async def duration_timer():
                await asyncio.sleep(args.duration)
                stop_event.set()
            tasks.append(asyncio.create_task(duration_timer()))

        try:
            await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            print("\nStopping...")
        finally:
            stop_event.set()
            for task in tasks:
                task.cancel()

    return 0


def export_csv(input_path, output_path):
    input_path = Path(input_path)
    output_path = Path(output_path) if output_path else input_path.with_suffix(".csv")

    rows = []
    with input_path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("type") != "snapshot":
                continue
            rows.append(record)

    if not rows:
        print("No snapshot data found")
        return 1

    header = [
        "timestamp",
        "channel",
        "messages_per_minute",
        "messages_per_second",
        "unique_per_minute",
        "unique_per_second",
        "total_messages",
        "unique_total",
        "viewer_count",
        "screenshot_path",
    ]

    with output_path.open("w", encoding="utf-8-sig", newline="") as fp:
        fp.write(",".join(header) + "\n")
        for row in rows:
            values = [
                row.get("ts", ""),
                row.get("channel", ""),
                str(row.get("messages_per_minute", "")),
                str(row.get("messages_per_second", "")),
                str(row.get("unique_per_minute", "")),
                str(row.get("unique_per_second", "")),
                str(row.get("total_messages", "")),
                str(row.get("unique_total", "")),
                "" if row.get("viewer_count") is None else str(row.get("viewer_count")),
                row.get("screenshot_path") or "",
            ]
            fp.write(",".join(values) + "\n")

    print(f"Wrote {output_path}")
    return 0


def export_messages(input_path, output_path):
    input_path = Path(input_path)
    output_path = Path(output_path) if output_path else input_path.with_name(input_path.stem + "-messages.csv")

    rows = []
    with input_path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("type") != "message":
                continue
            rows.append(record)

    if not rows:
        print("No message data found")
        return 1

    header = ["timestamp", "channel", "username", "message"]

    def csv_escape(value):
        if value is None:
            return ""
        text = str(value)
        if any(ch in text for ch in ["\"", ",", "\n"]):
            return "\"" + text.replace("\"", "\"\"") + "\""
        return text

    with output_path.open("w", encoding="utf-8-sig", newline="") as fp:
        fp.write(",".join(header) + "\n")
        for row in rows:
            values = [
                csv_escape(row.get("ts", "")),
                csv_escape(row.get("channel", "")),
                csv_escape(row.get("username", "")),
                csv_escape(row.get("message", "")),
            ]
            fp.write(",".join(values) + "\n")

    print(f"Wrote {output_path}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Kick chat analytics CLI", add_help=False)
    parser.add_argument("-h", "--help", "-help", action="help", help="Show this help message and exit")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Connect and print live stats")
    run.add_argument("--channel", help="Kick channel name")
    run.add_argument("--chatroom-id", help="Chatroom id")
    run.add_argument("--proxy", help="Proxy base url, e.g. http://localhost:3456")
    run.add_argument("--log", help="Path to session log JSONL")
    run.add_argument("--duration", type=int, help="Stop after N seconds")
    run.add_argument("--inactivity", type=int, help="Stop after N seconds without messages")
    run.add_argument("--screenshot-interval", type=int, help="Capture a 480p screenshot every N seconds")
    run.add_argument("--screenshot-on-snapshot", action="store_true", help="Capture a screenshot on each snapshot tick")
    run.add_argument("--screenshot-dir", help="Directory to write screenshots")
    run.add_argument("--screenshot-max", type=int, help="Max screenshots to keep (older files are deleted)")
    run.add_argument("--screenshot-format", choices=["jpg", "png"], default="jpg", help="Screenshot file format")
    run.add_argument("--screenshot-embed", action="store_true", help="Embed base64 thumbnail in JSON snapshots")
    run.add_argument("--screenshot-embed-width", type=int, default=160, help="Thumbnail width when embedding base64")
    run.add_argument("--stream-url", help="Explicit stream URL (m3u8) for screenshots")
    run.add_argument("--ffmpeg-path", help="Explicit path to ffmpeg executable")

    export_csv_cmd = sub.add_parser("export-csv", help="Export session stats to CSV")
    export_csv_cmd.add_argument("--input", required=True, help="Session JSONL input")
    export_csv_cmd.add_argument("--output", help="CSV output path")

    export_messages_cmd = sub.add_parser("export-messages", help="Export messages to CSV")
    export_messages_cmd.add_argument("--input", required=True, help="Session JSONL input")
    export_messages_cmd.add_argument("--output", help="CSV output path")

    argv = sys.argv[1:]
    help_flags = {"-h", "--help", "-help"}
    if len(argv) == 1 and argv[0] in help_flags:
        parser.print_help()
        print("\nRun command options:\n")
        run.print_help()
        print("\nExport CSV options:\n")
        export_csv_cmd.print_help()
        print("\nExport messages options:\n")
        export_messages_cmd.print_help()
        return 0

    args = parser.parse_args()

    if args.command == "run":
        return asyncio.run(run_live(args))
    if args.command == "export-csv":
        return export_csv(args.input, args.output)
    if args.command == "export-messages":
        return export_messages(args.input, args.output)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
