"""Chat-derived signal: Discord ingest, the calls ledger, and (later) catalysts.

Everything here reads the same `data/discord_log.db` and shares one privacy
posture — raw third-party chatter, real handles, personal P&L. Treat the DB and
any digest/ledger output as a *private local input*: synthesize, pseudonymize
handles, strip P&L before anything lands in a tracked file. See the privacy note
in `discord_log.py` and the pre-commit privacy hook.
"""
