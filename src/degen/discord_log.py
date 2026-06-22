"""Discord channel ingest — pull Inspector Lee's analyses + charts into a local log.

The piece the copy-paste workflow keeps losing: a durable, queryable record of
what was said in the channel, with the charts saved next to the text.

Mirrors `iv_store.py`: SQLite at `data/discord_log.db` (gitignored), one row per
message, idempotent per `message_id`, CLI subcommands. This is a *scheduled pull*,
not a 24/7 gateway listener — it connects, fetches everything since the last
message it stored (or since `--since` for a backfill), downloads new image
attachments, tags tickers, and disconnects. Fits the same launchd-cron model as
the IV snapshot.

`message_id` is the spine: a future calls-ledger and catalyst calendar foreign-key
back to it, so every structured fact traces to the verbatim line that produced it.

Setup (one time):
  1. Create a bot application at https://discord.com/developers/applications
     and enable the **Message Content** privileged intent (Bot → Privileged
     Gateway Intents). Under 100 servers, no verification needed.
  2. Invite the bot to the server with read access to the target channels.
  3. Put the token in `.env` at the repo root:   DISCORD_BOT_TOKEN=...
  4. List the channel ids in `discord_channels.json`:  {"channels": [123, 456]}
     (both files are gitignored)

  uv run python -m degen.discord_log pull                       # since last stored
  uv run python -m degen.discord_log backfill --since 2026-01-01
  uv run python -m degen.discord_log recent --author "Inspector Lee" --days 7
  uv run python -m degen.discord_log digest --days 1            # markdown for the daily brief
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sqlite3
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

DB_PATH = Path("data/discord_log.db")
MEDIA_DIR = Path("data/discord_media")
CHANNELS_FILE = Path("discord_channels.json")
ENV_FILE = Path(".env")
TICKERS_FILE = Path("tickers.txt")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    message_id   TEXT PRIMARY KEY,
    channel_id   TEXT NOT NULL,
    channel_name TEXT,
    author_id    TEXT NOT NULL,
    author_name  TEXT NOT NULL,
    ts           TEXT NOT NULL,                  -- ISO8601 UTC
    content      TEXT NOT NULL,
    reply_to_id  TEXT,
    attachments  TEXT NOT NULL DEFAULT '[]',     -- JSON: [{filename,url,local_path,content_type}]
    tickers      TEXT NOT NULL DEFAULT '[]'      -- JSON: list[str]
);
CREATE INDEX IF NOT EXISTS idx_msg_author_ts  ON messages(author_id, ts);
CREATE INDEX IF NOT EXISTS idx_msg_channel_ts ON messages(channel_id, ts);
"""

# A cashtag ($ABVX) or a bare uppercase token; bare tokens are kept only if they
# match a ticker we already track, so prose words like "I" or "CEO" don't leak in.
_CASHTAG_RE = re.compile(r"\$([A-Za-z]{1,6})\b")
_BARE_RE = re.compile(r"\b([A-Z]{2,6})\b")


@dataclass(frozen=True, slots=True)
class StoredMessage:
    message_id: str
    channel_id: str
    channel_name: str | None
    author_id: str
    author_name: str
    ts: str
    content: str
    reply_to_id: str | None
    attachments: list[dict[str, str | None]]
    tickers: list[str]


def _connect(db_path: Path = DB_PATH) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.executescript(_SCHEMA)
    return conn


# ---------- config / secrets ----------


def _load_token() -> str:
    """Bot token from the DISCORD_BOT_TOKEN env var, falling back to a .env file."""
    tok = os.environ.get("DISCORD_BOT_TOKEN")
    if tok:
        return tok.strip()
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if line.startswith("DISCORD_BOT_TOKEN="):
                return line.split("=", 1)[1].strip().strip("'\"")
    raise RuntimeError(
        "no DISCORD_BOT_TOKEN — set the env var or add it to .env (see module docstring)"
    )


def _load_channels() -> list[int]:
    if not CHANNELS_FILE.exists():
        raise FileNotFoundError(
            f"no {CHANNELS_FILE} — create it with: {{\"channels\": [<channel_id>, ...]}}"
        )
    data = json.loads(CHANNELS_FILE.read_text())
    return [int(c) for c in data["channels"]]


def _known_tickers(path: Path = TICKERS_FILE) -> set[str]:
    if not path.exists():
        return set()
    out: set[str] = set()
    for line in path.read_text().splitlines():
        s = line.split("#", 1)[0].strip()
        if s:
            out.add(s.upper())
    return out


def _extract_tickers(text: str, known: set[str]) -> list[str]:
    """Cashtags ($ABVX) always count; bare uppercase tokens only if already tracked."""
    found: set[str] = set()
    for m in _CASHTAG_RE.finditer(text):
        found.add(m.group(1).upper())
    for m in _BARE_RE.finditer(text):
        tok = m.group(1).upper()
        if tok in known:
            found.add(tok)
    return sorted(found)


# ---------- persistence ----------


def _last_ts(conn: sqlite3.Connection, channel_id: int) -> datetime | None:
    row = conn.execute(
        "SELECT MAX(ts) FROM messages WHERE channel_id = ?", (str(channel_id),)
    ).fetchone()
    if row is None or row[0] is None:
        return None
    return datetime.fromisoformat(row[0])


def _upsert(conn: sqlite3.Connection, msg: StoredMessage) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO messages
            (message_id, channel_id, channel_name, author_id, author_name,
             ts, content, reply_to_id, attachments, tickers)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            msg.message_id,
            msg.channel_id,
            msg.channel_name,
            msg.author_id,
            msg.author_name,
            msg.ts,
            msg.content,
            msg.reply_to_id,
            json.dumps(msg.attachments),
            json.dumps(msg.tickers),
        ),
    )


def _download_attachment(url: str, message_id: str, filename: str) -> str | None:
    """Save a Discord CDN attachment locally. Returns the path, or None on failure.

    Discord CDN links are signed and expire, so we fetch at ingest time rather than
    storing only the URL — the local copy is the durable record of the chart.
    """
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    safe = filename.replace("/", "_")
    dest = MEDIA_DIR / f"{message_id}-{safe}"
    if dest.exists():
        return str(dest)
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            dest.write_bytes(r.read())
        return str(dest)
    except Exception as e:  # log and keep the URL; don't abort the pull
        print(f"  attachment download failed ({filename}): {e}")
        return None


# ---------- discord fetch ----------


async def _fetch(
    channels: list[int],
    token: str,
    since: datetime | None,
    db_path: Path,
) -> int:
    """Connect, pull messages after the watermark per channel, store, disconnect.

    `since` overrides the per-channel watermark (used by backfill). Returns the
    number of messages written.
    """
    import discord

    known = _known_tickers()
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    written = 0

    @client.event
    async def on_ready() -> None:
        nonlocal written
        try:
            with _connect(db_path) as conn:
                for cid in channels:
                    channel = client.get_channel(cid)
                    if channel is None:
                        channel = await client.fetch_channel(cid)
                    after = since or _last_ts(conn, cid)
                    name = getattr(channel, "name", None)
                    async for m in channel.history(  # type: ignore[union-attr]
                        limit=None, after=after, oldest_first=True
                    ):
                        atts: list[dict[str, str | None]] = []
                        for a in m.attachments:
                            local = (
                                _download_attachment(a.url, str(m.id), a.filename)
                                if (a.content_type or "").startswith("image/")
                                else None
                            )
                            atts.append(
                                {
                                    "filename": a.filename,
                                    "url": a.url,
                                    "local_path": local,
                                    "content_type": a.content_type,
                                }
                            )
                        reply_to = (
                            str(m.reference.message_id)
                            if m.reference and m.reference.message_id
                            else None
                        )
                        _upsert(
                            conn,
                            StoredMessage(
                                message_id=str(m.id),
                                channel_id=str(cid),
                                channel_name=name,
                                author_id=str(m.author.id),
                                author_name=str(m.author),
                                ts=m.created_at.astimezone(UTC).isoformat(),
                                content=m.content,
                                reply_to_id=reply_to,
                                attachments=atts,
                                tickers=_extract_tickers(m.content, known),
                            ),
                        )
                        written += 1
                    print(f"  #{name or cid}: pulled to {written} total")
        finally:
            await client.close()

    await client.start(token)
    return written


def pull(since: datetime | None = None, db_path: Path = DB_PATH) -> int:
    """Fetch new messages from all configured channels. `since` forces a backfill."""
    channels = _load_channels()
    token = _load_token()
    return asyncio.run(_fetch(channels, token, since, db_path))


# ---------- queries ----------


def recent(
    days: int = 7,
    author: str | None = None,
    db_path: Path = DB_PATH,
) -> list[StoredMessage]:
    """Messages from the last `days`, newest first, optionally filtered by author substring."""
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    q = "SELECT * FROM messages WHERE ts >= ?"
    params: list[str] = [cutoff]
    if author:
        q += " AND author_name LIKE ?"
        params.append(f"%{author}%")
    q += " ORDER BY ts DESC"
    with _connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(q, params).fetchall()
    return [
        StoredMessage(
            message_id=r["message_id"],
            channel_id=r["channel_id"],
            channel_name=r["channel_name"],
            author_id=r["author_id"],
            author_name=r["author_name"],
            ts=r["ts"],
            content=r["content"],
            reply_to_id=r["reply_to_id"],
            attachments=json.loads(r["attachments"]),
            tickers=json.loads(r["tickers"]),
        )
        for r in rows
    ]


def digest(days: int = 1, author: str | None = None, db_path: Path = DB_PATH) -> str:
    """Markdown block of recent messages — the staged dump for the daily brief.

    Deterministic capture only: author, time, verbatim text, chart paths, tagged
    tickers. The synthesis into a structured input note stays a hand/LLM step.
    """
    msgs = recent(days, author, db_path)
    if not msgs:
        return "_No Discord messages in window._"
    lines = []
    for m in reversed(msgs):  # chronological for reading
        when = m.ts[:16].replace("T", " ")
        tags = f"  [{', '.join(m.tickers)}]" if m.tickers else ""
        lines.append(f"**{m.author_name}** · {when}{tags}")
        if m.content:
            lines.append("> " + m.content.replace("\n", "\n> "))
        for a in m.attachments:
            loc = a.get("local_path") or a.get("url")
            lines.append(f"  - chart: {loc}")
        lines.append("")
    return "\n".join(lines)


# ---------- CLI ----------


def main() -> None:
    import argparse

    p = argparse.ArgumentParser(prog="degen.discord_log")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("pull", help="fetch new messages since last stored")
    bf = sub.add_parser("backfill", help="fetch history since a date")
    bf.add_argument("--since", required=True, help="YYYY-MM-DD")
    rc = sub.add_parser("recent", help="print recent messages")
    rc.add_argument("--days", type=int, default=7)
    rc.add_argument("--author", default=None)
    dg = sub.add_parser("digest", help="markdown block for the daily brief")
    dg.add_argument("--days", type=int, default=1)
    dg.add_argument("--author", default=None)

    args = p.parse_args()
    cmd = args.cmd or "pull"

    if cmd == "pull":
        n = pull()
        print(f"pulled {n} new message(s) → {DB_PATH}")
    elif cmd == "backfill":
        since = datetime.fromisoformat(args.since).replace(tzinfo=UTC)
        n = pull(since=since)
        print(f"backfilled {n} message(s) since {args.since} → {DB_PATH}")
    elif cmd == "recent":
        for m in recent(args.days, args.author):
            tags = f"  [{', '.join(m.tickers)}]" if m.tickers else ""
            charts = f"  ({len(m.attachments)} attach)" if m.attachments else ""
            print(f"{m.ts[:16]}  {m.author_name}{tags}{charts}")
            if m.content:
                print(f"    {m.content[:200]}")
    elif cmd == "digest":
        print(digest(args.days, args.author))
    else:
        p.error(f"unknown command: {cmd}")


if __name__ == "__main__":
    main()
