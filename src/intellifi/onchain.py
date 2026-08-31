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
from typing import Any

import requests

from . import config

log = logging.getLogger(__name__)


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

    _last_call_ts: float = 0.0
    calls_made: int = 0          # every HTTP attempt (retries included) — quota accounting
    ok_calls: int = 0            # successful responses — efficiency accounting

    def __post_init__(self) -> None:
        if not self.api_key:
            raise PolygonscanError(
                "POLYGONSCAN_API_KEY not set — register at polygonscan.com/myapikey"
            )

    @classmethod
    def from_env(cls) -> "Polygonscan":
        return cls(api_key=os.environ.get("POLYGONSCAN_API_KEY", ""))

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_call_ts
        if elapsed < self.min_interval_s:
            time.sleep(self.min_interval_s - elapsed)
        self._last_call_ts = time.time()

    # Transient server messages worth retrying with backoff.
    _RETRYABLE_MARKERS: tuple[str, ...] = (
        "timeout", "server too busy", "temporarily unavailable",
        "rate limit", "max rate limit", "max calls per sec",
    )

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
                r = requests.get(self.base_url, params=params, timeout=self.timeout,
                                 headers={"User-Agent": config.USER_AGENT})
            except requests.RequestException as exc:
                last_err = f"transport: {exc}"
                time.sleep(1.5 ** attempt)
                continue
            if r.status_code in (429, 500, 502, 503, 504):
                last_err = f"HTTP {r.status_code}"
                time.sleep(1.5 ** attempt)
                continue
            r.raise_for_status()
            body = r.json()
            if "jsonrpc" in body:          # proxy module answers JSON-RPC style, no "status"
                self.ok_calls += 1
                return body.get("result")
            status = str(body.get("status", "0"))
            if status == "1":
                self.ok_calls += 1
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
