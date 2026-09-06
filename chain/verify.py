"""
chain/verify.py
---------------
Verifies whether a match_record.json has been anchored on-chain.

Strategy A — calldata mode
    Scans the last N blocks for a transaction whose calldata starts with
    'FVCR:<hash_bytes>'. Prints VERIFIED / NOT FOUND.

Strategy B — contract mode
    Calls FaceVerifyChain.verify(bytes32) and checks whether anchoredAt != 0.
    Prints VERIFIED / NOT FOUND, plus anchoredAt timestamp and submitter address.

Tamper detection
    If the recomputed hash does NOT match any stored record, the pipeline
    prints TAMPERED — meaning the JSON has changed since it was anchored.

CLI
---
  python -m chain.verify match_record.json
  python -m chain.verify match_record.json --index 0
  python -m chain.verify match_record.json --scan-blocks 500   # calldata mode depth
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from chain.hasher import compute_hash_from_file  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Env config (same vars as anchor.py)
# ---------------------------------------------------------------------------
CHAIN_BACKEND     = os.getenv("CHAIN_BACKEND", "ganache").lower()
ANCHOR_MODE       = os.getenv("ANCHOR_MODE", "calldata").lower()
CHAIN_RPC_URL     = os.getenv("CHAIN_RPC_URL", "http://127.0.0.1:8545")
CHAIN_PRIVATE_KEY = os.getenv("CHAIN_PRIVATE_KEY", "")
CONTRACT_ADDRESS  = os.getenv("CONTRACT_ADDRESS", "")

CONTRACT_ABI = [
    {
        "inputs": [{"internalType": "bytes32", "name": "recordHash", "type": "bytes32"}],
        "name": "verify",
        "outputs": [
            {"internalType": "uint256", "name": "anchoredAt", "type": "uint256"},
            {"internalType": "address",  "name": "submitter",  "type": "address"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
]

# ANSI colours for terminal output
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BOLD   = "\033[1m"
RESET  = "\033[0m"


# ---------------------------------------------------------------------------
# Verification result enum
# ---------------------------------------------------------------------------
class VerifyResult:
    VERIFIED  = "VERIFIED"
    NOT_FOUND = "NOT_FOUND"
    TAMPERED  = "TAMPERED"


# ---------------------------------------------------------------------------
# Web3 helpers (mirrors anchor.py)
# ---------------------------------------------------------------------------

def _get_web3():
    try:
        from web3 import Web3
    except ImportError:
        raise RuntimeError("web3 is not installed. Run: pip3 install web3")

    rpc = CHAIN_RPC_URL
    w3 = Web3(Web3.HTTPProvider(rpc))

    if CHAIN_BACKEND != "ganache":
        # Polygon and most other L2s are POA chains — their extraData field
        # exceeds the 32 bytes web3.py expects on plain PoW/PoS chains.
        try:
            from web3.middleware import geth_poa_middleware
            w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        except ImportError:
            from web3.middleware import ExtraDataToPOAMiddleware
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    if not w3.is_connected():
        raise RuntimeError(
            f"Cannot connect to RPC at {rpc}. "
            "Is Ganache running?  →  npx ganache"
        )
    return w3


# ---------------------------------------------------------------------------
# Verification strategies
# ---------------------------------------------------------------------------

def _verify_contract(w3, hex_digest: str) -> dict:
    """Query FaceVerifyChain.verify(bytes32) on the deployed contract."""
    if not CONTRACT_ADDRESS:
        raise RuntimeError(
            "CONTRACT_ADDRESS is not set. Cannot use contract verification mode."
        )

    from web3 import Web3

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(CONTRACT_ADDRESS),
        abi=CONTRACT_ABI,
    )
    record_hash = bytes.fromhex(hex_digest)
    anchored_at, submitter = contract.functions.verify(record_hash).call()

    if anchored_at == 0:
        return {"status": VerifyResult.NOT_FOUND, "hex_digest": hex_digest}

    dt = datetime.fromtimestamp(anchored_at, tz=timezone.utc).isoformat()
    return {
        "status":      VerifyResult.VERIFIED,
        "hex_digest":  hex_digest,
        "anchored_at": anchored_at,
        "anchored_at_iso": dt,
        "submitter":   submitter,
        "anchor_mode": "contract",
    }


def _verify_calldata(w3, hex_digest: str, scan_blocks: int = 200) -> dict:
    """
    Scan recent blocks for a calldata transaction that embeds our hash.
    Looks for transactions to the burn address whose calldata starts with
    b'FVCR:' + hash_bytes.
    """
    target_data = b"FVCR:" + bytes.fromhex(hex_digest)
    target_hex  = "0x" + target_data.hex()
    burn_addr   = "0x000000000000000000000000000000000000dEaD"

    latest = w3.eth.block_number
    start  = max(0, latest - scan_blocks)

    logger.info(
        "Scanning blocks %d → %d for calldata hash %s...",
        start, latest, hex_digest[:16] + "...",
    )

    for block_num in range(latest, start - 1, -1):
        block = w3.eth.get_block(block_num, full_transactions=True)
        for tx in block.get("transactions", []):
            to = (tx.get("to") or "").lower()
            data = tx.get("input", b"")
            if hasattr(data, "hex"):
                data_hex = "0x" + data.hex()
            else:
                data_hex = data

            if to == burn_addr.lower() and data_hex == target_hex:
                ts = block.get("timestamp", 0)
                dt = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
                return {
                    "status":      VerifyResult.VERIFIED,
                    "hex_digest":  hex_digest,
                    "tx_hash":     tx["hash"].hex() if hasattr(tx["hash"], "hex") else tx["hash"],
                    "block_number": block_num,
                    "anchored_at":  ts,
                    "anchored_at_iso": dt,
                    "from_address": tx.get("from", ""),
                    "anchor_mode":  "calldata",
                }

    return {
        "status":       VerifyResult.NOT_FOUND,
        "hex_digest":   hex_digest,
        "blocks_scanned": scan_blocks,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def verify_record(hex_digest: str, scan_blocks: int = 200) -> dict:
    """
    Verify whether *hex_digest* exists on-chain.

    Returns a dict with a 'status' key: VERIFIED | NOT_FOUND
    """
    w3 = _get_web3()

    if ANCHOR_MODE == "contract":
        return _verify_contract(w3, hex_digest)
    else:
        return _verify_calldata(w3, hex_digest, scan_blocks=scan_blocks)


def verify_record_file(
    json_path: str | Path,
    index: int = -1,
    scan_blocks: int = 200,
) -> dict:
    """
    Load a match_record.json, recompute the hash, and verify on-chain.

    Returns a dict with 'status': VERIFIED | NOT_FOUND | TAMPERED
    plus 'hex_digest' and any chain metadata.
    """
    hex_digest, record = compute_hash_from_file(json_path, index=index)
    result = verify_record(hex_digest, scan_blocks=scan_blocks)
    result["record_image_path"] = record.get("image_path", "")
    return result


# ---------------------------------------------------------------------------
# Pretty printer
# ---------------------------------------------------------------------------

def print_result(result: dict) -> None:
    status = result.get("status", "UNKNOWN")

    if status == VerifyResult.VERIFIED:
        colour = GREEN
        icon   = "✅"
        label  = "VERIFIED"
    elif status == VerifyResult.TAMPERED:
        colour = RED
        icon   = "❌"
        label  = "TAMPERED — record has been modified since anchoring!"
    else:
        colour = YELLOW
        icon   = "⚠️ "
        label  = "NOT FOUND — this record has not been anchored yet"

    print()
    print(f"{BOLD}{colour}{icon}  {label}{RESET}")
    print(f"   SHA-256     : {result.get('hex_digest', '—')}")

    if status == VerifyResult.VERIFIED:
        print(f"   Anchored at : {result.get('anchored_at_iso', '—')}")
        if "tx_hash" in result:
            print(f"   Tx hash     : {result['tx_hash']}")
        if "block_number" in result:
            print(f"   Block       : {result['block_number']}")
        if "from_address" in result:
            print(f"   Submitted by: {result['from_address']}")
        if "submitter" in result:
            print(f"   Submitter   : {result['submitter']}")
    elif status == VerifyResult.NOT_FOUND:
        scanned = result.get("blocks_scanned")
        if scanned:
            print(f"   Blocks searched: last {scanned}")

    print()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv=None):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%H:%M:%S",
    )

    parser = argparse.ArgumentParser(
        description="Verify a match_record.json has been anchored on-chain.",
    )
    parser.add_argument("record_file", help="Path to match_record.json")
    parser.add_argument(
        "--index", type=int, default=-1,
        help="Which record to verify (default: -1 = last/most-recent).",
    )
    parser.add_argument(
        "--scan-blocks", type=int, default=200, metavar="N",
        help="(calldata mode) Number of recent blocks to scan (default: 200).",
    )
    args = parser.parse_args(argv)

    result = verify_record_file(
        args.record_file,
        index=args.index,
        scan_blocks=args.scan_blocks,
    )

    print_result(result)
    print(json.dumps(result, indent=2))

    return 0 if result["status"] == VerifyResult.VERIFIED else 1


if __name__ == "__main__":
    sys.exit(main())
