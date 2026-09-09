"""
Real Trade via Jupiter V6 - Solana DEX Aggregator
Quote -> Swap -> Sign -> Send
"""
import os
import json
import time
import base64
import requests

JUPITER_BASE = "https://quote-api.jup.ag/v6"
SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

SLIPPAGE_BPS = int(os.environ.get("SLIPPAGE_BPS", 500))  # 5%
PRIORITY_FEE = int(os.environ.get("PRIORITY_FEE_LAMPORTS", 1000000))  # 0.001 SOL
MAX_PRICE_IMPACT = 5.0  # reject if > 5%

HEADERS = {"User-Agent": "meme-screener-trade/1.0"}

def is_configured():
    """Cek apakah real trade sudah dikonfigurasi"""
    return bool(os.environ.get("SOLANA_RPC")) and bool(os.environ.get("PRIVATE_KEY"))

def get_wallet():
    """Load wallet dari PRIVATE_KEY env"""
    pk = os.environ.get("PRIVATE_KEY", "")
    if not pk:
        return None, "PRIVATE_KEY not set"
    try:
        import base58
        from solders.keypair import Keypair
        decoded = base58.b58decode(pk)
        if len(decoded) == 64:
            keypair = Keypair.from_bytes(decoded)
        elif len(decoded) == 32:
            keypair = Keypair.from_seed(decoded)
        else:
            return None, "Invalid private key length"
        return keypair, None
    except Exception as e:
        return None, str(e)

def get_sol_balance():
    """Cek SOL balance wallet"""
    rpc = os.environ.get("SOLANA_RPC", "")
    keypair, err = get_wallet()
    if err:
        return None, err
    try:
        from solana.rpc.api import Client
        from solders.pubkey import Pubkey
        client = Client(rpc)
        pubkey = keypair.pubkey()
        resp = client.get_balance(pubkey)
        lamports = resp.value
        sol = lamports / 1e9
        return {"sol": sol, "lamports": lamports, "address": str(pubkey)}, None
    except Exception as e:
        return None, str(e)

def get_quote(input_mint, output_mint, amount):
    """
    Step 1: Get best route from Jupiter
    amount: in smallest unit (lamports for SOL, raw for tokens)
    """
    try:
        resp = requests.get(f"{JUPITER_BASE}/quote", params={
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": int(amount),
            "slippageBps": SLIPPAGE_BPS,
        }, headers=HEADERS, timeout=10)
        if resp.status_code == 400:
            return None, "No route found - token may have no liquidity"
        if resp.status_code == 429:
            return None, "Rate limited - try again in a few seconds"
        resp.raise_for_status()
        quote = resp.json()
        impact = abs(float(quote.get("priceImpactPct", 0)))
        if impact > MAX_PRICE_IMPACT:
            return None, f"Price impact too high: {impact:.1f}% (max {MAX_PRICE_IMPACT}%)"
        return quote, None
    except requests.exceptions.Timeout:
        return None, "Jupiter API timeout"
    except Exception as e:
        return None, str(e)

def build_swap_transaction(quote):
    """Step 2: Build swap transaction from quote"""
    keypair, err = get_wallet()
    if err:
        return None, err
    try:
        resp = requests.post(f"{JUPITER_BASE}/swap", json={
            "quoteResponse": quote,
            "userPublicKey": str(keypair.pubkey()),
            "wrapAndUnwrapSol": True,
            "prioritizationFeeLamports": PRIORITY_FEE,
            "dynamicComputeUnitLimit": True,
        }, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return data.get("swapTransaction"), None
    except Exception as e:
        return None, str(e)

def sign_and_send(swap_tx_b64):
    """Step 3: Sign transaction and send to Solana"""
    keypair, err = get_wallet()
    if err:
        return None, err
    rpc = os.environ.get("SOLANA_RPC", "")
    if not rpc:
        return None, "SOLANA_RPC not set"
    try:
        import base58 as b58
        from solders.transaction import VersionedTransaction
        from solana.rpc.api import Client
        from solana.rpc.types import TxOpts

        tx_bytes = base64.b64decode(swap_tx_b64)
        tx = VersionedTransaction.from_bytes(tx_bytes)

        # Sign the transaction
        signed_tx = VersionedTransaction(tx.message, [keypair])

        # Send
        client = Client(rpc)
        opts = TxOpts(skip_preflight=False, preflight_commitment="processed")
        result = client.send_raw_transaction(bytes(signed_tx), opts)
        tx_sig = result.value
        return {"signature": str(tx_sig), "explorer": f"https://solscan.io/tx/{tx_sig}"}, None
    except Exception as e:
        return None, str(e)

def wait_confirmation(sig, timeout=60):
    """Wait for transaction confirmation"""
    rpc = os.environ.get("SOLANA_RPC", "")
    if not rpc:
        return None, "SOLANA_RPC not set"
    try:
        from solana.rpc.api import Client
        from solders.signature import Signature
        client = Client(rpc)
        sig_obj = Signature.from_string(sig)
        start = time.time()
        while time.time() - start < timeout:
            resp = client.get_signature_statuses([sig_obj])
            if resp.value and resp.value[0]:
                status = resp.value[0]
                if status.confirmation_status in ("confirmed", "finalized"):
                    return {"confirmed": True, "slot": status.slot}, None
            time.sleep(2)
        return None, "Confirmation timeout"
    except Exception as e:
        return None, str(e)

# --- High Level API ---

def real_buy(mint, amount_sol, slippage_bps=None):
    """
    Real buy token via Jupiter
    amount_sol: how much SOL to spend
    """
    if not is_configured():
        return {"error": "Real trade not configured - set SOLANA_RPC & PRIVATE_KEY"}

    keypair, err = get_wallet()
    if err:
        return {"error": err}

    # Get SOL balance
    bal, err = get_sol_balance()
    if err:
        return {"error": f"Cannot check balance: {err}"}
    if bal["sol"] < amount_sol + 0.01:  # reserve 0.01 SOL for fees
        return {"error": f"Insufficient SOL: {bal['sol']:.4f} (need {amount_sol + 0.01:.4f})"}

    # Amount in lamports
    lamports = int(amount_sol * 1e9)

    # Step 1: Quote
    quote, err = get_quote(SOL_MINT, mint, lamports)
    if err:
        return {"error": f"Quote failed: {err}"}

    out_amount = int(quote.get("outAmount", 0))
    price_impact = abs(float(quote.get("priceImpactPct", 0)))

    # Step 2: Build swap
    swap_tx, err = build_swap_transaction(quote)
    if err:
        return {"error": f"Build swap failed: {err}"}

    # Step 3: Sign & send
    result, err = sign_and_send(swap_tx)
    if err:
        return {"error": f"Send failed: {err}"}

    return {
        "ok": True,
        "type": "BUY",
        "mint": mint,
        "sol_spent": amount_sol,
        "tokens_received": out_amount,
        "price_impact": price_impact,
        "tx": result["signature"],
        "explorer": result["explorer"],
    }

def real_sell(mint, token_amount, decimals=9, slippage_bps=None):
    """
    Real sell token via Jupiter
    token_amount: amount in smallest unit (raw token amount)
    """
    if not is_configured():
        return {"error": "Real trade not configured"}

    keypair, err = get_wallet()
    if err:
        return {"error": err}

    # Step 1: Quote (token -> SOL)
    quote, err = get_quote(mint, SOL_MINT, int(token_amount))
    if err:
        return {"error": f"Quote failed: {err}"}

    out_lamports = int(quote.get("outAmount", 0))
    sol_received = out_lamports / 1e9
    price_impact = abs(float(quote.get("priceImpactPct", 0)))

    # Step 2: Build swap
    swap_tx, err = build_swap_transaction(quote)
    if err:
        return {"error": f"Build swap failed: {err}"}

    # Step 3: Sign & send
    result, err = sign_and_send(swap_tx)
    if err:
        return {"error": f"Send failed: {err}"}

    return {
        "ok": True,
        "type": "SELL",
        "mint": mint,
        "tokens_sold": token_amount,
        "sol_received": sol_received,
        "price_impact": price_impact,
        "tx": result["signature"],
        "explorer": result["explorer"],
    }
