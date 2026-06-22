"""E*TRADE read-only account access — positions & balances via the official API.

We build this ourselves (the community MCPs are stale) and own the boundary the
same way `data.py`/`edgar.py` do. E*TRADE uses **OAuth 1.0a**, not a bearer
token, so there are two credential layers:

  1. Consumer key/secret  — long-lived app creds. Put in `.env`:
         ETRADE_API_KEY=...
         ETRADE_API_SECRET=...
         ETRADE_ENV=prod          # or "sandbox"
  2. Access token/secret  — short-lived (E*TRADE expires them at midnight ET and
     after ~2h idle). Obtained via a one-time browser authorize and cached in
     `data/etrade_token.json` (gitignored). The code manages these; you never
     hand-edit them.

First run does the handshake:
    uv run python -m degen.etrade
      → opens the E*TRADE authorize page → you log in → paste the verifier code.
Subsequent runs reuse the cached token until it expires, then re-prompt.

Read-only by design: this module never places orders.
"""

from __future__ import annotations

import json
import os
import sys
import webbrowser
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from requests_oauthlib import OAuth1Session

load_dotenv()

_PROD = "https://api.etrade.com"
_SANDBOX = "https://apisb.etrade.com"
_AUTHORIZE = "https://us.etrade.com/e/t/etws/authorize"
_TOKEN_CACHE = Path("data/etrade_token.json")


def _base() -> str:
    return _SANDBOX if os.environ.get("ETRADE_ENV", "prod").lower() == "sandbox" else _PROD


def _creds() -> tuple[str, str]:
    key = os.environ.get("ETRADE_API_KEY")
    secret = os.environ.get("ETRADE_API_SECRET")
    if not key or not secret:
        raise RuntimeError(
            "Missing ETRADE_API_KEY / ETRADE_API_SECRET. Add them to .env "
            "(consumer key + secret from the E*TRADE developer portal)."
        )
    return key, secret


# ---------- OAuth 1.0a handshake + token cache ----------


def _save_token(token: str, secret: str) -> None:
    _TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _TOKEN_CACHE.write_text(json.dumps({"oauth_token": token, "oauth_token_secret": secret}))


def _load_token() -> tuple[str, str] | None:
    if not _TOKEN_CACHE.exists():
        return None
    d = json.loads(_TOKEN_CACHE.read_text())
    return d["oauth_token"], d["oauth_token_secret"]


def authorize() -> tuple[str, str]:
    """Run the one-time OAuth 1.0a flow; cache and return (access_token, secret)."""
    key, secret = _creds()

    # 1) request token (out-of-band callback → verifier shown on screen)
    rt = OAuth1Session(key, client_secret=secret, callback_uri="oob")
    fetched = rt.fetch_request_token(f"{_base()}/oauth/request_token")
    ro_key = str(fetched["oauth_token"])
    ro_secret = str(fetched["oauth_token_secret"])

    # 2) user authorizes in the browser, gets a verifier code
    url = f"{_AUTHORIZE}?key={key}&token={ro_key}"
    print(f"\nAuthorize this app in your browser:\n  {url}\n", file=sys.stderr)
    with __import__("contextlib").suppress(Exception):
        webbrowser.open(url)
    verifier = input("Paste the E*TRADE verification code: ").strip()

    # 3) exchange for the access token
    at = OAuth1Session(
        key,
        client_secret=secret,
        resource_owner_key=ro_key,
        resource_owner_secret=ro_secret,
        verifier=verifier,
    )
    access = at.fetch_access_token(f"{_base()}/oauth/access_token")
    token = str(access["oauth_token"])
    tok_secret = str(access["oauth_token_secret"])
    _save_token(token, tok_secret)
    return token, tok_secret


def _session(*, interactive: bool = True) -> OAuth1Session:
    """Authenticated session from the cached token; runs authorize() if needed."""
    key, secret = _creds()
    cached = _load_token()
    if cached is None:
        if not interactive:
            raise RuntimeError("No cached E*TRADE token — run `uv run python -m degen.etrade`.")
        cached = authorize()
    return OAuth1Session(
        key,
        client_secret=secret,
        resource_owner_key=cached[0],
        resource_owner_secret=cached[1],
    )


def _get(
    session: OAuth1Session,
    path: str,
    *,
    params: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    hdrs = {"Accept": "application/json", **(headers or {})}
    r = session.get(f"{_base()}{path}", params=params or {}, headers=hdrs)
    if r.status_code == 401:  # token expired → re-auth once and retry
        token, tok_secret = authorize()
        key, secret = _creds()
        session = OAuth1Session(
            key,
            client_secret=secret,
            resource_owner_key=token,
            resource_owner_secret=tok_secret,
        )
        r = session.get(f"{_base()}{path}", params=params or {}, headers=hdrs)
    if r.status_code == 204:  # no content (e.g. empty portfolio)
        return {}
    r.raise_for_status()
    return r.json()


# ---------- read-only account data ----------


@dataclass(frozen=True, slots=True)
class Account:
    account_id: str
    account_id_key: str  # the key the portfolio/balance endpoints want
    type: str
    description: str
    institution_type: str  # BROKERAGE / BANK — balance endpoint needs this verbatim


@dataclass(frozen=True, slots=True)
class EtradePosition:
    symbol: str
    security_type: str  # EQ, OPTN, etc.
    quantity: float
    price_paid: float | None  # avg cost / share (or per-contract for options)
    market_value: float | None
    total_gain: float | None
    total_gain_pct: float | None


def accounts(session: OAuth1Session | None = None) -> list[Account]:
    session = session or _session()
    data = _get(session, "/v1/accounts/list.json")
    rows = data.get("AccountListResponse", {}).get("Accounts", {}).get("Account", [])
    out: list[Account] = []
    for a in rows:
        if str(a.get("accountStatus", "")).upper() == "CLOSED":
            continue
        out.append(
            Account(
                account_id=str(a.get("accountId", "")),
                account_id_key=str(a.get("accountIdKey", "")),
                type=str(a.get("accountType", "")),
                description=str(a.get("accountDesc", "")),
                institution_type=str(a.get("institutionType", "BROKERAGE")),
            )
        )
    return out


def positions(account_id_key: str, session: OAuth1Session | None = None) -> list[EtradePosition]:
    session = session or _session()
    data = _get(session, f"/v1/accounts/{account_id_key}/portfolio.json", params={"count": "250"})
    portfolios = data.get("PortfolioResponse", {}).get("AccountPortfolio", [])
    out: list[EtradePosition] = []
    for pf in portfolios:
        for p in pf.get("Position", []):
            prod = p.get("Product", {})

            def _f(v: object) -> float | None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None

            out.append(
                EtradePosition(
                    symbol=str(prod.get("symbol", p.get("symbolDescription", ""))),
                    security_type=str(prod.get("securityType", "")),
                    quantity=_f(p.get("quantity")) or 0.0,
                    price_paid=_f(p.get("pricePaid")),
                    market_value=_f(p.get("marketValue")),
                    total_gain=_f(p.get("totalGain")),
                    total_gain_pct=_f(p.get("totalGainPct")),
                )
            )
    return out


def balance(
    account_id_key: str,
    inst_type: str = "BROKERAGE",
    session: OAuth1Session | None = None,
) -> dict:
    """Balance/NAV for an account. E*TRADE's balance endpoint is fussy: it needs
    the account's `institutionType` as `instType` AND a `consumerkey` header."""
    session = session or _session()
    key, _ = _creds()
    return _get(
        session,
        f"/v1/accounts/{account_id_key}/balance.json",
        params={"instType": inst_type, "realTimeNAV": "true"},
        headers={"consumerkey": key},
    )


def main() -> int:
    try:
        session = _session()
        accts = accounts(session)
    except RuntimeError as e:
        print(f"[error] {e}", file=sys.stderr)
        return 1

    print(f"\n=== E*TRADE accounts ({_base()}) ===")
    for a in accts:
        print(f"  {a.account_id}  [{a.type}]  {a.description}  (key={a.account_id_key})")
        try:
            ps = positions(a.account_id_key, session)
        except Exception as e:  # surface per-account, keep going
            print(f"    (positions unavailable: {e})")
            continue
        for p in ps:
            gain = f"{p.total_gain:+,.0f}" if p.total_gain is not None else "—"
            gpct = f"{p.total_gain_pct:+.1f}%" if p.total_gain_pct is not None else "—"
            mv = f"{p.market_value:,.0f}" if p.market_value is not None else "—"
            print(
                f"    {p.symbol:<22} {p.security_type:<5} qty {p.quantity:>10,.2f}  "
                f"mv {mv:>12}  gain {gain:>10} ({gpct})"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
