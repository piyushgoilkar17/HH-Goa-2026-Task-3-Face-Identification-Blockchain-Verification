"""
contracts/deploy.py
-------------------
Compiles and deploys FaceVerifyChain.sol to the configured EVM network.

Requirements
------------
  pip3 install web3 py-solc-x

Usage
-----
  # Deploy to local Ganache (default):
  python contracts/deploy.py

  # Deploy to Polygon Amoy testnet (set env vars first):
  CHAIN_BACKEND=custom \\
  CHAIN_RPC_URL=https://polygon-amoy-bor-rpc.publicnode.com \\
  CHAIN_PRIVATE_KEY=0x... \\
  python contracts/deploy.py

After deployment the script prints the contract address and writes it to .env
as CONTRACT_ADDRESS=0x...

Notes on Polygon Amoy
----------------------
  - Get free test POL at https://faucet.polygon.technology (select "Amoy")
  - Free RPCs: https://polygon-amoy-bor-rpc.publicnode.com  or  Alchemy/Infura
  - Amoy chain_id = 80002
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

CHAIN_BACKEND     = os.getenv("CHAIN_BACKEND", "ganache").lower()
CHAIN_RPC_URL     = os.getenv("CHAIN_RPC_URL", "http://127.0.0.1:8545")
CHAIN_PRIVATE_KEY = os.getenv("CHAIN_PRIVATE_KEY", "")

SOL_PATH = Path(__file__).parent / "FaceVerifyChain.sol"
ENV_PATH  = Path(__file__).parent.parent / ".env"


def _install_solc():
    """Install solc 0.8.20 via py-solc-x if not already available."""
    try:
        from solcx import install_solc, set_solc_version
        install_solc("0.8.20", show_progress=True)
        set_solc_version("0.8.20")
        logger.info("solc 0.8.20 ready.")
    except ImportError:
        raise RuntimeError(
            "py-solc-x is not installed. Run: pip3 install py-solc-x"
        )


def _compile_contract() -> dict:
    """Compile FaceVerifyChain.sol and return the ABI + bytecode."""
    from solcx import compile_source

    source = SOL_PATH.read_text(encoding="utf-8")
    compiled = compile_source(
        source,
        output_values=["abi", "bin"],
        solc_version="0.8.20",
    )
    # Key is "<stdin>:FaceVerifyChain" when compiled from a string
    key = next(k for k in compiled if "FaceVerifyChain" in k)
    abi      = compiled[key]["abi"]
    bytecode = compiled[key]["bin"]
    logger.info("Compiled successfully. Bytecode: %d bytes", len(bytecode) // 2)
    return {"abi": abi, "bytecode": bytecode}


def _get_web3():
    from web3 import Web3
    w3 = Web3(Web3.HTTPProvider(CHAIN_RPC_URL))

    if CHAIN_BACKEND != "ganache":
        try:
            from web3.middleware import geth_poa_middleware
            w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        except ImportError:
            from web3.middleware import ExtraDataToPOAMiddleware
            w3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)

    if not w3.is_connected():
        raise RuntimeError(
            f"Cannot connect to {CHAIN_RPC_URL}. "
            "Start Ganache: npx ganache  or  ganache-cli"
        )
    logger.info("Connected to %s (chain_id=%s)", CHAIN_RPC_URL, w3.eth.chain_id)
    return w3


def deploy() -> str:
    """
    Compile and deploy the contract. Returns the deployed contract address.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(message)s",
        datefmt="%H:%M:%S",
    )

    print("🔧  Installing solc 0.8.20...")
    _install_solc()

    print("📝  Compiling FaceVerifyChain.sol...")
    artifact = _compile_contract()

    w3 = _get_web3()

    # Determine deployer account
    if CHAIN_BACKEND == "ganache" and not CHAIN_PRIVATE_KEY:
        deployer   = w3.eth.accounts[0]
        private_key = None
        print(f"🏦  Using Ganache account[0]: {deployer}")
    else:
        if not CHAIN_PRIVATE_KEY:
            raise RuntimeError("CHAIN_PRIVATE_KEY must be set for non-Ganache deployments.")
        acct = w3.eth.account.from_key(CHAIN_PRIVATE_KEY)
        deployer    = acct.address
        private_key = CHAIN_PRIVATE_KEY
        print(f"🏦  Deploying from: {deployer}")

    contract = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])

    if private_key:
        tx = contract.constructor().build_transaction({
            "from":     deployer,
            "gas":      500_000,
            "gasPrice": w3.eth.gas_price,
            "nonce":    w3.eth.get_transaction_count(deployer),
            "chainId":  w3.eth.chain_id,
        })
        signed  = w3.eth.account.sign_transaction(tx, private_key)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    else:
        tx_hash = contract.constructor().transact({
            "from":  deployer,
            "gas":   500_000,
        })

    print(f"📡  Deploy tx: {tx_hash.hex() if hasattr(tx_hash, 'hex') else tx_hash}")
    print("⏳  Waiting for confirmation...")

    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    contract_address = receipt["contractAddress"]

    print(f"\n✅  Contract deployed at: {contract_address}")
    print(f"    Block  : {receipt['blockNumber']}")
    print(f"    Gas    : {receipt['gasUsed']}")

    # Save ABI alongside the contract source
    abi_path = Path(__file__).parent / "FaceVerifyChain.abi.json"
    abi_path.write_text(json.dumps(artifact["abi"], indent=2), encoding="utf-8")
    print(f"    ABI saved to: {abi_path}")

    # Append CONTRACT_ADDRESS to .env
    _update_env(contract_address)
    print(f"    CONTRACT_ADDRESS written to {ENV_PATH}")
    print("\nRun verification with:")
    print("  python -m chain.verify match_record.json")

    return contract_address


def _update_env(address: str) -> None:
    """Add or replace CONTRACT_ADDRESS in .env."""
    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
        new_lines = [l for l in lines if not l.startswith("CONTRACT_ADDRESS=")]
    else:
        new_lines = []
    new_lines.append(f"CONTRACT_ADDRESS={address}")
    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    deploy()
