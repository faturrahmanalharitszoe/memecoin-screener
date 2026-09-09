"""
Based Bot - Paper trade via Supabase, real trade via Jupiter
"""
import os
import json
from datetime import datetime, timezone

# --- Supabase Client ---
_sb = None

def _get_sb():
    global _sb
    if _sb is not None:
        return _sb
    url = os.environ.get("SUPABASE_URL", "")
    key = os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        print("[PAPER] SUPABASE_URL or SUPABASE_KEY not set")
        return None
    try:
        from supabase import create_client
        _sb = create_client(url, key)
        print("[PAPER] Supabase connected OK")
        return _sb
    except Exception as e:
        print("[PAPER] Supabase init error:", e)
        return None

INITIAL_BALANCE = 10000  # $10k paper

def _get_or_create_portfolio(sb, user_id="default"):
    """Ambil atau buat portfolio"""
    res = sb.table("paper_portfolios").select("*").eq("user_id", user_id).execute()
    if res.data:
        return res.data[0]
    # buat baru
    new = {
        "user_id": user_id,
        "balance_usd": INITIAL_BALANCE,
        "total_pnl": 0,
        "win_trades": 0,
        "loss_trades": 0,
    }
    res = sb.table("paper_portfolios").insert(new).execute()
    return res.data[0]

def _get_positions(sb, portfolio_id):
    res = sb.table("paper_positions").select("*").eq("portfolio_id", portfolio_id).execute()
    return {r["mint"]: r for r in (res.data or [])}

def _add_trade(sb, portfolio_id, trade):
    trade["portfolio_id"] = portfolio_id
    sb.table("paper_trades").insert(trade).execute()

def _update_portfolio(sb, portfolio_id, updates):
    sb.table("paper_portfolios").update(updates).eq("id", portfolio_id).execute()

def _upsert_position(sb, portfolio_id, mint, data):
    data["portfolio_id"] = portfolio_id
    data["mint"] = mint
    existing = sb.table("paper_positions").select("id").eq("portfolio_id", portfolio_id).eq("mint", mint).execute()
    if existing.data:
        sb.table("paper_positions").update(data).eq("id", existing.data[0]["id"]).execute()
    else:
        sb.table("paper_positions").insert(data).execute()

def _delete_position(sb, portfolio_id, mint):
    sb.table("paper_positions").delete().eq("portfolio_id", portfolio_id).eq("mint", mint).execute()

# --- Public API ---

def paper_buy(mint, symbol, price, size_pct=2, reason="bagger signal"):
    sb = _get_sb()
    if not sb:
        return {"error": "Supabase not configured - set SUPABASE_URL & SUPABASE_KEY"}
    try:
        port = _get_or_create_portfolio(sb)
        pid = port["id"]
        balance = float(port["balance_usd"])
        size_usd = balance * (size_pct / 100)
        if size_usd < 10:
            return {"error": "balance too small"}
        if size_usd > balance:
            return {"error": "insufficient balance"}

        amount = size_usd / price if price else 0
        positions = _get_positions(sb, pid)

        if mint in positions:
            pos = positions[mint]
            old_amount = float(pos["amount"])
            old_cost = float(pos["size_usd"])
            new_amount = old_amount + amount
            new_cost = old_cost + size_usd
            new_entry = new_cost / new_amount if new_amount else price
            _upsert_position(sb, pid, mint, {
                "symbol": symbol,
                "amount": new_amount,
                "entry_price": new_entry,
                "size_usd": new_cost,
            })
        else:
            _upsert_position(sb, pid, mint, {
                "symbol": symbol,
                "amount": amount,
                "entry_price": price,
                "size_usd": size_usd,
                "entry_time": datetime.now(timezone.utc).isoformat(),
            })

        _update_portfolio(sb, pid, {"balance_usd": balance - size_usd})

        _add_trade(sb, pid, {
            "type": "BUY", "mint": mint, "symbol": symbol,
            "price": price, "amount": amount, "size_usd": size_usd,
            "reason": reason,
            "time": datetime.now(timezone.utc).isoformat(),
        })

        return {"ok": True, "trade": {"type": "BUY", "mint": mint, "symbol": symbol, "price": price, "amount": amount, "size_usd": size_usd}}
    except Exception as e:
        return {"error": str(e)}

def paper_sell(mint, price, pct=100, reason="take profit"):
    sb = _get_sb()
    if not sb:
        return {"error": "Supabase not configured"}
    try:
        port = _get_or_create_portfolio(sb)
        pid = port["id"]
        positions = _get_positions(sb, pid)
        if mint not in positions:
            return {"error": "no position"}
        pos = positions[mint]
        sell_amount = float(pos["amount"]) * (pct / 100)
        sell_usd = sell_amount * price
        entry_usd = sell_amount * float(pos["entry_price"])
        pnl = sell_usd - entry_usd
        pnl_pct = (pnl / entry_usd * 100) if entry_usd else 0

        remaining = float(pos["amount"]) - sell_amount
        if remaining <= 0.000001:
            _delete_position(sb, pid, mint)
        else:
            _upsert_position(sb, pid, mint, {
                "amount": remaining,
                "size_usd": float(pos["size_usd"]) - entry_usd,
            })

        new_balance = float(port["balance_usd"]) + sell_usd
        new_pnl = float(port["total_pnl"]) + pnl
        wins = int(port["win_trades"]) + (1 if pnl > 0 else 0)
        losses = int(port["loss_trades"]) + (0 if pnl > 0 else 1)
        _update_portfolio(sb, pid, {
            "balance_usd": new_balance,
            "total_pnl": new_pnl,
            "win_trades": wins,
            "loss_trades": losses,
        })

        _add_trade(sb, pid, {
            "type": "SELL", "mint": mint, "symbol": pos.get("symbol", ""),
            "price": price, "amount": sell_amount, "size_usd": sell_usd,
            "pnl": pnl, "pnl_pct": pnl_pct, "reason": reason,
            "time": datetime.now(timezone.utc).isoformat(),
        })

        return {"ok": True, "pnl": pnl, "pnl_pct": pnl_pct}
    except Exception as e:
        return {"error": str(e)}

def get_portfolio():
    sb = _get_sb()
    if not sb:
        return {"balance_usd": INITIAL_BALANCE, "positions": {}, "total_pnl": 0, "total_unrealized": 0, "win_trades": 0, "loss_trades": 0, "trades": []}
    try:
        port = _get_or_create_portfolio(sb)
        pid = port["id"]
        positions = _get_positions(sb, pid)
        # fetch trades
        trades_res = sb.table("paper_trades").select("*").eq("portfolio_id", pid).order("time", desc=True).limit(10).execute()
        trades = trades_res.data or []

        pos_summary = {}
        total_unrealized = 0
        for mint, pos in positions.items():
            entry = float(pos.get("entry_price", 0))
            amount = float(pos.get("amount", 0))
            size = float(pos.get("size_usd", 0))
            current = entry  # will be updated by frontend with live price
            unrealized = 0
            roi_pct = 0
            total_unrealized += unrealized
            pos_summary[mint] = {
                "symbol": pos.get("symbol", ""),
                "amount": amount,
                "entry_price": entry,
                "current_price": current,
                "size_usd": size,
                "unrealized_pnl": round(unrealized, 2),
                "roi_pct": round(roi_pct, 1),
            }

        return {
            "balance_usd": float(port.get("balance_usd", INITIAL_BALANCE)),
            "positions": pos_summary,
            "total_pnl": float(port.get("total_pnl", 0)),
            "total_unrealized": round(total_unrealized, 2),
            "win_trades": int(port.get("win_trades", 0)),
            "loss_trades": int(port.get("loss_trades", 0)),
            "trades": trades,
        }
    except Exception as e:
        return {"error": str(e)}
