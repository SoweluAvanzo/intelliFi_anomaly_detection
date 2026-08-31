"""Gnosis Conditional Tokens position-id derivation (pure Python).

An outcome token id on Polymarket is a CTF *position id*:

    collectionId = getCollectionId(parentCollectionId = 0, conditionId, indexSet)
    positionId   = keccak256(collateralToken ‖ collectionId)

``getCollectionId`` (CTHelpers.sol) hashes (conditionId, indexSet) to a field
element, lifts it to a point on alt_bn128, and encodes the point's parity in
bit 254. With a zero parent collection the elliptic-curve addition is skipped,
which is Polymarket's case. Reproducing it lets us map *every* resolved
condition seen on-chain to its two token ids without any API — verified
against the Gamma ``clobTokenIds`` of the corpus markets (see ``verify``).
"""
from __future__ import annotations

from eth_hash.auto import keccak

P = 21888242871839275222246405745257275088696311157297823662689037894645226208583  # alt_bn128 field
B = 3
USDC_E = "0x2791bca1f2de4661ed88a30c99a7a9449aa84174"
WRAPPED_COLLATERAL = "0x3a3bd7bb9528e159577f7c2e685cc81a765002e2"   # negRisk markets' collateral


def _sqrt_mod_p(a: int) -> int:
    return pow(a, (P + 1) // 4, P)          # P ≡ 3 (mod 4)


def get_collection_id(condition_id: str, index_set: int, parent_collection_id: int = 0) -> int:
    if parent_collection_id != 0:
        raise NotImplementedError("non-zero parent collections are not used by Polymarket")
    cid = bytes.fromhex(condition_id[2:] if condition_id.startswith("0x") else condition_id)
    x1 = int.from_bytes(keccak(cid + index_set.to_bytes(32, "big")), "big")
    odd = (x1 >> 255) != 0
    while True:
        x1 = (x1 + 1) % P
        yy = (x1 * x1 % P * x1 + B) % P
        y1 = _sqrt_mod_p(yy)
        if y1 * y1 % P == yy:
            break
    if (odd and y1 % 2 == 0) or (not odd and y1 % 2 == 1):
        y1 = P - y1
    if y1 % 2 == 1:
        x1 ^= 1 << 254
    return x1


def position_id(collateral: str, condition_id: str, index_set: int) -> int:
    coll = get_collection_id(condition_id, index_set)
    return int.from_bytes(keccak(bytes.fromhex(collateral[2:]) + coll.to_bytes(32, "big")), "big")


def token_ids(condition_id: str, neg_risk: bool) -> tuple[int, int]:
    """(outcome 0 token, outcome 1 token) for a binary Polymarket condition."""
    coll = WRAPPED_COLLATERAL if neg_risk else USDC_E
    return position_id(coll, condition_id, 1), position_id(coll, condition_id, 2)
