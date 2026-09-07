"""
Based Bot - Paper trade dulu, siap real via Jupiter
"""
import json
import os
import time
from datetime import datetime, timezone

PAPER_FILE = os.path.join(os.path.dirname(__file__), "paper_portfolio.json")
INITIAL_BALANCE = 10000  # $10k paper

def load_portfolio():
    if os.path.exists(PAPER_FILE):
        try:
            with open(PAPER_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {
        "balance_usd": INITIAL_BALANCE,
        "positions": {},  # mint -> {amount, entry_price, entry_time, size_usd}
        "trades": [],  # history
        "total_pnl": 0,
        "win_trades": 0,
        "loss_trades": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

def save_portfolio(port):
    with open(PAPER_FILE, "w") as f:
        json.dump(port, f, indent=2)

def paper_buy(mint, symbol, price, size_pct=2, reason="bagger signal"):
    """Paper buy 2% portfolio"""
    port = load_portfolio()
    size_usd = port["balance_usd"] * (size_pct / 100)
    if size_usd < 10:
        return {"error": "balance too small"}
    if size_usd > port["balance_usd"]:
        return {"error": "insufficient balance"}
    
    amount = size_usd / price if price else 0
    # deduct balance
    port["balance_usd"] -= size_usd
    # add position
    if mint not in port["positions"]:
        port["positions"][mint] = {"symbol": symbol, "amount": 0, "entry_price": price, "entry_time": datetime.now(timezone.utc).isoformat(), "size_usd": 0}
    pos = port["positions"][mint]
    # avg entry
    total_amount = pos["amount"] + amount
    total_cost = pos["size_usd"] + size_usd
    pos["entry_price"] = total_cost / total_amount if total_amount else price
    pos["amount"] = total_amount
    pos["size_usd"] = total_cost
    
    trade = {
        "type": "BUY",
        "mint": mint,
        "symbol": symbol,
        "price": price,
        "amount": amount,
        "size_usd": size_usd,
        "reason": reason,
        "time": datetime.now(timezone.utc).isoformat(),
        "paper": True,
    }
    port["trades"].append(trade)
    save_portfolio(port)
    return {"ok": True, "trade": trade, "portfolio": port}

def paper_sell(mint, price, pct=100, reason="take profit"):
    """Paper sell pct of position"""
    port = load_portfolio()
    if mint not in port["positions"]:
        return {"error": "no position"}
    pos = port["positions"][mint]
    sell_amount = pos["amount"] * (pct / 100)
    sell_usd = sell_amount * price
    entry_usd = sell_amount * pos["entry_price"]
    pnl = sell_usd - entry_usd
    pnl_pct = (pnl / entry_usd * 100) if entry_usd else 0

    # update position
    pos["amount"] -= sell_amount
    pos["size_usd"] -= entry_usd
    if pos["amount"] <= 0.000001:
        del port["positions"][mint]
    
    port["balance_usd"] += sell_usd
    port["total_pnl"] += pnl
    if pnl > 0:
        port["win_trades"] += 1
    else:
        port["loss_trades"] += 1

    trade = {
        "type": "SELL",
        "mint": mint,
        "symbol": pos.get("symbol", ""),
        "price": price,
        "amount": sell_amount,
        "size_usd": sell_usd,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
        "reason": reason,
        "time": datetime.now(timezone.utc).isoformat(),
        "paper": True,
    }
    port["trades"].append(trade)
    save_portfolio(port)
    return {"ok": True, "trade": trade, "portfolio": port, "pnl": pnl}

def check_tp_sl():
    """Cek TP 100% (2x) dan SL -50% untuk semua posisi - dipanggil tiap price poll"""
    port = load_portfolio()
    # perlu fetch price live untuk tiap posisi - akan dipanggil dari dashboard dengan price terbaru
    # untuk sekarang, return info aja
    return port

def get_portfolio():
    return load_portfolio()

# Real trade via Jupiter (siap, tapi paper dulu)
def real_trade_via_jupiter(mint, amount, side="buy"):
    """Siap untuk real trade - butuh private key dan RPC. Untuk sekarang return paper."""
    # TODO: integrasi Jupiter Swap API
    # POST https://quote-api.jup.ag/v6/quote?inputMint=So111...&outputMint={mint}&amount={amount}&slippageBps=100
    # POST https://quote-api.jup.ag/v6/swap
    # sign & send via solana-py
    return {"paper": True, "message": "Real trade siap - set PRIVATE_KEY env dan uncomment Jupiter code di paper_bot.py:real_trade_via_jupiter"}
