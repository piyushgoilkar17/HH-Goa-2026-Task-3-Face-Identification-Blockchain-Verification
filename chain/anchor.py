"""
chain/anchor.py
---------------
Anchors a SHA-256 hash of a match record onto an EVM-compatible blockchain.

Supported backends (set via .env):
  - Local Ganache  (CHAIN_BACKEND=ganache, default RPC http://127.0.0.1:8545)
  - Polygon Amoy   (CHAIN_BACKEND=custom,  requires CHAIN_RPC_URL + CHAIN_PRIVATE_KEY)
  - Any EVM RPC    (CHAIN_BACKEND=custom,  requires CHAIN_RPC_URL + CHAIN_PRIVATE_KEY)

Two anchoring strategies (set via .env ANCHOR_MODE):
  - "calldata"  : embed the hash as tx calldata (no contract needed, cheapest)
  - "contract"  : call FaceVerifyChain.anchor(bytes32) (requires CONTRACT_ADDRESS)

Required .env vars
------------------
  CHAIN_BACKEND       = ganache | custom             (default: ganache)
  ANCHOR_MODE         = calldata | contract          (default: calldata)
  CHAIN_RPC_URL       = http://...                   (only for custom, e.g. Polygon Amoy)
  CHAIN_PRIVATE_KEY   = 0x...                        (only for custom backend)
  CONTRACT_ADDRESS    = 0x...                        (only for ANCHOR_MODE=contract)

CLI
---
  python -m chain.anchor match_record.json
  python -m chain.anchor match_record.json --index 0   # anchor first record
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from chain.hasher import compute_hash_from_file  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Env config
# ---------------------------------------------------------------------------
CHAIN_BACKEND     = os.getenv("CHAIN_BACKEND", "ganache").lower()
ANCHOR_MODE       = os.getenv("ANCHOR_MODE", "calldata").lower()
CHAIN_RPC_URL     = os.getenv("CHAIN_RPC_URL", "http://127.0.0.1:8545")
CHAIN_PRIVATE_KEY = os.getenv("CHAIN_PRIVATE_KEY", "")
CONTRACT_ADDRESS  = os.getenv("CONTRACT_ADDRESS", "")

# Minimal ABI — only the anchor() function
CONTRACT_ABI = [
    {
        "inputs": [{"internalType": "bytes32", "name": "recordHash", "type": "bytes32"}],
        "name": "anchor",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
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


# ---------------------------------------------------------------------------
# Web3 helpers
# ---------------------------------------------------------------------------

def _get_web3():
    """Return a connected Web3 instance."""
    try:
        from web3 import Web3
    except ImportError:
        raise RuntimeError(
            "web3 is not installed. Run: pip3 install web3"
        )

    rpc = CHAIN_RPC_URL
    if CHAIN_BACKEND == "ganache":
        rpc = os.getenv("CHAIN_RPC_URL", "http://127.0.0.1:8545")

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
            f"Could not connect to RPC at {rpc}. "
            "Is Ganache running?  →  npx ganache  or  ganache-cli"
        )
    logger.info("Connected to %s (chain_id=%s)", rpc, w3.eth.chain_id)
    return w3


def _get_account(w3):
    """Return (account_address, private_key). Uses first Ganache account if no key given."""
    from web3 import Web3

    if CHAIN_BACKEND == "ganache" and not CHAIN_PRIVATE_KEY:
        # Ganache provides unlocked accounts with test ETH
        account = w3.eth.accounts[0]
        logger.info("Using Ganache account[0]: %s", account)
        return account, None  # no signing needed — Ganache unlocked

    if not CHAIN_PRIVATE_KEY:
        raise RuntimeError(
            "CHAIN_PRIVATE_KEY is not set. "
            "Add it to .env (required for non-Ganache chains)."
        )

    acct = w3.eth.account.from_key(CHAIN_PRIVATE_KEY)
    logger.info("Signing with account: %s", acct.address)
    return acct.address, CHAIN_PRIVATE_KEY


def _hex_to_bytes32(hex_digest: str) -> bytes:
    """Convert a 64-char hex SHA-256 digest to a bytes32 value."""
    return bytes.fromhex(hex_digest)


# ---------------------------------------------------------------------------
# Anchoring strategies
# ---------------------------------------------------------------------------

def _anchor_calldata(w3, account: str, private_key: str | None, hex_digest: str) -> str:
    """
    Embed the hash directly as tx calldata sent to a burn address.
    No contract needed. Cheapest possible anchoring.

    Returns the tx hash string.
    """
    # We prefix calldata with 'FVCR:' so it can be grepped on-chain explorers
    calldata = b"FVCR:" + bytes.fromhex(hex_digest)

    tx = {
        "to":       "0x000000000000000000000000000000000000dEaD",
        "value":    0,
        "data":     calldata,
        "gas":      50_000,
        "gasPrice": w3.eth.gas_price,
        "nonce":    w3.eth.get_transaction_count(account),
        "chainId":  w3.eth.chain_id,
    }

    if private_key:
        signed = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    else:
        # Ganache unlocked account — send directly
        tx.pop("chainId", None)
        tx_hash = w3.eth.send_transaction({**tx, "from": account})

    return tx_hash.hex() if isinstance(tx_hash, bytes) else tx_hash


def _anchor_contract(w3, account: str, private_key: str | None, hex_digest: str) -> str:
    """
    Call FaceVerifyChain.anchor(bytes32) on the deployed contract.

    Returns the tx hash string.
    """
    if not CONTRACT_ADDRESS:
        raise RuntimeError(
            "CONTRACT_ADDRESS is not set. "
            "Deploy the contract first (see contracts/deploy.py) and set it in .env."
        )

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(CONTRACT_ADDRESS),
        abi=CONTRACT_ABI,
    )
    record_hash = _hex_to_bytes32(hex_digest)

    if private_key:
        tx = contract.functions.anchor(record_hash).build_transaction({
            "from":     account,
            "gas":      100_000,
            "gasPrice": w3.eth.gas_price,
            "nonce":    w3.eth.get_transaction_count(account),
            "chainId":  w3.eth.chain_id,
        })
        signed = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    else:
        tx_hash = contract.functions.anchor(record_hash).transact({"from": account})

    return tx_hash.hex() if isinstance(tx_hash, bytes) else tx_hash


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def anchor_record(hex_digest: str) -> dict:
    """
    Anchor *hex_digest* onto the configured chain.

    Returns
    -------
    dict with keys: hash, tx_hash, chain_backend, anchor_mode, rpc_url
    """
    from web3 import Web3  # import here so module loads without web3 if needed

    w3 = _get_web3()
    account, private_key = _get_account(w3)

    if ANCHOR_MODE == "contract":
        tx_hash = _anchor_contract(w3, account, private_key, hex_digest)
    else:
        tx_hash = _anchor_calldata(w3, account, private_key, hex_digest)

    # Wait for receipt
    logger.info("Waiting for tx %s to be mined...", tx_hash)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    logger.info(
        "Mined in block %s (gas used: %s, status: %s)",
        receipt["blockNumber"], receipt["gasUsed"], receipt["status"],
    )

    return {
        "hash":         hex_digest,
        "tx_hash":      tx_hash if tx_hash.startswith("0x") else "0x" + tx_hash,
        "block_number": receipt["blockNumber"],
        "gas_used":     receipt["gasUsed"],
        "tx_status":    receipt["status"],   # 1=success, 0=reverted
        "chain_backend": CHAIN_BACKEND,
        "anchor_mode":   ANCHOR_MODE,
        "rpc_url":       CHAIN_RPC_URL,
        "from_address":  account,
    }


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
        description="Anchor a match_record.json hash onto an EVM chain."
    )
    parser.add_argument("record_file", help="Path to match_record.json")
    parser.add_argument(
        "--index", type=int, default=-1,
        help="Which record to anchor (default: -1 = last/most-recent).",
    )
    args = parser.parse_args(argv)

    hex_digest, record = compute_hash_from_file(args.record_file, index=args.index)
    print(f"\n📋  Record SHA-256 : {hex_digest}")
    print(f"    image_path     : {record.get('image_path', '—')}")
    print(f"    top_match url  : {(record.get('top_match') or {}).get('source_url', '—')}")
    print(f"    anchor_mode    : {ANCHOR_MODE}")
    print(f"    chain_backend  : {CHAIN_BACKEND}\n")

    result = anchor_record(hex_digest)

    print("✅  Anchoring successful!")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
