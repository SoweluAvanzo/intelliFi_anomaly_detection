"""On-chain helpers for wallet entity resolution.

Two clients:

* ``PolygonRPC`` — JSON-RPC against a public Polygon endpoint. Used for
  ``eth_getCode`` (EOA vs. contract) and ``eth_call`` for ``owner()`` /
  ``getOwners()`` style lookups on proxy contracts.

* ``Polygonscan`` — REST client for the Polygonscan API. Used for token
  transfer history (``tokentx`` for ERC-20 and ``tokennfttx`` /
  ``token1155tx`` for ERC-1155). Requires a free API key in the
  ``POLYGONSCAN_API_KEY`` environment variable.

Empirical Polymarket observation: in our top-trader sample of 50 wallets,
**100% are EOAs** (no proxy contract bytecode). The "proxyWallet" field in
the Data API is therefore the user's actual address for self-custody users,
and ``owner()`` resolution is not applicable. We keep the contract-detect
helper for completeness (older/custodial wallets may still be SCWs).
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from . import config

log = logging.getLogger(__name__)

# How long a stamped per-IP penalty marker is treated as "warm". The observed penalty
# runs multiple hours (laptop cleared in ~2.5 h, box ~3 h), so the marker must outlive it
# or the guards periodically false-clear and re-poke the still-penalized IP (audit
# Finding 3). Default 3 h; override with INTELLIFI_PENALTY_COOLDOWN_S.
PENALTY_COOLDOWN_S = float(os.getenv("INTELLIFI_PENALTY_COOLDOWN_S", "10800"))


# ---------------------------------------------------------------------------
# Known token contract addresses on Polygon
# ---------------------------------------------------------------------------

# Bridged USDC ("USDC.e"), historically dominant on Polymarket.
USDC_E = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"
# Native USDC (Circle) on Polygon — newer.
USDC_NATIVE = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
# Polymarket Conditional Tokens Framework (Gnosis CTF) — ERC-1155 outcome shares.
POLYMARKET_CTF = "0x4d97dcd97ec945f40cf65f87097ace5ea0476045"
# Polymarket Exchange — main CLOB matching contract.
POLYMARKET_EXCHANGE = "0x4bfb41d5b3570defd03c39a9a4d8de6bd8b8982e"
# Polymarket NegRisk CTF Exchange — separate matching contract for negRisk markets.
POLYMARKET_NEGRISK_EXCHANGE = "0xc5d563a36ae78145c45a50134d48a1215220f80a"
# Polymarket NegRisk Adapter — implements the No→portfolio-Yes conversion gadget.
POLYMARKET_NEGRISK_ADAPTER = "0xd91e80cf2e7be2e162c6513ced06f1dd0da35296"
# Polymarket WrappedCollateral — USDC wrapper used inside the negRisk system.
POLYMARKET_WRAPPED_COLLATERAL = "0x3a3bd7bb9528e159577f7c2e685cc81a765002e2"
# Polymarket internal CollateralToken (resolved via Etherscan V2 source lookup).
POLYMARKET_COLLATERAL_TOKEN = "0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb"

# Addresses we tag as "popular": any wallet a Polymarket user is likely to
# interact with for non-relationship reasons (Polymarket internals, CEX
# deposits, bridges). Used in the graph layer to suppress common-neighbor
# edges that are not evidence of entity overlap.
POPULAR_ADDRESSES = {
    # Polymarket internals — every user touches these:
    POLYMARKET_CTF,
    POLYMARKET_EXCHANGE,
    POLYMARKET_NEGRISK_EXCHANGE,
    POLYMARKET_NEGRISK_ADAPTER,
    POLYMARKET_WRAPPED_COLLATERAL,
    POLYMARKET_COLLATERAL_TOKEN,
    # USDC contracts themselves (transfer "from"/"to" can include them):
    USDC_E,
    USDC_NATIVE,
}


# ---------------------------------------------------------------------------
# Polygon JSON-RPC
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PolygonRPC:
    url: str = "https://polygon-rpc.com"
    timeout: float = 20.0

    def _post(self, payload: Any) -> Any:
        r = requests.post(self.url, json=payload, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get_code(self, address: str) -> str:
        res = self._post({
            "jsonrpc": "2.0", "id": 1, "method": "eth_getCode",
            "params": [address, "latest"],
        })
        return res.get("result", "0x")

    def batch_get_code(self, addresses: list[str]) -> dict[str, str]:
        """Batch ``eth_getCode``. Returns ``{address_lower: bytecode}``."""
        if not addresses:
            return {}
        payload = [
            {"jsonrpc": "2.0", "id": i, "method": "eth_getCode",
             "params": [a, "latest"]}
            for i, a in enumerate(addresses)
        ]
        res = self._post(payload)
        out: dict[str, str] = {}
        for item in res if isinstance(res, list) else [res]:
            if not isinstance(item, dict):
                continue
            i = item.get("id")
            if i is None or not (0 <= i < len(addresses)):
                continue
            out[addresses[i].lower()] = item.get("result", "0x")
        return out

    def eth_call(self, to: str, data: str) -> str:
        res = self._post({
            "jsonrpc": "2.0", "id": 1, "method": "eth_call",
            "params": [{"to": to, "data": data}, "latest"],
        })
        return res.get("result", "0x")


# ABI selectors for the proxy-controller lookup. Defensive ordering: try the
# common ones; first non-empty wins.
OWNER_SELECTORS: tuple[tuple[str, str], ...] = (
    ("owner()",      "0x8da5cb5b"),
    ("getOwners()",  "0xa0e67e2b"),
)


def resolve_controller(rpc: PolygonRPC, address: str) -> str | None:
    """Return the controller EOA for a proxy contract, or None for EOAs."""
    code = rpc.get_code(address)
    if code == "0x":
        return None  # already an EOA
    for _, sel in OWNER_SELECTORS:
        try:
            res = rpc.eth_call(address, sel)
        except Exception:
            continue
        if res and res != "0x" and len(res) >= 66:
            # Decode last 20 bytes of a 32-byte word as an address.
            return "0x" + res[-40:].lower()
    return None


# ---------------------------------------------------------------------------
# Polygonscan
# ---------------------------------------------------------------------------

class PolygonscanError(RuntimeError):
    pass


class IPPenaltyError(PolygonscanError):
    """The IP is under Etherscan's per-IP invalid-key penalty.

    Raised when consecutive "too many invalid api key attempts" responses cross
    ``invalid_key_breaker``. A poisoned IP needs SILENCE, not retries — every
    further request keeps it warm and extends the penalty — so callers (crawler,
    relaunch orchestrator, box entrypoint) must STOP and alert, never relaunch.
    """


class DailyQuotaError(PolygonscanError):
    """This KEY's per-day call quota (Etherscan free tier: 100k/day) is spent.

    Distinct from a per-second rate limit (retryable) and from an IP penalty
    (NEVER stamps the .ip_penalty marker — this is per-key and not an IP problem).
    The quota resets at 00:00 UTC, so callers should STOP this key cleanly and
    wait for the reset rather than retry-grinding the daily-limit response (which,
    because it contains the substring "rate limit", would otherwise be swallowed by
    the retryable path and backed-off 12x per call).
    """


@dataclass
class Polygonscan:
    """Etherscan V2 multichain client targeting Polygon (chainid=137).

    The Polygonscan V1 endpoint (api.polygonscan.com/api) was deprecated in
    2025 in favour of a unified Etherscan V2 endpoint that accepts a
    ``chainid`` parameter. The same Polygonscan/Etherscan API key works for
    both. Reference: https://docs.etherscan.io/v2-migration

    Free-tier limits: 5 calls/sec, 100,000 calls/day. The client tracks call
    counts in ``calls_made`` and aborts when ``max_calls`` is reached so an
    accidental loop cannot exhaust the daily quota.
    """

    api_key: str
    base_url: str = "https://api.etherscan.io/v2/api"
    chain_id: int = 137
    timeout: float = 30.0
    # Polite default well under the free-tier 5/sec ceiling.
    min_interval_s: float = 0.25
    # Hard cap. ``None`` disables it; default leaves headroom under the daily quota.
    max_calls: int | None = 80_000
    # Retries per call on transient errors / rate limits (the free key is
    # enforced at 3 calls/s, measured 2026-08-30 — parallel crawlers must share it).
    max_retries: int = 5
    # Circuit breaker: after this many CONSECUTIVE per-IP invalid-key responses,
    # raise IPPenaltyError so callers stop instead of grinding the IP warm. 0 disables.
    invalid_key_breaker: int = 5
    # Cross-process penalty marker (best-effort). ``None`` -> DATA_DIR/logs/.ip_penalty.
    # Orchestrators read it (penalty_active) to refuse launching onto a warm IP.
    penalty_marker: "Path | None" = None

    _last_call_ts: float = 0.0
    calls_made: int = 0          # every HTTP attempt (retries included) — quota accounting
    ok_calls: int = 0            # successful responses — efficiency accounting
    _consecutive_invalid: int = 0
    _session: "requests.Session | None" = None

    def __post_init__(self) -> None:
        if not self.api_key:
            raise PolygonscanError(
                "POLYGONSCAN_API_KEY not set — register at polygonscan.com/myapikey"
            )
        if self.penalty_marker is None:
            self.penalty_marker = config.DATA_DIR / "logs" / ".ip_penalty"
        # Reuse one keep-alive connection for every call. The dense-genesis crawl
        # makes hundreds of calls per 500-block chunk; a fresh TLS handshake per call
        # (the default requests.get behaviour) both slows it ~30-40% and churns
        # connections against the endpoint. A pooled Session avoids both.
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({"User-Agent": config.USER_AGENT})

    @classmethod
    def from_env(cls) -> "Polygonscan":
        return cls(api_key=os.environ.get("POLYGONSCAN_API_KEY", ""))

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_call_ts
        if elapsed < self.min_interval_s:
            time.sleep(self.min_interval_s - elapsed)
        self._last_call_ts = time.time()

    def _record_penalty(self) -> None:
        """Best-effort: stamp the cross-process penalty marker with now + count.

        Orchestrators read it via :meth:`penalty_active` to refuse launching onto
        a still-warm IP. Failure to write is non-fatal (the in-process breaker
        still fires); the marker "expires" by age, matching the observed decay.
        """
        try:
            self.penalty_marker.parent.mkdir(parents=True, exist_ok=True)
            self.penalty_marker.write_text(f"{time.time():.0f} {self._consecutive_invalid}\n")
            log.warning("per-IP penalty marker stamped at %s (consecutive=%d) — launch guards "
                        "will now refuse this IP until cooldown", self.penalty_marker, self._consecutive_invalid)
        except OSError as exc:
            # A failed stamp means the cross-process guard is BLIND — surface it loudly
            # (e.g. /data/logs not writable by the container uid) rather than swallowing it.
            log.error("COULD NOT stamp per-IP penalty marker %s (%s) — cross-process guard is "
                      "inert; fix marker-path permissions", self.penalty_marker, exc)

    def _raise_if_invalid_key(self, message: Any, result: Any) -> None:
        """If the response is the per-IP invalid-key penalty, stamp the marker and raise
        (IPPenaltyError once ``invalid_key_breaker`` consecutive hits are seen, else
        PolygonscanError); no-op otherwise. Called for BOTH HTTP-200 status=0 bodies and
        HTTP-429 bodies — a recovering IP may deliver the penalty either way, and either
        must stamp (never retry-grind). Placed before the generic status=0 raise so these
        signatures are recognised, not swallowed by the catch-all."""
        combined = f"{message} {result}".lower()
        if not any(m in combined for m in self._INVALID_KEY_MARKERS):
            return
        self._consecutive_invalid += 1
        log.warning("Etherscan per-IP invalid-key penalty hit (consecutive=%d): %s",
                    self._consecutive_invalid, message or str(result)[:80])
        self._record_penalty()
        if self.invalid_key_breaker and self._consecutive_invalid >= self.invalid_key_breaker:
            raise IPPenaltyError(
                f"IP under Etherscan per-IP penalty: {self._consecutive_invalid} consecutive "
                f"invalid-key responses ({message!r}). STOP — do not relaunch; let the IP go quiet."
            )
        raise PolygonscanError(
            f"Etherscan invalid-key response (consecutive={self._consecutive_invalid}): "
            f"message={message!r} result={str(result)[:80]!r}"
        )

    @staticmethod
    def penalty_active(cooldown_s: float = PENALTY_COOLDOWN_S, marker: "Path | None" = None) -> float:
        """Seconds remaining in the per-IP penalty cooldown, or 0.0 if clear.

        A crawler that hits the invalid-key penalty stamps ``marker`` (default
        DATA_DIR/logs/.ip_penalty). While the stamp is younger than ``cooldown_s``
        (default ``PENALTY_COOLDOWN_S`` = 3 h, matching the observed multi-hour
        penalty), the IP is treated as still warm and callers should not launch.
        Successes never clear it — only quiet time (age) does.
        """
        marker = marker or (config.DATA_DIR / "logs" / ".ip_penalty")
        try:
            ts = float(marker.read_text().split()[0])
        except (OSError, ValueError, IndexError):
            return 0.0
        remaining = cooldown_s - (time.time() - ts)
        return remaining if remaining > 0 else 0.0

    # Transient server messages worth retrying with backoff.
    _RETRYABLE_MARKERS: tuple[str, ...] = (
        "timeout", "server too busy", "temporarily unavailable",
        "rate limit", "max rate limit", "max calls per sec",
    )
    # Per-IP invalid-key penalty: NEVER retry these (a retry keeps the IP warm and
    # extends the ban); count consecutive hits toward the circuit breaker instead.
    _INVALID_KEY_MARKERS: tuple[str, ...] = (
        "too many invalid", "invalid api key", "#err2",
    )
    # Per-KEY daily-quota exhaustion: a clean stop (resets 00:00 UTC), NOT retryable.
    # Checked BEFORE _RETRYABLE_MARKERS because the daily message contains "rate limit".
    _DAILY_LIMIT_MARKERS: tuple[str, ...] = (
        "daily rate limit", "max calls per day", "daily limit", "per day",
    )

    def _raise_if_daily_quota(self, message: Any, result: Any) -> None:
        """Raise DailyQuotaError if the response is the per-day quota-exhausted message."""
        combined = f"{message} {result}".lower()
        if any(m in combined for m in self._DAILY_LIMIT_MARKERS):
            raise DailyQuotaError(
                f"Etherscan daily quota exhausted for this key ({message!r}); stop and resume "
                f"after the 00:00 UTC reset — not an IP penalty, not retryable")

    def _get(self, params: dict[str, Any], *, max_retries: int | None = None) -> Any:
        max_retries = max_retries or self.max_retries
        if self.max_calls is not None and self.calls_made >= self.max_calls:
            raise PolygonscanError(
                f"daily call cap hit ({self.calls_made}/{self.max_calls}); "
                "raise --max-calls or wait for quota reset"
            )
        params = {**params, "apikey": self.api_key, "chainid": self.chain_id}
        last_err: str | None = None
        for attempt in range(max_retries):
            self._throttle()
            try:
                self.calls_made += 1
                r = self._session.get(self.base_url, params=params, timeout=self.timeout)
            except requests.RequestException as exc:
                last_err = f"transport: {exc}"
                time.sleep(1.5 ** attempt)
                continue
            if r.status_code == 429:
                # A per-IP invalid-key penalty can surface as HTTP 429; peek the body so
                # it stamps + stops instead of being retry-ground as a plain rate limit.
                try:
                    b = r.json()
                except ValueError:
                    b = None
                if isinstance(b, dict):
                    self._raise_if_invalid_key(b.get("message", ""), b.get("result", ""))
                    self._raise_if_daily_quota(b.get("message", ""), b.get("result", ""))
                last_err = "HTTP 429"
                time.sleep(1.5 ** attempt)
                continue
            if r.status_code in (500, 502, 503, 504):
                last_err = f"HTTP {r.status_code}"
                time.sleep(1.5 ** attempt)
                continue
            r.raise_for_status()
            body = r.json()
            if "jsonrpc" in body:          # proxy module answers JSON-RPC style, no "status"
                self.ok_calls += 1
                self._consecutive_invalid = 0
                return body.get("result")
            status = str(body.get("status", "0"))
            if status == "1":
                self.ok_calls += 1
                self._consecutive_invalid = 0
                return body.get("result", [])
            message = body.get("message", "") or ""
            result = body.get("result")
            # Normal empty-result responses.
            if isinstance(result, str) and "no transactions" in result.lower():
                return []
            if isinstance(message, str) and "no transactions" in message.lower():
                return []
            if "no records found" in f"{message} {result}".lower():   # getLogs empty result
                return []
            # Per-IP invalid-key penalty: never retry; stamp the marker + (maybe) hard-stop.
            self._raise_if_invalid_key(message, result)
            # Per-KEY daily quota spent: clean stop (checked before the retryable path, which
            # would otherwise swallow it via the "rate limit" substring and grind 12x).
            self._raise_if_daily_quota(message, result)
            # Retry-worthy transient errors.
            combined = f"{message} {result}".lower()
            if any(marker in combined for marker in self._RETRYABLE_MARKERS):
                last_err = f"{message} | {str(result)[:80]}"
                time.sleep(1.5 ** attempt)
                continue
            raise PolygonscanError(f"Etherscan V2 API error: status={status} "
                                   f"message={message!r} result={str(result)[:120]!r}")
        raise PolygonscanError(f"Etherscan V2: retries exhausted ({last_err})")

    # ---- ERC-20 transfers (used for USDC) ----

    def latest_block(self) -> int:
        """Current Polygon head via the proxy module (one call)."""
        r = self._get({"module": "proxy", "action": "eth_blockNumber"})
        return int(str(r), 16)

    def erc20_transfers(
        self,
        address: str,
        *,
        contract_address: str | None = None,
        start_block: int = 0,
        end_block: int = 99999999,
        page: int = 1,
        offset: int = 5_000,
        sort: str = "asc",
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "module": "account",
            "action": "tokentx",
            "address": address,
            "startblock": start_block,
            "endblock": end_block,
            "page": page,
            "offset": offset,
            "sort": sort,
        }
        if contract_address:
            params["contractaddress"] = contract_address
        result = self._get(params)
        return result if isinstance(result, list) else []

    def erc20_transfers_all(
        self,
        address: str,
        *,
        contract_address: str | None = None,
        page_size: int = 5_000,
        max_pages: int = 10,
    ) -> list[dict[str, Any]]:
        """Paginate ``erc20_transfers`` until exhausted or ``max_pages`` hit.

        The free-tier API caps total results at ~10k per query window. We
        sidestep by paginating with a moving ``startblock`` boundary instead
        of relying on ``page``. ``max_pages`` caps how deep we go for a single
        wallet — at default (10 × 5000 = 50k rows) we capture all relevant
        counterparty patterns without burning the daily quota on a few
        ultra-active wallets.
        """
        out: list[dict[str, Any]] = []
        start_block = 0
        for _ in range(max_pages):
            batch = self.erc20_transfers(
                address,
                contract_address=contract_address,
                start_block=start_block,
                page=1,
                offset=page_size,
                sort="asc",
            )
            if not batch:
                return out
            out.extend(batch)
            if len(batch) < page_size:
                return out
            # Advance past the highest block in this batch to avoid duplicates.
            max_block = max(int(t["blockNumber"]) for t in batch)
            if max_block + 1 <= start_block:
                return out  # safety: cannot advance
            start_block = max_block + 1
        log.warning("erc20_transfers_all: hit max_pages=%d for %s (truncating)",
                    max_pages, address)
        return out

    # ---- ERC-1155 transfers (Polymarket outcome shares) ----

    def erc1155_transfers(
        self,
        address: str,
        *,
        contract_address: str | None = None,
        start_block: int = 0,
        end_block: int = 99999999,
        page: int = 1,
        offset: int = 5_000,
        sort: str = "asc",
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "module": "account",
            "action": "token1155tx",
            "address": address,
            "startblock": start_block,
            "endblock": end_block,
            "page": page,
            "offset": offset,
            "sort": sort,
        }
        if contract_address:
            params["contractaddress"] = contract_address
        result = self._get(params)
        return result if isinstance(result, list) else []

    def erc1155_transfers_all(
        self,
        address: str,
        *,
        contract_address: str | None = None,
        page_size: int = 5_000,
        max_pages: int = 10,
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        start_block = 0
        for _ in range(max_pages):
            batch = self.erc1155_transfers(
                address,
                contract_address=contract_address,
                start_block=start_block,
                page=1,
                offset=page_size,
                sort="asc",
            )
            if not batch:
                return out
            out.extend(batch)
            if len(batch) < page_size:
                return out
            max_block = max(int(t["blockNumber"]) for t in batch)
            if max_block + 1 <= start_block:
                return out
            start_block = max_block + 1
        log.warning("erc1155_transfers_all: hit max_pages=%d for %s (truncating)",
                    max_pages, address)
        return out
