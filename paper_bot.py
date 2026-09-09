"""
Based Bot - Paper trade dulu, siap real via Jupiter
"""
import json
import os
import base64
from datetime import datetime, timezone

INITIAL_BALANCE = 10000  # $10k paper

def _load_from_env():
    """Load portfolio dari env var (persistent across restarts)"""
    data = os.environ.get("PAPER_PORTFOLIO", "")
    if data:
        try:
            return json.loads(base64.b64decode(data).decode("utf-8"))
        except:
            pass
    return None

def _save_to_env(port):
    """Save portfolio ke env var via runtime os.environ (persist di memory selama process hidup)"""
    try:
        encoded = base64.b64encode(json.dumps(port).encode("utf-8")).decode("utf-8")
        os.environ["PAPER_PORTFOLIO"] = encoded
    except:
        pass

def _new_portfolio():
    return {
        "balance_usd": INITIAL_BALANCE,
        "positions": {},
        "trades": [],
        "total_pnl": 0,
        "win_trades": 0,
        "loss_trades": 0,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

# In-memory cache (survives as long as process lives)
_PORT = None

def load_portfolio():
    global _PORT
    if _PORT is not None:
        return _PORT
    _PORT = _load_from_env() or _new_portfolio()
    return _PORT

def save_portfolio(port):
    global _PORT
    _PORT = port
    _save_to_env(port)

def paper_buy(mint, symbol, price, size_pct=2, reason="bagger signal"):
    port = load_portfolio()
    size_usd = port["balance_usd"] * (size_pct / 100)
    if size_usd < 10:
        return {"error": "balance too small"}
    if size_usd > port["balance_usd"]:
        return {"error": "insufficient balance"}
    
    amount = size_usd / price if price else 0
    port["balance_usd"] -= size_usd
    if mint not in port["positions"]:
        port["positions"][mint] = {"symbol": symbol, "amount": 0, "entry_price": price, "entry_time": datetime.now(timezone.utc).isoformat(), "size_usd": 0}
    pos = port["positions"][mint]
    total_amount = pos["amount"] + amount
    total_cost = pos["size_usd"] + size_usd
    pos["entry_price"] = total_cost / total_amount if total_amount else price
    pos["amount"] = total_amount
    pos["size_usd"] = total_cost
    
    trade = {
        "type": "BUY", "mint": mint, "symbol": symbol, "price": price,
        "amount": amount, "size_usd": size_usd, "reason": reason,
        "time": datetime.now(timezone.utc).isoformat(), "paper": True,
    }
    port["trades"].append(trade)
    save_portfolio(port)
    return {"ok": True, "trade": trade, "portfolio": get_portfolioSummary(port)}

def paper_sell(mint, price, pct=100, reason="take profit"):
    port = load_portfolio()
    if mint not in port["positions"]:
        return {"error": "no position"}
    pos = port["positions"][mint]
    sell_amount = pos["amount"] * (pct / 100)
    sell_usd = sell_amount * price
    entry_usd = sell_amount * pos["entry_price"]
    pnl = sell_usd - entry_usd
    pnl_pct = (pnl / entry_usd * 100) if entry_usd else 0

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
        "type": "SELL", "mint": mint, "symbol": pos.get("symbol", ""),
        "price": price, "amount": sell_amount, "size_usd": sell_usd,
        "pnl": pnl, "pnl_pct": pnl_pct, "reason": reason,
        "time": datetime.now(timezone.utc).isoformat(), "paper": True,
    }
    port["trades"].append(trade)
    save_portfolio(port)
    return {"ok": True, "trade": trade, "portfolio": get_portfolioSummary(port), "pnl": pnl, "pnl_pct": pnl_pct}

def get_portfolioSummary(port=None):
    if port is None:
        port = load_portfolio()
    pos_summary = {}
    total_unrealized = 0
    for mint, pos in port.get("positions", {}).items():
        entry = pos.get("entry_price", 0)
        amount = pos.get("amount", 0)
        size = pos.get("size_usd", 0)
        current = pos.get("current_price", entry)
        unrealized = (current - entry) * amount if current and entry else 0
        roi_pct = ((current - entry) / entry * 100) if entry and current else 0
        total_unrealized += unrealized
        pos_summary[mint] = {
            "symbol": pos.get("symbol", ""), "amount": amount,
            "entry_price": entry, "current_price": current,
            "size_usd": size, "unrealized_pnl": round(unrealized, 2),
            "roi_pct": round(roi_pct, 1),
        }
    total_value = port.get("balance_usd", 0) + sum(p["size_usd"] for p in pos_summary.values()) + total_unrealized
    return {
        "balance_usd": port.get("balance_usd", 0),
        "positions": pos_summary,
        "total_value": round(total_value, 2),
        "total_pnl": port.get("total_pnl", 0),
        "total_unrealized": round(total_unrealized, 2),
        "win_trades": port.get("win_trades", 0),
        "loss_trades": port.get("loss_trades", 0),
        "trades": port.get("trades", [])[-10:],
    }

def get_portfolio():
    return get_portfolioSummary()

def real_trade_via_jupiter(mint, amount, side="buy"):
    return {"paper": True, "message": "Real trade siap - set PRIVATE_KEY env"}
