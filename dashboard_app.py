#!/usr/bin/env python3
"""
Dashboard Flask untuk Meme Screener Solana
Run: py dashboard_app.py
Open: http://localhost:5000
Stack: Flask + Tailwind CDN + Chart.js
Reuses meme_screener.py logic (free stack) + social velocity
"""
import os
import time
import json
from datetime import datetime, timezone
from flask import Flask, jsonify, request, send_from_directory
import requests

# Reuse logic dari meme_screener.py
try:
    from bagger import fetch_trending_solana, is_bagger_candidate
    from whale_tracker import get_robinhood_wallets, analyze_whale_flow, get_bagger_whales
    from paper_bot import paper_buy, paper_sell, get_portfolio
except ImportError:
    fetch_trending_solana = is_bagger_candidate = None
    get_robinhood_wallets = analyze_whale_flow = get_bagger_whales = None
    paper_buy = paper_sell = get_portfolio = None

try:
    from meme_screener import (
        fetch_dexscreener,
        fetch_rugcheck,
        fetch_coingecko_context,
        fetch_coingecko_token_by_search,
        calculate_durability,
        attribute_move,
        WIF_MINT,
        BONK_MINT,
    )
except ImportError:
    # fallback jika run dari folder berbeda
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from meme_screener import (
        fetch_dexscreener,
        fetch_rugcheck,
        fetch_coingecko_context,
        fetch_coingecko_token_by_search,
        calculate_durability,
        attribute_move,
        WIF_MINT,
        BONK_MINT,
    )

app = Flask(__name__)

# Staggered cache biar real-time tanpa kena limit:
# DexScreener (price/vol/tx) 10s, RugCheck/GoPlus (holder) 300s, CoinGecko (BTC/SOL) 60s
CACHE = {}
CACHE_TTL_PRICE = 10
CACHE_TTL_HOLDER = 300
CACHE_TTL_BTC = 60
CACHE_TTL_CG_TOKEN = 60
CACHE_TTL_SOCIAL = 30
CACHE_TTL = 60  # fallback

# Mapping symbol untuk LunarCrush & CoinGecko
KNOWN = {
    WIF_MINT: {"cg": "dogwifcoin", "symbol": "WIF", "name": "dogwifhat"},
    BONK_MINT: {"cg": "bonk", "symbol": "BONK", "name": "Bonk"},
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": {"cg": "usd-coin", "symbol": "USDC", "name": "USD Coin"},
    "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R": {"cg": "raydium", "symbol": "RAY", "name": "Raydium"},
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": {"cg": "bonk", "symbol": "BONK", "name": "Bonk"},
}

POPCAT_MINT = "5dYN9EvQdJ1c3c2pZ9c2pZ9c2pZ9c2pZ9c2pZ9c2pZ9c2p"
PUMP_MINT = "9zCN...dummy"

LUNAR_KEY = os.getenv("LUNARCRUSH_API_KEY", "").strip()

def get_cached(key, fetch_fn, ttl=None):
    ttl = ttl if ttl is not None else CACHE_TTL
    now = time.time()
    if key in CACHE and now - CACHE[key]["ts"] < ttl:
        return CACHE[key]["data"]
    data = fetch_fn()
    # cache error juga tapi cuma 5 detik biar tidak hammer DexScreener pas timeout
    is_error = False
    if isinstance(data, tuple) and len(data)==2 and data[0] is None:
        is_error = True
    if is_error:
        CACHE[key] = {"ts": now - ttl + 5, "data": data}  # cache 5 detik saja untuk error
    else:
        CACHE[key] = {"ts": now, "data": data}
    return data

def get_cached_ttl(key, ttl):
    """Cek cache tanpa fetch, return (data, age) atau (None, None) jika expired"""
    now = time.time()
    if key in CACHE and now - CACHE[key]["ts"] < ttl:
        return CACHE[key]["data"], now - CACHE[key]["ts"]
    return None, None

def fetch_social_velocity(mint, dex, cg_token):
    """
    Social velocity free tier:
    - CoinGecko community_data (telegram, twitter, reddit) jika large cap
    - Tx velocity proxy (buy/sell ratio, volume momentum) - selalu ada dari DexScreener
    - LunarCrush jika LUNARCRUSH_API_KEY tersedia (real social velocity)
    Returns dict dengan skor 0-100
    """
    social = {
        "tx_velocity": {},
        "community": {},
        "lunarcrush": None,
        "score": 50,
        "interpretation": "NEUTRAL",
        "details": []
    }

    # 1. Tx velocity proxy (selalu ada, gratis)
    if dex:
        buys24 = dex.get("txns_24h_buys", 0)
        sells24 = dex.get("txns_24h_sells", 0)
        total24 = buys24 + sells24
        buy_ratio = (buys24 / total24 * 100) if total24 else 50
        vol24 = dex.get("total_vol_24h", 0)
        # volume momentum: h1 vs h6 vs h24
        best = dex.get("best_pair", {})
        vol_h1 = (best.get("volume") or {}).get("h1", 0) or 0
        vol_h6 = (best.get("volume") or {}).get("h6", 0) or 0
        # txns h1/h6 dari best pair
        tx_h1_buys = (best.get("txns") or {}).get("h1", {}).get("buys", 0) or 0
        tx_h1_sells = (best.get("txns") or {}).get("h1", {}).get("sells", 0) or 0
        tx_h6_buys = (best.get("txns") or {}).get("h6", {}).get("buys", 0) or 0
        tx_h6_sells = (best.get("txns") or {}).get("h6", {}).get("sells", 0) or 0

        social["tx_velocity"] = {
            "buys_24h": buys24,
            "sells_24h": sells24,
            "buy_ratio_24h": round(buy_ratio, 1),
            "total_tx_24h": total24,
            "vol_24h": vol24,
            "vol_h1": vol_h1,
            "vol_h6": vol_h6,
            "tx_h1": {"buys": tx_h1_buys, "sells": tx_h1_sells},
            "tx_h6": {"buys": tx_h6_buys, "sells": tx_h6_sells},
        }

        # Hitung skor velocity proxy
        # - Banyak tx = attention tinggi
        # - Buy ratio ekstrim = FOMO atau distribusi
        tx_score = 0
        if total24 > 1000:
            tx_score += 30
            social["details"].append(f"Tx tinggi {total24} /24h (+30)")
        elif total24 > 200:
            tx_score += 15
            social["details"].append(f"Tx sedang {total24} /24h (+15)")
        else:
            social["details"].append(f"Tx sepi {total24} /24h (+0)")

        if buy_ratio > 65:
            tx_score += 20
            social["details"].append(f"Buy ratio FOMO {buy_ratio:.0f}% (+20)")
        elif buy_ratio < 35:
            tx_score -= 10
            social["details"].append(f"Sell pressure {buy_ratio:.0f}% (-10)")
        else:
            tx_score += 5

        # volume momentum: jika vol h1 > vol h6/6 (rata2 per jam) = accelerating
        if vol_h6 > 0 and vol_h1 > (vol_h6 / 6) * 1.5:
            tx_score += 15
            social["details"].append(f"Volume accelerating h1 ${vol_h1:,.0f} > avg h6 (+15)")

        social["score"] = max(0, min(100, 50 + tx_score))
        if social["score"] >= 75:
            social["interpretation"] = "VIRAL / FOMO"
        elif social["score"] >= 60:
            social["interpretation"] = "ACCELERATING"
        elif social["score"] >= 40:
            social["interpretation"] = "NEUTRAL"
        else:
            social["interpretation"] = "FADING / DISTRIBUTION"

    # 2. CoinGecko community (jika large cap)
    cg_id = KNOWN.get(mint, {}).get("cg")
    if cg_id:
        try:
            # cache 60s
            def _fetch_cg():
                try:
                    r = requests.get(
                        f"https://api.coingecko.com/api/v3/coins/{cg_id}?localization=false&tickers=false&market_data=false&community_data=true&developer_data=false",
                        timeout=10,
                        headers={"User-Agent": "meme-screener/1.0"}
                    )
                    if r.status_code == 200:
                        j = r.json()
                        return {
                            "telegram": j.get("community_data", {}).get("telegram_channel_user_count"),
                            "reddit_sub": j.get("community_data", {}).get("reddit_subscribers"),
                            "twitter": j.get("links", {}).get("twitter_screen_name"),
                            "telegram_handle": j.get("links", {}).get("telegram_channel_identifier"),
                        }
                except:
                    pass
                return None
            comm = get_cached(f"cg_comm_{cg_id}", _fetch_cg, CACHE_TTL_CG_TOKEN)
            if comm:
                social["community"] = comm
                if comm.get("telegram"):
                    social["details"].append(f"Telegram {comm['telegram']} members")
        except:
            pass

    # 3. LunarCrush (jika ada API key) - real social velocity
    if LUNAR_KEY:
        symbol = KNOWN.get(mint, {}).get("symbol", "WIF")
        try:
            def _fetch_lunar():
                try:
                    # LunarCrush v4
                    headers = {"Authorization": f"Bearer {LUNAR_KEY}"}
                    # coba endpoint public coins
                    url = f"https://lunarcrush.com/api4/public/coins/{symbol.lower()}/v1"
                    r = requests.get(url, headers=headers, timeout=10)
                    if r.status_code == 200:
                        j = r.json()
                        data = j.get("data", j)
                        return {
                            "social_volume": data.get("social_volume"),
                            "social_volume_24h_change": data.get("social_volume_24h_change"),
                            "social_score": data.get("social_score"),
                            "galaxy_score": data.get("galaxy_score"),
                            "alt_rank": data.get("alt_rank"),
                            "interactions_24h": data.get("interactions_24h"),
                        }
                except Exception as e:
                    return {"error": str(e)}
                return None
            lunar = get_cached(f"lunar_{symbol}", _fetch_lunar, CACHE_TTL_SOCIAL)
            social["lunarcrush"] = lunar
            if lunar and not lunar.get("error") and lunar.get("social_volume"):
                ch = lunar.get("social_volume_24h_change") or 0
                try:
                    ch_f = float(ch)
                    if ch_f > 50:
                        social["score"] = min(100, social["score"] + 20)
                        social["details"].append(f"LunarCrush social volume +{ch_f:.0f}% (+20)")
                        social["interpretation"] = "VIRAL (LunarCrush)"
                    elif ch_f < -30:
                        social["score"] = max(0, social["score"] - 15)
                        social["details"].append(f"LunarCrush social fading {ch_f:.0f}% (-15)")
                except:
                    pass
        except:
            pass
    else:
        social["details"].append("LunarCrush API key belum set - set env LUNARCRUSH_API_KEY untuk social velocity real. Fallback ke Tx proxy + CoinGecko.")

    return social

@app.route("/api/price/<mint>")
def api_price(mint):
    """Fast price poll - 10s cache, cuma DexScreener (real-time tanpa kena limit)"""
    try:
        mint = mint.strip()
        def _fetch():
            return fetch_dexscreener(mint)
        cached = get_cached(f"dex_{mint}", _fetch, CACHE_TTL_PRICE)
        dex, dex_err = cached if isinstance(cached, tuple) else (cached, None)
        if not dex:
            return jsonify({"error": "dex not found", "dex_err": str(dex_err)}), 400
        return jsonify({
            "mint": mint,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dex": dex,
            "price_usd": dex.get("price_usd"),
            "priceChange": dex.get("priceChange"),
            "volume": dex.get("total_vol_24h"),
            "txns": {"buys": dex.get("txns_24h_buys"), "sells": dex.get("txns_24h_sells")},
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/screen/<mint>")
def api_screen(mint):
    try:
        mint = mint.strip()
        # Staggered cache: price 10s, holder 300s, btc 60s
        def _dex():
            return fetch_dexscreener(mint)
        def _rug():
            return fetch_rugcheck(mint)
        def _btc():
            return fetch_coingecko_context()
        def _cg():
            return fetch_coingecko_token_by_search(mint)

        dex_cached = get_cached(f"dex_{mint}", _dex, CACHE_TTL_PRICE)
        dex, dex_err = dex_cached if isinstance(dex_cached, tuple) else (dex_cached, None)

        rug_cached = get_cached(f"rug_{mint}", _rug, CACHE_TTL_HOLDER)
        rug, rug_err = rug_cached if isinstance(rug_cached, tuple) else (rug_cached, None)

        btc_cached = get_cached("btc_ctx", _btc, CACHE_TTL_BTC)
        if isinstance(btc_cached, tuple):
            btc_ctx, btc_err = btc_cached
        else:
            btc_ctx, btc_err = btc_cached, None
        if btc_err or not btc_ctx:
            btc_ctx = {"btc_24h_change": 0, "sol_24h_change": 0, "btc_price": None, "sol_price": None}

        cg_tok = get_cached(f"cg_{mint}", _cg, CACHE_TTL_CG_TOKEN)
        if isinstance(cg_tok, tuple):
            cg_tok = cg_tok[0] if len(cg_tok)>0 else None

        # override MCAP jika selisih besar (BONK case)
        if cg_tok and dex and cg_tok.get("market_cap"):
            dex_mcap = dex.get("market_cap") or 0
            cg_mcap = cg_tok["market_cap"]
            if dex_mcap and cg_mcap and abs(dex_mcap - cg_mcap) / max(cg_mcap, 1) > 0.5:
                dex["market_cap"] = cg_mcap
                if cg_tok.get("price_usd"):
                    dex["price_usd"] = cg_tok["price_usd"]

        if not dex or not rug:
            return jsonify({"error": "Data tidak lengkap", "dex_err": str(dex_err), "rug_err": str(rug_err)}), 400

        score, reasons, flags = calculate_durability(dex, rug, cg_tok)
        primary, attr_reasons = attribute_move(dex, rug, btc_ctx, cg_tok)
        social = fetch_social_velocity(mint, dex, cg_tok)

        # snapshot check
        snapshot_path = os.path.join(os.path.dirname(__file__), "snapshots", f"{mint[:8]}.json")
        snapshot_info = None
        if os.path.exists(snapshot_path):
            try:
                with open(snapshot_path, "r") as f:
                    old = json.load(f)
                snapshot_info = {
                    "exists": True,
                    "prev": old,
                    "prev_top10": old.get("top10_pct"),
                    "prev_price": old.get("price_usd"),
                    "prev_time": old.get("timestamp"),
                }
            except:
                snapshot_info = {"exists": False}
        else:
            snapshot_info = {"exists": False}

        result = {
            "mint": mint,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "dex": dex,
            "rug": {
                "score": rug.get("score"),
                "score_normalised": rug.get("score_normalised"),
                "total_holders": rug.get("total_holders"),
                "top5_pct": rug.get("top5_pct"),
                "top10_pct": rug.get("top10_pct"),
                "risks": rug.get("risks"),
                "top_holders": rug.get("top_holders")[:10] if rug.get("top_holders") else [],
                "insider_detected": rug.get("insider_detected"),
                "mintAuthority": rug.get("mintAuthority"),
                "freezeAuthority": rug.get("freezeAuthority"),
                "holder_unavailable": rug.get("holder_unavailable", False),
                "holder_source": rug.get("holder_source", "rugcheck"),
            },
            "btc_ctx": btc_ctx,
            "cg_token": cg_tok,
            "durability": {
                "score": score,
                "level": "AMAN" if score >=75 else "WASPADA" if score >=50 else "BERBAHAYA" if score >=30 else "EXTREME RISK",
                "reasons": reasons,
                "flags": flags,
            },
            "attribution": {
                "primary": primary,
                "reasons": attr_reasons,
                "priceChange": dex.get("priceChange"),
            },
            "social": social,
            "snapshot": snapshot_info,
        }

        return jsonify(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/snapshot/<mint>", methods=["POST"])
def api_snapshot(mint):
    dex, _ = fetch_dexscreener(mint)
    rug, _ = fetch_rugcheck(mint)
    if not dex or not rug:
        return jsonify({"error": "data missing"}), 400
    from meme_screener import save_snapshot
    old, new = save_snapshot(mint, dex, rug)
    return jsonify({"old": old, "new": new})

@app.route("/api/bagger")
def api_bagger():
    try:
        from meme_screener import fetch_dexscreener, fetch_rugcheck, calculate_durability
        from bagger import fetch_trending_solana, is_bagger_candidate, detect_whale_signal
        import time
        relaxed = request.args.get("relaxed") == "true"
        show_filtered = request.args.get("show_filtered") == "true"
        beyond = request.args.get("beyond") == "true"
        limit = int(request.args.get("limit") or 20)
        trending = fetch_trending_solana(limit=limit, beyond_trending=beyond)
        baggers = []
        filtered = []
        for tok in trending[:12]:  # scan 12 biar dpt lebih banyak
            mint = tok["mint"]
            try:
                dex,_ = fetch_dexscreener(mint)
                rug = None
                try:
                    rug,_ = fetch_rugcheck(mint)
                except:
                    pass
                if not dex:
                    continue
                # whale accumulation signal
                whale = detect_whale_signal(dex)
                # social & durability
                from dashboard_app import fetch_social_velocity, get_cached, CACHE_TTL_PRICE
                social = {"score": 50}
                try:
                    social = fetch_social_velocity(mint, dex, None)
                except:
                    pass
                score, _, _ = calculate_durability(dex, rug, None)
                is_bag, reason = is_bagger_candidate(dex, rug, social, score, relaxed=relaxed)
                # Whale signal kuat = otomatis bagger (early detection)
                whale_override = False
                if whale.get("signal") and whale.get("strength", 0) >= 40:
                    is_bag = True
                    reason = "WHALE SIGNAL (" + str(whale['strength']) + "): " + ", ".join(whale.get("reasons", []))
                    whale_override = True
                entry = {
                    "mint": mint,
                    "chain": tok.get("chain") or dex.get("best_pair",{}).get("chainId") or "solana",
                    "symbol": tok.get("symbol") or dex.get("best_pair",{}).get("baseToken",{}).get("symbol"),
                    "name": tok.get("name"),
                    "price": dex.get("price_usd"),
                    "mcap": dex.get("market_cap"),
                    "holders": (rug.get("total_holders") if rug else None),
                    "top10": (rug.get("top10_pct") if rug else None),
                    "score": score,
                    "social": social.get("score"),
                    "reason": reason,
                    "dex": dex.get("dex"),
                    "pairUrl": tok.get("pairUrl"),
                    "source": tok.get("source", "trending"),
                    "whale_signal": whale.get("signal", False),
                    "whale_strength": whale.get("strength", 0),
                    "whale_reasons": whale.get("reasons", []),
                }
                if is_bag:
                    baggers.append(entry)
                elif show_filtered:
                    entry["filtered_reason"] = reason
                    filtered.append(entry)
                time.sleep(0.1)
            except Exception as e:
                continue
        return jsonify({"baggers": baggers, "filtered": filtered, "scanned": len(trending), "relaxed": relaxed, "beyond": beyond, "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/whale/<mint>")
def api_whale(mint):
    try:
        from meme_screener import fetch_rugcheck
        from whale_tracker import analyze_whale_flow, get_bagger_whales, get_robinhood_wallets
        rug,_ = fetch_rugcheck(mint.strip())
        if not rug:
            return jsonify({"error": "rugcheck fail"}), 400
        flow = analyze_whale_flow(rug.get("top_holders", []))
        whales = get_bagger_whales(mint, rug.get("top_holders", []))
        robinhood = get_robinhood_wallets()
        return jsonify({
            "mint": mint,
            "total_holders": rug.get("total_holders"),
            "top10": rug.get("top10_pct"),
            "flow": flow,
            "whales": whales,
            "robinhood_wallets": robinhood,
            "holder_source": rug.get("holder_source"),
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/paper/portfolio")
def api_paper_portfolio():
    try:
        from paper_bot import get_portfolio
        return jsonify(get_portfolio())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/paper/prices")
def api_paper_prices():
    """Fetch live prices untuk semua posisi - dipanggil auto-refresh"""
    try:
        from paper_bot import get_portfolio
        port = get_portfolio()
        mints = list(port.get("positions", {}).keys())
        prices = {}
        for mint in mints[:8]:
            try:
                from meme_screener import fetch_dexscreener
                dex, _ = fetch_dexscreener(mint)
                if dex:
                    p = dex.get("price_usd") or dex.get("base_token_price_usd")
                    if p:
                        prices[mint] = float(p)
            except:
                pass
        return jsonify({"prices": prices})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/paper/buy", methods=["POST"])
def api_paper_buy():
    try:
        data = request.get_json() or {}
        mint = data.get("mint")
        price = float(data.get("price") or 0)
        symbol = data.get("symbol") or mint[:6]
        size_pct = float(data.get("size_pct") or 2)
        reason = data.get("reason") or "bagger"
        if not mint or not price:
            return jsonify({"error": "mint & price required"}), 400
        from paper_bot import paper_buy
        res = paper_buy(mint, symbol, price, size_pct, reason)
        return jsonify(res)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/paper/sell", methods=["POST"])
def api_paper_sell():
    try:
        data = request.get_json() or {}
        mint = data.get("mint")
        price = float(data.get("price") or 0)
        pct = float(data.get("pct") or 100)
        if not mint or not price:
            return jsonify({"error": "mint & price required"}), 400
        from paper_bot import paper_sell
        res = paper_sell(mint, price, pct, "manual")
        return jsonify(res)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/")
def index():
    return HTML

# HTML Dashboard - Tailwind CDN + Chart.js
HTML = r"""
<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Meme Screener Solana - Dashboard</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@500&display=swap" rel="stylesheet">
<style>
  body{font-family:Inter,sans-serif}
  .mono{font-family:'JetBrains Mono',monospace}
  .glass{backdrop-filter:blur(12px);background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.1)}
  .score-ring{transform:rotate(-90deg)}
</style>
</head>
<body class="bg-[#0a0a0f] text-white min-h-screen">
<!-- Header -->
<div class="border-b border-white/10 bg-[#111117] sticky top-0 z-50">
  <div class="max-w-[1400px] mx-auto px-4 py-4 flex flex-wrap gap-3 items-center justify-between">
    <div class="flex items-center gap-3">
      <div class="w-9 h-9 rounded-xl bg-gradient-to-br from-violet-600 to-fuchsia-600 flex items-center justify-center font-bold">◎</div>
      <div>
        <h1 class="font-bold leading-none">MEME SCREENER <span class="text-violet-400">SOLANA</span></h1>
        <p class="text-xs text-white/50">Free Stack • DexScreener + RugCheck + CoinGecko + Social Velocity</p>
      </div>
    </div>
    <div class="flex items-center gap-2 text-xs">
      <span class="px-2 py-1 rounded bg-emerald-500/20 text-emerald-400 border border-emerald-500/30">BTC <span id="btcBadge">--</span></span>
      <span class="px-2 py-1 rounded bg-violet-500/20 text-violet-300 border border-violet-500/30">SOL <span id="solBadge">--</span></span>
      <span id="timeBadge" class="text-white/40 mono"></span>
    </div>
  </div>
</div>

<div class="max-w-[1400px] mx-auto px-4 pt-4">
  <div class="flex gap-2 overflow-x-auto">
    <button onclick="showTab('screener')" id="tab-btn-screener" class="tab-btn active px-4 py-2 rounded-xl bg-violet-600 font-semibold text-sm whitespace-nowrap">🔍 Screener</button>
    <button onclick="showTab('bagger')" id="tab-btn-bagger" class="tab-btn px-4 py-2 rounded-xl bg-white/5 border border-white/10 text-sm whitespace-nowrap">🚀 Bagger Hunter + Bot (All Chain)</button>
  </div>
</div>
<div class="max-w-[1400px] mx-auto px-4 py-6 space-y-4">
  <!-- SCREENER TAB -->
  <div id="tab-screener">
  <!-- Input -->
  <div class="glass rounded-2xl p-4">
    <div class="flex flex-wrap gap-3 items-end">
      <div class="flex-1 min-w-[280px]">
        <label class="text-xs text-white/60">Solana Mint (CA)</label>
        <input id="mintInput" value="EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm" class="w-full mt-1 bg-white/5 border border-white/10 rounded-xl px-4 py-3 mono text-sm focus:outline-none focus:border-violet-500" placeholder="Paste mint address..." />
      </div>
      <button onclick="doScreen()" id="btnScreen" class="bg-violet-600 hover:bg-violet-500 px-6 py-3 rounded-xl font-semibold flex items-center gap-2">🔍 Screening</button>
      <button onclick="doSnapshot()" class="bg-white/5 hover:bg-white/10 border border-white/10 px-4 py-3 rounded-xl text-sm">💾 Snapshot Whale</button>
    </div>
    <div class="flex flex-wrap gap-2 mt-3">
      <span class="text-xs text-white/40 py-2">Preset:</span>
      <button onclick="setMint('EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm')" class="preset px-3 py-1.5 rounded-full bg-white/5 hover:bg-violet-600 border border-white/10 text-xs">WIF</button>
      <button onclick="setMint('DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263')" class="preset px-3 py-1.5 rounded-full bg-white/5 hover:bg-violet-600 border border-white/10 text-xs">BONK</button>
      <button onclick="setMint('4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R')" class="preset px-3 py-1.5 rounded-full bg-white/5 hover:bg-violet-600 border border-white/10 text-xs">RAY</button>
      <button onclick="setMint('EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v')" class="preset px-3 py-1.5 rounded-full bg-white/5 hover:bg-violet-600 border border-white/10 text-xs">USDC (test)</button>
      <label class="ml-4 flex items-center gap-2 text-xs cursor-pointer" title="Price update 10s (DexScreener), Holder/BTC 60s/300s biar gak kena limit"><input type="checkbox" id="autoRefresh" class="accent-violet-600"> Auto live (price 10s)</label>
      <span id="status" class="text-xs text-white/50 ml-auto py-1"></span>
    </div>
  </div>

  <!-- Loading -->
  <div id="loading" class="hidden glass rounded-2xl p-8 text-center">
    <div class="inline-block w-6 h-6 border-2 border-violet-500 border-t-transparent rounded-full animate-spin"></div>
    <p class="text-sm text-white/60 mt-2">Fetching DexScreener + RugCheck + CoinGecko + Social...</p>
  </div>

  <!-- Main Grid -->
  <div id="main" class="hidden space-y-4">
    <!-- Row 1: Score + Price + Attribution -->
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-4">
      <!-- Score -->
      <div class="lg:col-span-3 glass rounded-2xl p-5">
        <h3 class="text-xs tracking-widest text-white/40 mb-3">DURABILITY SCORE</h3>
        <div class="flex items-center gap-4">
          <div class="relative w-28 h-28">
            <svg class="w-28 h-28 score-ring"><circle cx="56" cy="56" r="50" stroke="rgba(255,255,255,0.08)" stroke-width="10" fill="none"/><circle id="scoreCircle" cx="56" cy="56" r="50" stroke="#8b5cf6" stroke-width="10" fill="none" stroke-linecap="round" stroke-dasharray="314" stroke-dashoffset="314" style="transition: stroke-dashoffset 1s ease"/></svg>
            <div class="absolute inset-0 flex flex-col items-center justify-center">
              <span id="scoreNum" class="text-3xl font-bold mono">--</span>
              <span id="scoreLevel" class="text-[10px] tracking-widest px-2 py-0.5 rounded-full bg-white/10">--</span>
            </div>
          </div>
          <div class="flex-1">
            <div id="scoreFlags" class="flex flex-wrap gap-1"></div>
            <p id="scoreDesc" class="text-xs text-white/50 mt-2 leading-relaxed"></p>
          </div>
        </div>
        <div id="scoreReasons" class="mt-4 space-y-1 text-xs max-h-[180px] overflow-auto pr-1"></div>
      </div>

      <!-- Price & Market -->
      <div class="lg:col-span-5 glass rounded-2xl p-5">
        <div class="flex items-start justify-between">
          <div>
            <h3 class="text-xs tracking-widest text-white/40">PRICE & MARKET</h3>
            <p id="tokenName" class="font-bold text-lg mt-1">-- <span id="tokenSymbol" class="text-white/50 text-sm"></span></p>
            <p id="mintShort" class="mono text-[11px] text-white/30"></p>
          </div>
          <a id="dexLink" target="_blank" class="text-xs bg-violet-600 hover:bg-violet-500 px-3 py-1.5 rounded-full">DexScreener ↗</a>
        </div>
        <div class="grid grid-cols-3 gap-3 mt-4">
          <div class="bg-white/5 rounded-xl p-3">
            <p class="text-[10px] tracking-widest text-white/40">PRICE</p>
            <p id="priceUsd" class="mono font-bold mt-1">--</p>
            <p id="priceChangeBadge" class="text-xs mt-1"></p>
          </div>
          <div class="bg-white/5 rounded-xl p-3">
            <p class="text-[10px] tracking-widest text-white/40">MCAP</p>
            <p id="mcap" class="mono font-bold mt-1">--</p>
            <p id="fdv" class="text-[11px] text-white/40"></p>
          </div>
          <div class="bg-white/5 rounded-xl p-3">
            <p class="text-[10px] tracking-widest text-white/40">LIQ / VOL 24H</p>
            <p id="liq" class="mono font-bold mt-1">--</p>
            <p id="vol" class="text-xs text-white/60"></p>
          </div>
        </div>
        <div class="mt-4">
          <canvas id="priceChart" height="80"></canvas>
        </div>
        <div class="flex gap-2 mt-3 text-[11px]">
          <span id="dexBadge" class="px-2 py-1 rounded bg-white/5">--</span>
          <span id="pairBadge" class="px-2 py-1 rounded bg-white/5 mono">--</span>
          <span id="pairsCount" class="px-2 py-1 rounded bg-white/5">-- pairs</span>
        </div>
      </div>

      <!-- Attribution -->
      <div class="lg:col-span-4 glass rounded-2xl p-5">
        <h3 class="text-xs tracking-widest text-white/40">ATTRIBUTION ENGINE</h3>
        <p class="text-[11px] text-white/40">Kenapa naik/turun?</p>
        <div id="primaryDriver" class="mt-3 inline-flex px-3 py-1.5 rounded-full bg-violet-600 font-bold text-sm">--</div>
        <div id="attrReasons" class="mt-3 space-y-2 text-xs leading-relaxed max-h-[220px] overflow-auto pr-1"></div>
        <div class="mt-4 grid grid-cols-2 gap-2 text-[11px]">
          <div class="bg-white/5 rounded-lg p-2"><span class="text-white/40">BTC</span> <span id="btcChange" class="mono float-right">--</span></div>
          <div class="bg-white/5 rounded-lg p-2"><span class="text-white/40">SOL</span> <span id="solChange" class="mono float-right">--</span></div>
        </div>
      </div>
    </div>

    <!-- Row 2: Holder + Social -->
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-4">
      <!-- Holder -->
      <div class="lg:col-span-5 glass rounded-2xl p-5">
        <div class="flex items-center justify-between"><h3 class="text-xs tracking-widest text-white/40">HOLDER & WHALE</h3><span id="holderSource" class="text-[10px] px-2 py-1 rounded-full bg-white/5 border border-white/10">--</span></div>
        <div class="grid grid-cols-3 gap-3 mt-3">
          <div class="text-center bg-white/5 rounded-xl p-3">
            <p class="text-[10px] text-white/40">HOLDERS</p>
            <p id="holders" class="mono font-bold text-lg">--</p>
          </div>
          <div class="text-center bg-white/5 rounded-xl p-3">
            <p class="text-[10px] text-white/40">TOP 5</p>
            <p id="top5" class="mono font-bold text-lg">--</p>
          </div>
          <div class="text-center bg-white/5 rounded-xl p-3">
            <p class="text-[10px] text-white/40">TOP 10</p>
            <p id="top10" class="mono font-bold text-lg">--</p>
          </div>
        </div>
        <div class="mt-3 space-y-2">
          <div class="flex justify-between text-[11px]"><span class="text-white/50">Top10 concentration</span><span id="top10BarText" class="mono">--</span></div>
          <div class="h-2 bg-white/10 rounded-full overflow-hidden"><div id="top10Bar" class="h-full bg-gradient-to-r from-emerald-500 to-amber-500" style="width:0%"></div></div>
          <p class="text-[11px] text-white/40">Threshold: Top5 >20% atau Top10 >30% = 🔴 Whale risk (1 whale bisa crash 50-90%)</p>
        </div>
        <div id="topHoldersList" class="mt-3 space-y-1 max-h-[160px] overflow-auto pr-1"></div>
        <div id="risksList" class="mt-3 flex flex-wrap gap-1"></div>
        <div class="mt-3 text-[11px] space-y-1">
          <p><span class="text-white/40">Mint Authority:</span> <span id="mintAuth" class="mono">--</span></p>
          <p><span class="text-white/40">Freeze Authority:</span> <span id="freezeAuth" class="mono">--</span></p>
          <p><span class="text-white/40">Insider graph:</span> <span id="insider" class="mono">--</span></p>
        </div>
      </div>

      <!-- Social Velocity -->
      <div class="lg:col-span-7 glass rounded-2xl p-5">
        <div class="flex items-center justify-between">
          <div>
            <h3 class="text-xs tracking-widest text-white/40">SOCIAL VELOCITY</h3>
            <p class="text-[11px] text-white/40">Tx proxy + CoinGecko community + LunarCrush (jika ada key)</p>
          </div>
          <div id="socialScoreBadge" class="px-4 py-2 rounded-full font-bold text-sm bg-white/10">--</div>
        </div>
        <div class="grid grid-cols-3 gap-3 mt-4">
          <div class="bg-white/5 rounded-xl p-3 text-center">
            <p class="text-[10px] tracking-widest text-white/40">SOCIAL SCORE</p>
            <p id="socialScore" class="mono font-bold text-xl mt-1">--</p>
            <p id="socialInterp" class="text-[11px] px-2 py-1 rounded-full bg-white/10 inline-block mt-1">--</p>
          </div>
          <div class="bg-white/5 rounded-xl p-3 text-center">
            <p class="text-[10px] tracking-widest text-white/40">BUY RATIO 24H</p>
            <p id="buyRatio" class="mono font-bold text-xl mt-1">--</p>
            <p id="buyRatioDesc" class="text-[11px] text-white/50"></p>
          </div>
          <div class="bg-white/5 rounded-xl p-3 text-center">
            <p class="text-[10px] tracking-widest text-white/40">TX 24H</p>
            <p id="txTotal" class="mono font-bold text-xl mt-1">--</p>
            <p id="txSplit" class="text-[11px] text-white/50"></p>
          </div>
        </div>
        <div class="grid grid-cols-2 gap-3 mt-3 text-xs">
          <div class="bg-white/5 rounded-xl p-3">
            <p class="text-[10px] tracking-widest text-white/40">VOLUME VELOCITY</p>
            <div id="volVelocity" class="mono mt-1 space-y-1"></div>
          </div>
          <div class="bg-white/5 rounded-xl p-3">
            <p class="text-[10px] tracking-widest text-white/40">COMMUNITY</p>
            <div id="communityBox" class="mt-1 space-y-1"></div>
          </div>
        </div>
        <div id="lunarBox" class="mt-3 bg-gradient-to-br from-violet-600/20 to-fuchsia-600/20 border border-violet-500/20 rounded-xl p-3 hidden">
          <p class="text-[10px] tracking-widest text-violet-300">LUNARCRUSH (REAL SOCIAL)</p>
          <div id="lunarContent" class="text-xs mt-1"></div>
        </div>
        <div id="socialDetails" class="mt-3 space-y-1 text-xs max-h-[120px] overflow-auto pr-1"></div>
        <canvas id="socialChart" height="70" class="mt-3"></canvas>
      </div>
    </div>

    <!-- Snapshot -->
    <div class="glass rounded-2xl p-5">
      <h3 class="text-xs tracking-widest text-white/40">WHALE CABUT DETECTOR (SNAPSHOT)</h3>
      <p class="text-xs text-white/40">Bandingkan holding sekarang vs snapshot sebelumnya. Simpan snapshot tiap hari untuk deteksi distribusi.</p>
      <div id="snapshotBox" class="mt-3 text-xs bg-white/5 rounded-xl p-3">Belum ada snapshot. Klik "Snapshot Whale" untuk simpan baseline.</div>
    </div>
  </div>

  </div> <!-- end screener -->
  <!-- BAGGER TAB (with Based Bot) -->
  <div id="tab-bagger" class="hidden space-y-4">
    <div class="glass rounded-2xl p-5">
      <div class="flex items-center justify-between">
        <div><h3 class="font-bold">🚀 Bagger Hunter + Based Bot (All Chain)</h3><p class="text-xs text-white/50">Scan all-chain micin bagger + auto paper BUY 2%. Jangan cuma trending - new micin juga.</p></div>
        <button onclick="scanBagger()" id="btnBagger" class="bg-emerald-600 hover:bg-emerald-500 px-5 py-2.5 rounded-xl font-semibold text-sm">🔍 Scan Bagger</button>
      </div>
      <div class="flex flex-wrap gap-4 mt-3 text-xs">
        <label class="flex items-center gap-1.5 cursor-pointer"><input type="checkbox" id="baggerRelaxed" class="accent-emerald-600"> Mode Relaxed (mcap 100M, dur 45)</label>
        <label class="flex items-center gap-1.5 cursor-pointer"><input type="checkbox" id="baggerFiltered" class="accent-violet-600" checked> Lihat ke-filter + alasan</label>
        <label class="flex items-center gap-1.5 cursor-pointer"><input type="checkbox" id="baggerBeyond" class="accent-amber-600"> Beyond trending (new Pump.fun)</label>
      </div>
      <div id="baggerStatus" class="text-xs text-white/50 mt-3"></div>
      <div id="baggerList" class="mt-4 grid gap-3"></div>
      <div id="baggerFilteredList" class="mt-6 space-y-3 hidden">
        <h4 class="text-xs font-bold tracking-widest text-white/40">YANG KE-FILTER (kenapa gak lolos)</h4>
        <div id="baggerFilteredGrid" class="grid gap-2"></div>
      </div>
    </div>
    <div class="glass rounded-2xl p-5">
      <div class="flex items-center justify-between">
        <div><h3 class="font-bold">🤖 Based Bot - Paper</h3><p class="text-xs text-white/50">Terhubung ke Bagger - klik Paper BUY di bagger buat entry. Saldo $10k paper, siap real Jupiter.</p></div>
        <button onclick="loadPaper()" class="bg-white/5 border border-white/10 px-4 py-2 rounded-xl text-sm">Refresh</button>
      </div>
      <div id="paperStats" class="grid grid-cols-3 gap-3 mt-4"></div>
      <div id="paperPositions" class="mt-4 space-y-2"></div>
      <div id="paperTrades" class="mt-4 max-h-[300px] overflow-auto space-y-1 text-xs"></div>
    </div>
  </div>
  <p class="text-center text-[11px] text-white/20 py-4">Bukan financial advice • Data: DexScreener + RugCheck + CoinGecko • 95% meme coin mati &lt;90 hari • Selalu cek holder, liquidity lock, whale concentration</p>
</div>

<script>
let priceChart, socialChart;
let currentMint = "";
function parseWIB(iso){
  if(!iso) return new Date(NaN);
  // potong microsecond ke 3 digit biar valid di semua browser
  iso = iso.replace(/\.(\d{3})\d*/, '.$1');
  // kalau sudah ada timezone (+00:00 atau Z) jangan tambah Z lagi
  if(/Z$/.test(iso) || /[+-]\d{2}:\d{2}$/.test(iso)) return new Date(iso);
  return new Date(iso + 'Z');
}
function formatWIB(iso){
  try{
    const d = parseWIB(iso);
    if(isNaN(d)) return iso;
    return d.toLocaleString('id-ID', {timeZone:'Asia/Jakarta', year:'numeric', month:'short', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false}) + ' WIB';
  }catch{ return iso; }
}
function timeAgo(iso){
  try{
    const d = parseWIB(iso);
    if(isNaN(d)) return '';
    const diff = Date.now() - d.getTime();
    const mins = Math.floor(diff/60000);
    if(mins<1) return 'baru saja';
    if(mins<60) return mins+' menit lalu';
    const hrs = Math.floor(mins/60);
    if(hrs<24) return hrs+' jam lalu';
    const days = Math.floor(hrs/24);
    return days+' hari lalu';
  }catch{ return ''; }
}

function showTab(name){
  document.querySelectorAll('div[id^="tab-"]').forEach(el=>el.classList.add('hidden'));
  document.getElementById('tab-'+name).classList.remove('hidden');
  document.querySelectorAll('.tab-btn').forEach(b=>{b.classList.remove('bg-violet-600'); b.classList.add('bg-white/5','border','border-white/10')});
  document.getElementById('tab-btn-'+name).classList.add('bg-violet-600'); document.getElementById('tab-btn-'+name).classList.remove('bg-white/5','border','border-white/10');
  if(name==='bagger'){ if(!document.getElementById('baggerList').innerHTML) scanBagger(); loadPaper(); startPaperAutoRefresh(); }
  else{ stopPaperAutoRefresh(); }
}
async function scanBagger(){
  const btn=document.getElementById('btnBagger'); const status=document.getElementById('baggerStatus'); const list=document.getElementById('baggerList');
  const relaxed=document.getElementById('baggerRelaxed')?.checked; const showFiltered=document.getElementById('baggerFiltered')?.checked; const beyond=document.getElementById('baggerBeyond')?.checked;
  btn.disabled=true; btn.textContent='Scanning...'; status.textContent=(beyond?'Scan trending + new micin':'Scan trending') + ', cek durability+social tiap token ~0.3s...';
  list.innerHTML='<div class="text-center py-8 text-white/50">Scanning micin bagger...</div>';
  document.getElementById('baggerFilteredList').classList.add('hidden');
  try{
    const params=new URLSearchParams({relaxed: relaxed, show_filtered: showFiltered, beyond: beyond, limit: 20});
    const r=await fetch('/api/bagger?'+params); const j=await r.json();
    if(j.error) throw new Error(j.error);
    status.textContent=`Scanned ${j.scanned} trending${j.beyond ? ' + new' : ''}, found ${j.baggers.length} bagger candidate${j.relaxed ? ' (relaxed)' : ''}`;
    // show filtered if enabled
    if(j.filtered && j.filtered.length && document.getElementById('baggerFiltered')?.checked){
      document.getElementById('baggerFilteredList').classList.remove('hidden');
      document.getElementById('baggerFilteredGrid').innerHTML = j.filtered.slice(0,10).map(f=>`<div class="bg-white/5 border border-white/5 rounded-xl p-3 opacity-60"><p class="mono text-xs font-bold">${f.symbol||f.mint.slice(0,6)} <span class="text-white/40">${f.chain||'solana'}</span> - mcap $${(f.mcap||0).toLocaleString()} | score ${f.score} | social ${f.social}</p><p class="text-[11px] text-amber-300/80 mt-1">${f.reason}</p></div>`).join('');
    }
    if(!j.baggers.length){ list.innerHTML='<div class="text-center py-8 text-white/30">Gak ada bagger hari ini - coba Mode Relaxed atau Beyond trending</div>'; return; }
    list.innerHTML=j.baggers.map(b=>`<div class="bg-white/5 border border-white/10 rounded-xl p-4 flex flex-wrap gap-3 items-center justify-between">
      <div><p class="font-bold mono">${b.symbol || b.mint.slice(0,6)} <span class="text-white/50 text-xs">${b.mint.slice(0,6)}...${b.mint.slice(-4)}</span></p><p class="text-xs mono">mcap $${(b.mcap||0).toLocaleString()} | holders ${b.holders?.toLocaleString()||'-'} | top10 ${b.top10?.toFixed(1)}% | score ${b.score} | social ${b.social}</p><p class="text-[11px] text-white/40 mt-1">${b.reason}</p></div>
      <div class="flex gap-2"><a href="${b.pairUrl}" target="_blank" class="px-3 py-2 rounded-full bg-white/10 text-xs">Dex ↗</a><button onclick="document.getElementById('mintInput').value='${b.mint}'; showTab('screener'); doScreen();" class="px-3 py-2 rounded-full bg-violet-600 text-xs font-bold">Screen</button><button onclick="paperBuyFor('${b.mint}','${b.symbol||''}',${b.price||0})" class="px-3 py-2 rounded-full bg-emerald-600 text-xs font-bold">Paper BUY</button></div>
    </div>`).join('');
  }catch(e){ status.textContent='Error: '+e.message; }
  finally{ btn.disabled=false; btn.textContent='🔍 Scan Bagger'; }
}
async function trackWhale(){
  const mint=document.getElementById('whaleMint').value.trim(); if(!mint) return;
  const box=document.getElementById('whaleBox'); box.innerHTML='Loading whale...';
  try{
    const r=await fetch('/api/whale/'+mint); const j=await r.json();
    if(j.error) throw new Error(j.error);
    box.innerHTML=`<div class="bg-white/5 rounded-xl p-3"><p class="text-xs">Holders ${j.total_holders?.toLocaleString()} | Top10 ${j.top10?.toFixed(1)}% | Source ${j.holder_source}</p><p class="text-xs mt-1">Flow: <span class="font-bold">${j.flow.signal}</span> - ${j.flow.details}</p><div class="mt-3 space-y-1">${j.whales.map(w=>`<div class="flex justify-between bg-white/5 rounded-lg px-3 py-2 mono text-xs"><span>${w.address.slice(0,6)}...${w.address.slice(-4)} ${w.is_robinhood?'[RH]':''}</span><span>${w.pct.toFixed(2)}%</span></div>`).join('') || '<span class="text-white/30">No whale >2%</span>'}</div></div>`;
    document.getElementById('robinhoodBox').textContent = JSON.stringify(j.robinhood_wallets, null, 2).slice(0,400);
  }catch(e){ box.innerHTML='Error: '+e.message; }
}
async function loadPaper(){
  try{
    const r=await fetch('/api/paper/portfolio'); const j=await r.json();
    // fetch live prices
    let livePrices={};
    try{ const pr=await fetch('/api/paper/prices'); const pj=await pr.json(); livePrices=pj.prices||{}; }catch(e){}
    let totalU=0;
    document.getElementById('paperStats').innerHTML=`<div class="bg-white/5 rounded-xl p-3 text-center"><p class="text-[10px] text-white/40">BALANCE</p><p class="mono font-bold">$${j.balance_usd.toFixed(2)}</p></div><div class="bg-white/5 rounded-xl p-3 text-center"><p class="text-[10px] text-white/40">REALIZED PNL</p><p class="mono font-bold ${j.total_pnl>=0?'text-emerald-400':'text-red-400'}">$${j.total_pnl.toFixed(2)}</p></div><div class="bg-white/5 rounded-xl p-3 text-center"><p class="text-[10px] text-white/40">UNREALIZED PNL</p><p class="mono font-bold" id="paperU">...</p></div><div class="bg-white/5 rounded-xl p-3 text-center"><p class="text-[10px] text-white/40">WIN/LOSS</p><p class="mono font-bold">${j.win_trades}/${j.loss_trades}</p></div>`;
    const posEl=document.getElementById('paperPositions');
    const entries=Object.entries(j.positions);
    if(!entries.length){ posEl.innerHTML='<p class="text-xs text-white/30">No positions - scan bagger & paper BUY</p>'; }
    else{ posEl.innerHTML=entries.map(([mint,pos])=>{
      const cur=livePrices[mint]||pos.entry_price;
      const uPnl=(cur-pos.entry_price)*pos.amount;
      totalU+=uPnl;
      const roi=pos.entry_price?((cur-pos.entry_price)/pos.entry_price*100):0;
      const roiC=roi>=0?'text-emerald-400':'text-red-400';
      return `<div class="bg-white/5 rounded-xl p-3 flex justify-between items-center"><div><p class="mono font-bold text-xs">${pos.symbol} ${mint.slice(0,6)}... <span class="${roiC} text-[11px]">${roi>0?'+':''}${roi.toFixed(1)}%</span></p><p class="text-[11px] mono">${pos.amount.toFixed(2)} @ $${pos.entry_price.toFixed(6)} <span class="text-white/40">now $${cur.toFixed(6)}</span></p><p class="text-[10px] ${uPnl>=0?'text-emerald-400':'text-red-400'}">PnL $${uPnl.toFixed(2)}</p></div><button onclick="paperSellFor('${mint}')" class="px-3 py-1 rounded-full bg-red-600 text-xs">SELL</button></div>`}).join('');}
    const uEl=document.getElementById('paperU');
    if(uEl){ const uc=totalU>=0?'text-emerald-400':'text-red-400'; uEl.className='mono font-bold '+uc; uEl.textContent='$'+totalU.toFixed(2); }
    document.getElementById('paperTrades').innerHTML = j.trades.slice(-20).reverse().map(t=>`<div class="flex justify-between bg-white/5 rounded-lg px-3 py-1.5"><span class="${t.type==='BUY'?'text-emerald-400':'text-red-400'}">${t.type} ${t.symbol}</span><span class="mono">$${t.price?.toFixed(6)} x ${t.amount?.toFixed(2)} ${t.pnl!=null ? 'PNL $'+t.pnl.toFixed(2)+' ('+t.pnl_pct?.toFixed(1)+'%)':''}</span><span class="text-white/30">${new Date(t.time).toLocaleTimeString()}</span></div>`).join('');
  }catch(e){ console.error(e); }
}
let _paperTimer=null;
function startPaperAutoRefresh(){ if(_paperTimer) return; _paperTimer=setInterval(()=>{ const tab=document.getElementById('tab-bagger'); if(tab && !tab.classList.contains('hidden')) loadPaper(); },10000); }
function stopPaperAutoRefresh(){ if(_paperTimer){ clearInterval(_paperTimer); _paperTimer=null; } }
let _paperBusy=false;
async function paperBuy(){ if(_paperBusy) return; const mint=document.getElementById('paperMint').value.trim(); const price=parseFloat(document.getElementById('paperPrice').value); if(!mint||!price) return alert('mint & price'); _paperBusy=true; try{ const r=await fetch('/api/paper/buy',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mint, price, symbol:mint.slice(0,6), size_pct:2})}); const j=await r.json(); if(j.error) alert(j.error); else loadPaper(); }finally{ _paperBusy=false; } }
async function paperBuyFor(mint,symbol,price){ if(_paperBusy) return; if(!price) { const p=prompt('price?'); price=parseFloat(p); } if(!price) return; _paperBusy=true; try{ const r=await fetch('/api/paper/buy',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mint, symbol, price, size_pct:2})}); const j=await r.json(); if(j.error) alert(j.error); else { showTab('bagger'); loadPaper(); startPaperAutoRefresh(); } }finally{ _paperBusy=false; } }
async function paperSell(){ if(_paperBusy) return; const mint=document.getElementById('paperMint').value.trim(); const price=parseFloat(document.getElementById('paperPrice').value); if(!mint||!price) return; _paperBusy=true; try{ const r=await fetch('/api/paper/sell',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mint, price, pct:100})}); const j=await r.json(); if(j.error) alert(j.error); else loadPaper(); }finally{ _paperBusy=false; } }
async function paperSellFor(mint){ if(_paperBusy) return; const price=prompt('sell price?'); if(!price) return; _paperBusy=true; try{ const r=await fetch('/api/paper/sell',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({mint, price:parseFloat(price), pct:100})}); const j=await r.json(); if(j.error) alert(j.error); else loadPaper(); }finally{ _paperBusy=false; } }
function setMint(m){ document.getElementById('mintInput').value=m; doScreen(); }

async function doScreen(isAuto=false){
  const mint = document.getElementById('mintInput').value.trim();
  if(!mint) return;
  currentMint=mint;
  const statusEl = document.getElementById('status');
  const mainEl = document.getElementById('main');
  const isInitial = mainEl.classList.contains('hidden');
  // cuma tampil preloader pas initial load, auto refresh pakai ajax halus
  if(!isAuto || isInitial){
    if(isInitial) document.getElementById('loading').classList.remove('hidden');
    statusEl.textContent = isAuto ? "Auto refresh..." : "Fetching...";
  } else {
    statusEl.textContent = "Updating...";
  }
  try{
    const res = await fetch(`/api/screen/${mint}`);
    const data = await res.json();
    if(data.error){ throw new Error(data.error + " " + (data.dex_err||"") + " " + (data.rug_err||"")); }
    render(data);
    mainEl.classList.remove('hidden');
    document.getElementById('loading').classList.add('hidden');
    statusEl.textContent = "Updated " + new Date().toLocaleTimeString() + (isAuto ? " (auto)" : "");
  }catch(e){
    document.getElementById('loading').classList.add('hidden');
    statusEl.textContent="Error: "+e.message;
    if(!isAuto) alert(e.message);
  }
}

async function doSnapshot(){
  if(!currentMint){ alert("Screening dulu"); return; }
  const res = await fetch(`/api/snapshot/${currentMint}`, {method:"POST"});
  const j = await res.json();
  alert(j.old ? `Snapshot updated. Prev top10 ${j.old.top10_pct?.toFixed(1)}% -> Now ${j.new.top10_pct?.toFixed(1)}%` : "Snapshot disimpan. Run lagi besok untuk delta.");
  doScreen();
}

function render(d){
  // BTC/SOL badge
  const btc = d.btc_ctx?.btc_24h_change; const sol = d.btc_ctx?.sol_24h_change;
  document.getElementById('btcBadge').textContent = (btc>=0?"+":"")+ (btc?.toFixed(2)??"--")+"%";
  document.getElementById('solBadge').textContent = (sol>=0?"+":"")+ (sol?.toFixed(2)??"--")+"%";
  lastDataForClock = d;
  lastDataForClock._isPriceLive = false;
  document.getElementById('timeBadge').textContent = formatWIB(d.timestamp) + ' (' + timeAgo(d.timestamp) + ')';

  // Score
  const sc = d.durability.score; const flags = d.durability.flags||[];
  document.getElementById('scoreNum').textContent = sc;
  const lvl = d.durability.level;
  const lvlEl = document.getElementById('scoreLevel');
  lvlEl.textContent = lvl;
  lvlEl.className = "text-[10px] tracking-widest px-2 py-0.5 rounded-full " + (sc>=75?"bg-emerald-500 text-white": sc>=50?"bg-amber-500 text-white": sc>=30?"bg-orange-600 text-white":"bg-red-600 text-white");
  // circle
  const pct = sc/100; const offset = 314 - 314*pct;
  const circle = document.getElementById('scoreCircle');
  circle.style.strokeDashoffset = offset;
  circle.setAttribute("stroke", sc>=75?"#10b981": sc>=50?"#f59e0b": sc>=30?"#f97316":"#ef4444");
  document.getElementById('scoreFlags').innerHTML = flags.map(f=>`<span class="text-[10px] px-2 py-1 rounded-full bg-white/10 border border-white/10">${f}</span>`).join("") || '<span class="text-xs text-white/30">No flags</span>';
  document.getElementById('scoreDesc').textContent = sc>=75?"Struktur sehat - layak monitor": sc>=50?"Waspada - position kecil": sc>=30?"Berbahaya - hindari entry": "Extreme - 95% mati";
  document.getElementById('scoreReasons').innerHTML = d.durability.reasons.map(r=>`<div class="flex gap-2"><span class="text-white/30">•</span><span>${r}</span></div>`).join("");

  // Price
  document.getElementById('tokenName').childNodes[0].textContent = (d.dex.best_pair?.baseToken?.name || "--") + " ";
  document.getElementById('tokenSymbol').textContent = d.dex.best_pair?.baseToken?.symbol || "";
  document.getElementById('mintShort').textContent = d.mint.slice(0,8)+"..."+d.mint.slice(-6);
  document.getElementById('dexLink').href = d.dex.best_pair?.url || "#";
  document.getElementById('priceUsd').textContent = "$" + (d.dex.price_usd?.toFixed(6) ?? "--");
  const pc = d.attribution.priceChange?.h24 ?? 0;
  const pcEl = document.getElementById('priceChangeBadge');
  pcEl.textContent = (pc>=0?"+":"")+pc.toFixed(1)+"% 24h";
  pcEl.className = "text-xs mt-1 px-2 py-0.5 rounded-full inline-block " + (pc>=0?"bg-emerald-500/20 text-emerald-400":"bg-red-500/20 text-red-400");
  document.getElementById('mcap').textContent = "$"+(d.dex.market_cap?.toLocaleString() ?? "--");
  document.getElementById('fdv').textContent = "FDV $"+(d.dex.fdv?.toLocaleString() ?? "--");
  document.getElementById('liq').textContent = "$"+(d.dex.total_liquidity_usd?.toLocaleString(undefined,{maximumFractionDigits:0}) ?? "--");
  document.getElementById('vol').textContent = "Vol 24h $"+(d.dex.total_vol_24h?.toLocaleString(undefined,{maximumFractionDigits:0}) ?? "--");
  document.getElementById('dexBadge').textContent = d.dex.dex || "--";
  document.getElementById('pairBadge').textContent = (d.dex.best_pair?.quoteToken?.symbol || "") + " pair";
  document.getElementById('pairsCount').textContent = d.dex.all_pairs_count + " pairs";

  // chart price
  const ctx = document.getElementById('priceChart').getContext('2d');
  if(priceChart) priceChart.destroy();
  const pc5=d.attribution.priceChange?.m5 ?? 0, pch1=d.attribution.priceChange?.h1 ?? 0, pch6=d.attribution.priceChange?.h6 ?? 0;
  priceChart = new Chart(ctx, {type:'bar', data:{labels:['m5','h1','h6','h24'], datasets:[{label:'% change', data:[pc5,pch1,pch6,pc], backgroundColor: [pc5>=0?'#10b981':'#ef4444', pch1>=0?'#10b981':'#ef4444', pch6>=0?'#10b981':'#ef4444', pc>=0?'#8b5cf6':'#ef4444']}]}, options:{plugins:{legend:{display:false}}, scales:{y:{grid:{color:'rgba(255,255,255,0.05)'}, ticks:{color:'rgba(255,255,255,0.5)', callback:v=>v+'%'}}, x:{grid:{display:false}, ticks:{color:'rgba(255,255,255,0.5)'}}}}});

  // Attribution
  const primary = d.attribution.primary;
  const primaryEl = document.getElementById('primaryDriver');
  primaryEl.textContent = primary;
  const colorMap = {"BTC_BETA_AMPLIFIED":"bg-violet-600","BTC_CORRELATED":"bg-blue-600","SOL_CORRELATED":"bg-emerald-600","SENTIMENT_FOMO":"bg-fuchsia-600","SELL_PRESSURE":"bg-orange-600","LOW_LIQUIDITY_AMPLIFICATION":"bg-amber-600","SUSPECTED_MANIPULATION":"bg-red-600","SIDEWAYS_NO_CATALYST":"bg-white/10"};
  primaryEl.className = "mt-3 inline-flex px-3 py-1.5 rounded-full font-bold text-sm " + (colorMap[primary]||"bg-white/10");
  document.getElementById('attrReasons').innerHTML = d.attribution.reasons.map(r=>`<div class="bg-white/5 rounded-xl p-2.5">${r}</div>`).join("");
  document.getElementById('btcChange').textContent = (btc>=0?"+":"")+btc?.toFixed(2)+"%";
  document.getElementById('solChange').textContent = (sol>=0?"+":"")+sol?.toFixed(2)+"%";
  document.getElementById('btcChange').className = "mono float-right " + (btc>=0?"text-emerald-400":"text-red-400");
  document.getElementById('solChange').className = "mono float-right " + (sol>=0?"text-emerald-400":"text-red-400");

  // Holder
  document.getElementById('holders').textContent = d.rug.total_holders?.toLocaleString() ?? "--";
  // holder source badge
  const src = d.rug.holder_source || "rugcheck";
  const srcEl = document.getElementById('holderSource');
  srcEl.textContent = src;
  srcEl.className = "text-[10px] px-2 py-1 rounded-full border " + (src==="goplus"?"bg-emerald-500/20 text-emerald-300 border-emerald-500/30": src==="birdeye"?"bg-blue-500/20 text-blue-300 border-blue-500/30": src==="rugcheck"?"bg-violet-500/20 text-violet-300 border-violet-500/30":"bg-white/5 border-white/10");
  if(d.rug.holder_unavailable){
    document.getElementById('top5').textContent = "N/A";
    document.getElementById('top10').textContent = "N/A";
    document.getElementById('top10Bar').style.width = "0%";
    document.getElementById('top10BarText').textContent = "RugCheck limit";
    document.getElementById('topHoldersList').innerHTML = `<div class="bg-amber-500/10 border border-amber-500/30 rounded-xl p-3 text-amber-300">Holder detail tidak tersedia dari RugCheck (limit API untuk token besar). Total holders ${d.rug.total_holders?.toLocaleString()} tetap valid. Cek manual Top Holders di <a href="https://solscan.io/token/${d.mint}" target="_blank" class="underline">SolScan</a> atau <a href="https://rugcheck.xyz/tokens/${d.mint}" target="_blank" class="underline">RugCheck</a>. Score ${d.rug.score_normalised} digunakan sebagai proxy.</div>`;
  } else {
    document.getElementById('top5').textContent = d.rug.top5_pct?.toFixed(1)+"%" ?? "--";
    document.getElementById('top10').textContent = d.rug.top10_pct?.toFixed(1)+"%" ?? "--";
    const t10 = d.rug.top10_pct ?? 0;
    document.getElementById('top10Bar').style.width = Math.min(100,t10)+"%";
    document.getElementById('top10Bar').className = "h-full " + (t10>30?"bg-red-500": t10>20?"bg-amber-500":"bg-emerald-500");
    document.getElementById('top10BarText').textContent = t10.toFixed(1)+"%";
    document.getElementById('topHoldersList').innerHTML = d.rug.top_holders.map((h,i)=>`<div class="flex justify-between bg-white/5 rounded-lg px-3 py-1.5"><span class="mono text-[11px]">#${i+1} ${h.address.slice(0,6)}...${h.address.slice(-4)}</span><span class="mono text-xs ${h.pct>10?'text-red-400':h.pct>5?'text-amber-400':''}">${h.pct.toFixed(2)}%</span></div>`).join("");
  }
  const risks = d.rug.risks||[];
  document.getElementById('risksList').innerHTML = risks.length? risks.map(r=>`<span class="text-[10px] px-2 py-1 rounded-full bg-red-500/20 text-red-300 border border-red-500/30">${r.name}</span>`).join("") : '<span class="text-xs text-emerald-400">No critical risks ✓</span>';
  document.getElementById('mintAuth').textContent = d.rug.mintAuthority ? "AKTIF (bahaya)" : "None ✓";
  document.getElementById('mintAuth').className = "mono " + (d.rug.mintAuthority?"text-red-400":"text-emerald-400");
  document.getElementById('freezeAuth').textContent = d.rug.freezeAuthority ? "AKTIF" : "None ✓";
  document.getElementById('freezeAuth').className = "mono " + (d.rug.freezeAuthority?"text-red-400":"text-emerald-400");
  document.getElementById('insider').textContent = d.rug.insider_detected ?? "--";
  document.getElementById('insider').className = "mono " + ((d.rug.insider_detected||0)>100?"text-amber-400":"");

  // Social
  const s = d.social;
  document.getElementById('socialScore').textContent = s.score;
  document.getElementById('socialScoreBadge').textContent = s.interpretation;
  document.getElementById('socialScoreBadge').className = "px-4 py-2 rounded-full font-bold text-sm " + (s.interpretation.includes("VIRAL")?"bg-fuchsia-600": s.interpretation.includes("ACCELERATING")?"bg-emerald-600": s.interpretation.includes("FADING")?"bg-red-600":"bg-white/10");
  document.getElementById('socialInterp').textContent = s.interpretation;
  const buyRatio = s.tx_velocity?.buy_ratio_24h ?? 50;
  document.getElementById('buyRatio').textContent = buyRatio.toFixed(0)+"%";
  document.getElementById('buyRatio').className = "mono font-bold text-xl mt-1 " + (buyRatio>65?"text-emerald-400": buyRatio<35?"text-red-400":"");
  document.getElementById('buyRatioDesc').textContent = buyRatio>65?"FOMO buys": buyRatio<35?"Sell pressure":"Balance";
  document.getElementById('txTotal').textContent = s.tx_velocity?.total_tx_24h?.toLocaleString() ?? "--";
  document.getElementById('txSplit').textContent = `${s.tx_velocity?.buys_24h ?? 0} buys / ${s.tx_velocity?.sells_24h ?? 0} sells`;
  document.getElementById('volVelocity').innerHTML = `Vol 24h $${(s.tx_velocity?.vol_24h??0).toLocaleString()}<br>h1 $${(s.tx_velocity?.vol_h1??0).toLocaleString()} | h6 $${(s.tx_velocity?.vol_h6??0).toLocaleString()}<br>tx h1: ${s.tx_velocity?.tx_h1?.buys??0}B/${s.tx_velocity?.tx_h1?.sells??0}S`;
  const comm = s.community||{};
  document.getElementById('communityBox').innerHTML = `Twitter: @${comm.twitter||"--"}<br>Telegram: ${comm.telegram??"--"} members<br>Handle: ${comm.telegram_handle||"--"}`;
  if(s.lunarcrush && !s.lunarcrush.error){
    document.getElementById('lunarBox').classList.remove('hidden');
    document.getElementById('lunarContent').innerHTML = `Social score ${s.lunarcrush.social_score??"--"} | Galaxy ${s.lunarcrush.galaxy_score??"--"} | AltRank ${s.lunarcrush.alt_rank??"--"}<br>Social vol ${s.lunarcrush.social_volume??"--"} (24h ${s.lunarcrush.social_volume_24h_change??"--"}%)`;
  }else{
    document.getElementById('lunarBox').classList.add('hidden');
  }
  document.getElementById('socialDetails').innerHTML = s.details.map(t=>`<div class="flex gap-2"><span class="text-white/30">•</span><span>${t}</span></div>`).join("");
  // social chart: tx h1/h6/h24 buys vs sells
  const sctx = document.getElementById('socialChart').getContext('2d');
  if(socialChart) socialChart.destroy();
  socialChart = new Chart(sctx, {type:'bar', data:{labels:['h1 buys','h1 sells','h6 buys','h6 sells','24h buys','24h sells'], datasets:[{data:[s.tx_velocity?.tx_h1?.buys||0, s.tx_velocity?.tx_h1?.sells||0, s.tx_velocity?.tx_h6?.buys||0, s.tx_velocity?.tx_h6?.sells||0, s.tx_velocity?.buys_24h||0, s.tx_velocity?.sells_24h||0], backgroundColor:['#10b981','#ef4444','#10b981','#ef4444','#8b5cf6','#f97316']}]}, options:{plugins:{legend:{display:false}}, scales:{y:{grid:{color:'rgba(255,255,255,0.05)'}, ticks:{color:'rgba(255,255,255,0.5)'}}, x:{grid:{display:false}, ticks:{color:'rgba(255,255,255,0.5)', font:{size:9}}}}}});

  // snapshot
  const snap = d.snapshot;
  const snapBox = document.getElementById('snapshotBox');
  if(!snap.exists){
    snapBox.innerHTML = 'Belum ada snapshot. Klik "Snapshot Whale" untuk simpan baseline. File: snapshots/'+d.mint.slice(0,8)+'.json';
  }else{
    const prev = snap.prev;
    const prevWIB = formatWIB(prev.timestamp);
    const ago = timeAgo(prev.timestamp);
    const delta = (d.rug.top10_pct - snap.prev_top10).toFixed(2);
    const deltaColor = parseFloat(delta) < -2 ? 'text-red-400' : parseFloat(delta) > 2 ? 'text-emerald-400' : 'text-white/60';
    snapBox.innerHTML = `<div class="flex flex-wrap gap-4"><div><span class="text-white/40">Prev:</span> <span class="mono">${prevWIB}</span> <span class="text-white/30">(<span id="snapshotAgo">${ago}</span>)</span> | price <span class="mono">$${prev.price_usd?.toFixed(6)}</span> | top10 <span class="mono">${snap.prev_top10?.toFixed(1)}%</span> | holders <span class="mono">${prev.total_holders?.toLocaleString()}</span></div><div><span class="text-white/40">Saat ini:</span> top10 <span class="mono">${d.rug.top10_pct.toFixed(1)}%</span> | delta <span class="mono ${deltaColor}">${delta}ppt</span> ${ parseFloat(delta) < -2 ? '<span class="text-red-400 font-bold">WHALE CABUT!</span>' : parseFloat(delta) > 2 ? '<span class="text-emerald-400">akumulasi</span>' : ''}</div></div>`;
  }
}

// auto refresh
async function doPricePoll(){
  if(!currentMint || !document.getElementById('autoRefresh').checked) return;
  try{
    const res = await fetch(`/api/price/${currentMint}`);
    const d = await res.json();
    if(d.error) return;
    // update price elements live
    document.getElementById('priceUsd').textContent = "$" + (d.price_usd?.toFixed(6) ?? "--");
    const pc = d.priceChange?.h24 ?? 0;
    const pcEl = document.getElementById('priceChangeBadge');
    if(pcEl){ pcEl.textContent = (pc>=0?"+":"")+pc.toFixed(1)+"% 24h"; pcEl.className = "text-xs mt-1 px-2 py-0.5 rounded-full inline-block " + (pc>=0?"bg-emerald-500/20 text-emerald-400":"bg-red-500/20 text-red-400"); }
    document.getElementById('vol').textContent = "Vol 24h $"+(d.volume?.toLocaleString(undefined,{maximumFractionDigits:0}) ?? "--");
    // keep last full data but update timestamp for clock
    if(lastDataForClock) lastDataForClock.timestamp = d.timestamp;
    else lastDataForClock = d;
    lastDataForClock._isPriceLive = true;
    document.getElementById('timeBadge').textContent = formatWIB(d.timestamp) + ' (' + timeAgo(d.timestamp) + ' - price live 10s)';
    // update chart data if exists
    if(priceChart){
      priceChart.data.datasets[0].data = [d.priceChange?.m5 ?? 0, d.priceChange?.h1 ?? 0, d.priceChange?.h6 ?? 0, d.priceChange?.h24 ?? 0];
      priceChart.update('none');
    }
  }catch(e){ /* silent */ }
}
// Staggered: price 10s (real-time tanpa kena limit holder/BTC), full screen 60s
setInterval(doPricePoll, 10000);
setInterval(()=>{ if(document.getElementById('autoRefresh').checked && currentMint) doScreen(true); }, 60000);

let lastDataForClock = null;
function updateClocks(){
  if(!lastDataForClock) return;
  // update header timeBadge
  const tb = document.getElementById('timeBadge');
  if(tb && lastDataForClock.timestamp){
    tb.textContent = formatWIB(lastDataForClock.timestamp) + ' (' + timeAgo(lastDataForClock.timestamp) + (lastDataForClock._isPriceLive ? ' - price live 10s' : '') + ')';
  }
  // update snapshot ago
  const snap = lastDataForClock.snapshot;
  if(snap && snap.exists && snap.prev){
    const agoEl = document.getElementById('snapshotAgo');
    if(agoEl){
      agoEl.textContent = timeAgo(snap.prev.timestamp);
    }
  }
}
setInterval(updateClocks, 5000);

// initial
doScreen(false);
</script>
</body>
</html>
"""

if __name__ == "__main__":
    print("="*60)
    print("MEME SCREENER DASHBOARD - Solana")
    print("="*60)
    print(f"WIF: {WIF_MINT}")
    print(f"BONK: {BONK_MINT}")
    print(f"LunarCrush key: {'SET' if LUNAR_KEY else 'NOT SET (pakai Tx proxy + CoinGecko)'}")
    print("Untuk social velocity real, set env: LUNARCRUSH_API_KEY=xxx")
    print("Dashboard: http://localhost:5001")
    print("API: http://localhost:5001/api/screen/<mint>")
    print("="*60)
    port = int(os.getenv("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True, use_reloader=False)
