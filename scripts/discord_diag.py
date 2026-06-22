"""One-off: confirm the bot's guild membership and per-channel read access."""

import asyncio

import discord

from degen.ingest import discord_log as dl


async def run() -> None:
    token = dl._load_token()
    channels = dl._load_channels()
    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        print("logged in as", client.user)
        print("in guilds:", [(g.name, g.id) for g in client.guilds])
        for cid in channels:
            ch = client.get_channel(cid)
            if ch is None:
                try:
                    ch = await client.fetch_channel(cid)
                except Exception as e:
                    print(f"  {cid}: FETCH FAILED -> {e}")
                    continue
            print(f"  #{getattr(ch, 'name', cid)} ({cid}) type={type(ch).__name__}")
            # show this channel's perms for the bot
            perms = ch.permissions_for(ch.guild.me) if hasattr(ch, "guild") else None
            if perms is not None:
                print(
                    f"      view={perms.view_channel} "
                    f"read_history={perms.read_message_history}"
                )
            try:
                cnt = 0
                async for m in ch.history(limit=3):
                    cnt += 1
                    print(f"      [{m.created_at.date()}] {m.author}: {m.content[:70]!r}")
                if cnt == 0:
                    print("      (history returned 0 messages)")
            except Exception as e:
                print(f"      history error: {e}")
        await client.close()

    await client.start(token)


asyncio.run(run())
