#!/usr/bin/env python3
"""
Meme Coin Screener & Attribution Engine - Solana (Free Stack)
Stack: DexScreener (free) + RugCheck (free) + CoinGecko (free) + Solana Public RPC
Usage: py meme_screener.py --mint <SOLANA_MINT> [--explain] [--snapshot]
Contoh WIF: EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm
         BONK: DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

# Konstanta
WIF_MINT = "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm"
BONK_MINT = "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263"
SOL_MINT_WRAPPED = "So11111111111111111111111111111111111111112"

SNAPSHOT_DIR = os.path.join(os.path.dirname(__file__), "snapshots")
os.makedirs(SNAPSHOT_DIR, exist_ok=True)

HEADERS = {"User-Agent": "meme-screener-solana/1.0"}


def fetch_dexscreener(mint: str):
    """Ambil data DEX lengkap dari DexScreener (gratis, no key) + retry 3x + fallback GeckoTerminal."""
    url = f"https://api.dexscreener.com/latest/dex/tokens/{mint}"
    last_err = None
    data = None
    for attempt in range(1):
        try:
            timeout = 5
            r = requests.get(url, headers=HEADERS, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            break
        except Exception as e:
            last_err = e
            # fallback GeckoTerminal setelah 3x gagal
            try:
                gecko_url = f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{mint}"
                rg = requests.get(gecko_url, headers=HEADERS, timeout=10)
                if rg.status_code == 200:
                    gj = rg.json()
                    attrs = gj.get("data", {}).get("attributes", {})
                    price = float(attrs.get("price_usd") or 0)
                    mcap = float(attrs.get("fdv_usd") or attrs.get("market_cap_usd") or 0)
                    dummy_pair = {
                        "chainId": "solana",
                        "dexId": "geckoterminal",
                        "url": f"https://www.geckoterminal.com/solana/tokens/{mint}",
                        "pairAddress": mint[:10],
                        "baseToken": {"address": mint, "name": attrs.get("name") or "unknown", "symbol": attrs.get("symbol") or "UNKNOWN"},
                        "quoteToken": {"address": "So11111111111111111111111111111111111111112", "name": "Wrapped SOL", "symbol": "SOL"},
                        "priceUsd": str(price),
                        "priceNative": "0",
                        "liquidity": {"usd": float(attrs.get("total_reserve_in_usd") or attrs.get("reserve_in_usd") or 0)},
                        "volume": {"h24": float((attrs.get("volume_usd") or {}).get("h24") or 0) if isinstance((attrs.get("volume_usd") or {}), dict) else 0, "h1": 0, "h6": 0},
                        "txns": {"h24": {"buys": 0, "sells": 0}, "h1": {"buys": 0, "sells": 0}, "h6": {"buys": 0, "sells": 0}},
                        "priceChange": {"h24": float((attrs.get("price_change_percentage") or {}).get("h24") or 0) if isinstance((attrs.get("price_change_percentage") or {}), dict) else 0, "h1": 0, "h6": 0, "m5": 0},
                        "fdv": mcap,
                        "marketCap": mcap,
                        "pairCreatedAt": 0,
                    }
                    return {
                        "best_pair": dummy_pair,
                        "all_pairs_count": 1,
                        "total_liquidity_usd": dummy_pair["liquidity"]["usd"],
                        "total_vol_24h": dummy_pair["volume"]["h24"],
                        "txns_24h_buys": 0,
                        "txns_24h_sells": 0,
                        "price_usd": price,
                        "fdv": mcap,
                        "market_cap": mcap,
                        "priceChange": dummy_pair["priceChange"],
                        "pair_address": dummy_pair["pairAddress"],
                        "dex": "geckoterminal",
                    }, None
            except Exception as e2:
                import traceback
                traceback.print_exc()
                pass
            return None, {"error": f"DexScreener timeout ({last_err}) - coba refresh 5 detik lagi"}
    if data is None:
        return None, {"error": f"DexScreener timeout ({last_err})"}
    try:
        # lanjut parsing DexScreener normal
        _ = data  # keep data

        pairs = data.get("pairs") or []
        if not pairs:
            return None, {"error": "No pairs found di DexScreener (token belum ada DEX liquidity?)"}

        # Filter hanya Solana chain
        sol_pairs = [p for p in pairs if p.get("chainId") == "solana"]
        if not sol_pairs:
            sol_pairs = pairs

        # Prioritaskan pair dengan quote SOL/USDC/USDT untuk harga yang akurat
        # Kalau tidak ada, fallback ke liquidity terbesar
        STABLE_QUOTES = {
            "So11111111111111111111111111111111111111112",  # Wrapped SOL
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
            "11111111111111111111111111111111",  # SOL native
        }
        stable_pairs = [p for p in sol_pairs if p.get("quoteToken", {}).get("address") in STABLE_QUOTES]
        if stable_pairs:
            # pilih stable pair dengan volume 24h terbesar, kalau volume 0 pilih liquidity terbesar
            sol_pairs_sorted = sorted(
                stable_pairs,
                key=lambda x: ((x.get("volume") or {}).get("h24", 0) or 0, (x.get("liquidity") or {}).get("usd", 0) or 0),
                reverse=True,
            )
        else:
            sol_pairs_sorted = sorted(sol_pairs, key=lambda x: (x.get("liquidity") or {}).get("usd", 0) or 0, reverse=True)
        best = sol_pairs_sorted[0]

        total_liquidity = sum((p.get("liquidity") or {}).get("usd", 0) or 0 for p in sol_pairs)
        total_vol_24h = sum((p.get("volume") or {}).get("h24", 0) or 0 for p in sol_pairs)
        total_txns_buys_24h = sum((p.get("txns") or {}).get("h24", {}).get("buys", 0) or 0 for p in sol_pairs)
        total_txns_sells_24h = sum((p.get("txns") or {}).get("h24", {}).get("sells", 0) or 0 for p in sol_pairs)

        # Price change dari best pair
        price_usd = best.get("priceUsd")
        try:
            price_usd_f = float(price_usd) if price_usd else 0
        except:
            price_usd_f = 0

        fdv = best.get("fdv") or best.get("marketCap") or 0
        market_cap = best.get("marketCap") or fdv or 0

        info = {
            "best_pair": best,
            "all_pairs_count": len(sol_pairs),
            "total_liquidity_usd": total_liquidity,
            "total_vol_24h": total_vol_24h,
            "txns_24h_buys": total_txns_buys_24h,
            "txns_24h_sells": total_txns_sells_24h,
            "price_usd": price_usd_f,
            "fdv": fdv,
            "market_cap": market_cap,
            "priceChange": best.get("priceChange") or {},
            "pair_address": best.get("pairAddress"),
            "dex": best.get("dexId"),
        }
        return info, None
    except Exception as e:
        return None, {"error": str(e)}


def fetch_goplus_holders(mint: str):
    """Fallback holder dari GoPlus (gratis, no key) - dipakai kalau RugCheck topHolders None."""
    try:
        url = f"https://api.gopluslabs.io/api/v1/solana/token_security?contract_addresses={mint}"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        j = r.json()
        res = j.get("result", {}).get(mint)
        if not res:
            return None
        holders = res.get("holders") or []
        if not holders:
            return None
        total_supply_str = res.get("total_supply")
        try:
            total_supply = float(total_supply_str) if total_supply_str else 0
        except:
            total_supply = 0
        # GoPlus holders: percent adalah fraction (0.1372 = 13.72%), balance adalah uiAmount
        # Kita hitung pct yang benar = balance / total_supply *100 jika total_supply ada, else pakai percent*100
        mapped = []
        for h in holders[:15]:
            try:
                bal = float(h.get("balance", 0))
                # percent dari API adalah fraction, convert ke %
                pct_api = float(h.get("percent", 0)) * 100
                # Jika total_supply valid, hitung ulang lebih akurat
                pct_calc = (bal / total_supply * 100) if total_supply else pct_api
                # Gunakan pct_calc (lebih akurat)
                pct = pct_calc if pct_calc else pct_api
                mapped.append({
                    "address": h.get("token_account") or h.get("account") or "",
                    "pct": pct,
                    "amount": int(bal * 1_000_000) if bal else 0,  # raw approximation
                    "balance": bal,
                })
            except:
                continue
        # Sort desc by pct
        mapped.sort(key=lambda x: x["pct"], reverse=True)
        holder_count = res.get("holder_count")
        return {"holders": mapped, "holder_count": holder_count, "total_supply": total_supply}
    except:
        return None

def fetch_birdeye_holders(mint: str):
    """Fallback Birdeye (butuh BIRDEYE_API_KEY env) - holder lebih detail jika ada key."""
    api_key = os.getenv("BIRDEYE_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        url = f"https://public-api.birdeye.so/defi/token_holders?address={mint}&offset=0&limit=15"
        headers = {**HEADERS, "X-API-KEY": api_key, "x-chain": "solana"}
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        j = r.json()
        data = j.get("data", {})
        items = data.get("items") or data.get("holders") or []
        if not items:
            return None
        total_supply = 0
        # Birdeye tidak kasih total_supply di endpoint ini, ambil dari DexScreener atau GoPlus
        mapped = []
        for h in items[:15]:
            try:
                # Birdeye field: amount, uiAmount, owner, percentage?
                pct = float(h.get("percentage") or h.get("percent") or 0)
                # Birdeye percentage sudah dalam % (0-100) atau fraction? cek
                # Jika pct <1 dan holder besar, kemungkinan fraction -> *100
                if pct < 1 and pct > 0:
                    # cek apakah ini fraction (0.137) vs percent (13.7)
                    # Kita asumsikan jika top holder <5%, itu fraction, jadi *100
                    # Tapi kita biarkan apa adanya dan nanti dihitung di scoring
                    pass
                mapped.append({
                    "address": h.get("owner") or h.get("address") or "",
                    "pct": pct if pct > 1 else pct * 100,
                    "amount": int(float(h.get("amount", 0))),
                    "balance": float(h.get("uiAmount", 0)),
                })
            except:
                continue
        mapped.sort(key=lambda x: x["pct"], reverse=True)
        return {"holders": mapped, "holder_count": data.get("total") or len(mapped)}
    except:
        return None

def fetch_rugcheck(mint: str):
    """Ambil laporan RugCheck (gratis) + fallback GoPlus kalau topHolders None."""
    url = f"https://api.rugcheck.xyz/v1/tokens/{mint}/report"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code == 404:
            return None, {"error": "RugCheck 404 - token belum terindex"}
        r.raise_for_status()
        data = r.json()
        top_holders_raw = data.get("topHolders")
        holder_source = "rugcheck"
        goplus_fallback = None
        birdeye_fallback = None
        # RugCheck kadang return None untuk token besar (rate limit) - coba GoPlus -> Birdeye
        if top_holders_raw is None:
            goplus_fallback = fetch_goplus_holders(mint)
            if goplus_fallback and goplus_fallback.get("holders"):
                top_holders = goplus_fallback["holders"]
                top5_pct = sum(h.get("pct", 0) for h in top_holders[:5])
                top10_pct = sum(h.get("pct", 0) for h in top_holders[:10])
                top10_pct_raw = top10_pct
                holder_unavailable = False
                holder_source = "goplus"
            else:
                # Coba Birdeye jika ada key
                birdeye_fallback = fetch_birdeye_holders(mint)
                if birdeye_fallback and birdeye_fallback.get("holders"):
                    top_holders = birdeye_fallback["holders"]
                    top5_pct = sum(h.get("pct", 0) for h in top_holders[:5])
                    top10_pct = sum(h.get("pct", 0) for h in top_holders[:10])
                    top10_pct_raw = top10_pct
                    holder_unavailable = False
                    holder_source = "birdeye"
                else:
                    top_holders = []
                    top5_pct = 0
                    top10_pct = 0
                    top10_pct_raw = 0
                    holder_unavailable = True
        else:
            top_holders = top_holders_raw or []
            # hitung top5, top10 pct
            top5_pct = sum(h.get("pct", 0) for h in top_holders[:5])
            top10_pct = sum(h.get("pct", 0) for h in top_holders[:10])
            top10_pct_raw = top10_pct  # sudah dalam % (0-100)
            holder_unavailable = False

        # insider networks
        insider_detected = data.get("graphInsidersDetected", 0)
        insider_networks = data.get("insiderNetworks") or []

        # risks
        risks = data.get("risks") or []
        # score: 0 = berbahaya, 1 = aman di normalized? Dokumentasi: score_normalised 0-100, kecil = aman
        score = data.get("score")
        score_norm = data.get("score_normalised")

        # mint/freeze authority
        mint_auth = data.get("mintAuthority")
        freeze_auth = data.get("freezeAuthority")

        # total_holders fallback ke GoPlus/Birdeye jika RugCheck tidak ada
        total_holders = data.get("totalHolders")
        if (not total_holders or total_holders == 0):
            fallback_count = None
            if goplus_fallback and goplus_fallback.get("holder_count"):
                fallback_count = goplus_fallback.get("holder_count")
            elif birdeye_fallback and birdeye_fallback.get("holder_count"):
                fallback_count = birdeye_fallback.get("holder_count")
            if fallback_count:
                try:
                    total_holders = int(fallback_count)
                except:
                    pass
        info = {
            "raw": data,
            "score": score,
            "score_normalised": score_norm,
            "risks": risks,
            "top_holders": top_holders[:15] if top_holders else [],
            "top5_pct": top5_pct,
            "top10_pct": top10_pct_raw,
            "total_holders": total_holders,
            "insider_detected": insider_detected,
            "insider_networks": insider_networks,
            "mintAuthority": mint_auth,
            "freezeAuthority": freeze_auth,
            "markets_count": len(data.get("markets") or {}),
            "holder_unavailable": holder_unavailable,
            "holder_source": holder_source,
        }
        return info, None
    except Exception as e:
        return None, {"error": str(e)}


def fetch_coingecko_context():
    """Ambil BTC & SOL context dari CoinGecko (gratis)."""
    url = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin,solana&vs_currencies=usd&include_24hr_change=true"
    try:
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
        btc = data.get("bitcoin", {})
        sol = data.get("solana", {})
        return {
            "btc_price": btc.get("usd"),
            "btc_24h_change": btc.get("usd_24h_change"),
            "sol_price": sol.get("usd"),
            "sol_24h_change": sol.get("usd_24h_change"),
        }, None
    except Exception as e:
        return None, {"error": str(e)}


def fetch_coingecko_token_by_search(mint: str, symbol_hint: str = None):
    """
    Coba cari token di CoinGecko untuk dapat volume CEX.
    Untuk large cap kayak WIF/BONK ini penting karena DEX liquidity kecil tapi CEX besar.
    Kita pakai search API gratis.
    """
    # mapping hardcode untuk token populer biar gak kena rate limit search
    known = {
        WIF_MINT: "dogwifcoin",
        BONK_MINT: "bonk",
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "usd-coin",
    }
    cg_id = known.get(mint)
    if not cg_id:
        return None
    try:
        url = f"https://api.coingecko.com/api/v3/coins/{cg_id}?localization=false&tickers=false&market_data=true&community_data=false&developer_data=false"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code != 200:
            return None
        data = r.json()
        md = data.get("market_data", {})
        return {
            "id": cg_id,
            "price_usd": md.get("current_price", {}).get("usd"),
            "market_cap": md.get("market_cap", {}).get("usd"),
            "volume_24h": md.get("total_volume", {}).get("usd"),
            "price_change_24h": md.get("price_change_percentage_24h"),
        }
    except:
        return None


def calculate_durability(dex, rug, cg_token):
    """
    Hitung durability score 0-100.
    Logic mengikuti framework 4 pilar penelitian:
    - Holder distribution
    - Whale concentration (top5 20%, top10 30%)
    - Liquidity / MCAP ratio (MCAP illusion)
    - Risks (mint/freeze, honeypot)
    """
    score = 100
    reasons = []
    flags = []

    if not dex or not rug:
        return 0, ["Data tidak lengkap"], ["DATA_MISSING"]

    # 1. Holder distribution
    holders = rug.get("total_holders") or 0
    if holders == 0:
        score -= 25
        reasons.append("Holder count 0 / tidak terdeteksi (-25)")
        flags.append("NO_HOLDERS")
    elif holders < 500:
        score -= 20
        reasons.append(f"Holder sangat sedikit ({holders}) (-20)")
        flags.append("HOLDER_TOO_FEW")
    elif holders < 2000:
        score -= 10
        reasons.append(f"Holder sedikit ({holders}) (-10)")
        flags.append("HOLDER_LOW")
    elif holders > 100000:
        reasons.append(f"Holder sangat luas ({holders}) (+0)")

    # 2. Whale concentration
    if rug.get("holder_unavailable"):
        reasons.append(f"Holder detail tidak tersedia dari RugCheck (limit API) - total holders {holders} terdeteksi, cek manual di SolScan/Solana Explorer untuk Top10")
        flags.append("HOLDER_DATA_UNAVAILABLE")
        # Jangan penalti whale jika data tidak ada, tapi beri warning
        # Gunakan score_normalised sebagai proxy: jika <=30 aman, >50 waspada
        sn = rug.get("score_normalised") or 99
        if sn > 50:
            score -= 10
            reasons.append(f"RugCheck score {sn} agak tinggi tanpa detail holder (-10)")
            flags.append("SCORE_MEDIUM")
    else:
        top5 = rug.get("top5_pct", 0)
        top10 = rug.get("top10_pct", 0)
        # RugCheck pct sudah dalam 0-100 scale, contoh WIF top10 44.12
        # Threshold framework: top5 >20% atau top10 >30% = bahaya
        # Tapi untuk large cap dengan holder >100k dan score_normalised bagus, kurangi penalti karena banyak top holder adalah CEX
        is_large_verified = holders > 100000 and (rug.get("score_normalised") or 99) <= 10
        if top10 > 50:
            pen = 10 if is_large_verified else 30
            score -= pen
            reasons.append(f"Top10 pegang {top10:.1f}% (>{'50%'}) konsentrasi ekstrim (-{pen}) {'[DISKON karena large cap CEX]' if is_large_verified else ''}")
            flags.append("WHALE_EXTREME")
        elif top10 > 30:
            pen = 5 if is_large_verified else 20
            score -= pen
            reasons.append(f"Top10 pegang {top10:.1f}% (>30% threshold) (-{pen}) {'[DISKON CEX]' if is_large_verified else ''}")
            flags.append("WHALE_HIGH")
        elif top5 > 20:
            pen = 5 if is_large_verified else 15
            score -= pen
            reasons.append(f"Top5 pegang {top5:.1f}% (>20% threshold) (-{pen})")
            flags.append("WHALE_MEDIUM")
        else:
            reasons.append(f"Whale concentration aman Top10 {top10:.1f}% Top5 {top5:.1f}%")

    # 3. Liquidity / MCAP ratio & Volume
    mcap = dex.get("market_cap") or dex.get("fdv") or 0
    liq = dex.get("total_liquidity_usd") or 0
    vol = dex.get("total_vol_24h") or 0

    # Cek CEX volume jika ada
    cex_vol = None
    if cg_token and cg_token.get("volume_24h"):
        cex_vol = cg_token["volume_24h"]
        # Jika ada CEX volume besar, pakai itu sebagai liquidity proxy
        if cex_vol > 5_000_000:
            reasons.append(f"CEX volume besar ${cex_vol:,.0f} -> DEX liquidity tipis diabaikan (token CEX-listed)")
            # Jangan penalti liquidity kalau CEX volume besar
            liq_ratio = 1  # fake aman
        else:
            liq_ratio = (liq / mcap * 100) if mcap else 0
    else:
        liq_ratio = (liq / mcap * 100) if mcap else 0

    if cex_vol is None or cex_vol < 5_000_000:
        if mcap and liq_ratio < 0.05:
            score -= 25
            reasons.append(f"MCAP illusion: MCAP ${mcap:,.0f} tapi DEX liquidity cuma ${liq:,.0f} ({liq_ratio:.4f}%) (-25)")
            flags.append("MCAP_ILLUSION")
        elif liq_ratio < 0.5:
            score -= 15
            reasons.append(f"Liquidity tipis: {liq_ratio:.3f}% dari MCAP (-15)")
            flags.append("LIQUIDITY_THIN")
        elif liq_ratio < 2:
            score -= 5
            reasons.append(f"Liquidity cukup tipis {liq_ratio:.2f}% (-5)")
        else:
            reasons.append(f"Liquidity sehat {liq_ratio:.2f}% dari MCAP")

        # Volume check (DEX only)
        if vol < 50_000:
            score -= 15
            reasons.append(f"Volume DEX 24h sangat kecil ${vol:,.0f} (<$50k) (-15)")
            flags.append("VOLUME_TOO_LOW")
        elif vol < 1_000_000:
            # Untuk large cap ini akan false alarm, tapi sudah di-handle cex_vol di atas
            score -= 10
            reasons.append(f"Volume DEX 24h kecil ${vol:,.0f} (<$1M) (-10)")
            flags.append("VOLUME_LOW")

    # 4. Risks dari RugCheck
    risks = rug.get("risks") or []
    if risks:
        high_risk_names = [r.get("name") for r in risks]
        score -= min(25, len(risks) * 8)
        reasons.append(f"RugCheck risks: {', '.join(high_risk_names)} (-{min(25,len(risks)*8)})")
        flags.append("RUG_RISK")
    else:
        reasons.append("RugCheck: No critical risks detected")

    if rug.get("mintAuthority"):
        score -= 20
        reasons.append("Mint authority masih aktif (bisa cetak token baru) (-20)")
        flags.append("MINT_AUTHORITY")
    if rug.get("freezeAuthority"):
        score -= 15
        reasons.append("Freeze authority aktif (-15)")
        flags.append("FREEZE_AUTHORITY")

    # Insider network
    insiders = rug.get("insider_detected") or 0
    if insiders > 100:
        # Untuk WIF insiders 4992 tapi score 1 (artinya network lama / transfer history, bukan insider aktif)
        # Kita cek apakah score_normalised bagus, kalau bagus jangan penalti berat
        if (rug.get("score_normalised") or 99) > 20:
            score -= 15
            reasons.append(f"Insider network terdeteksi {insiders} wallets (-15)")
            flags.append("INSIDER_NETWORK")
        else:
            reasons.append(f"Insider graph {insiders} tapi score RugCheck aman (dianggap historis)")

    # Tx buys vs sells ratio (proxy sentiment)
    buys = dex.get("txns_24h_buys", 0)
    sells = dex.get("txns_24h_sells", 0)
    total_tx = buys + sells
    if total_tx > 0:
        buy_ratio = buys / total_tx * 100
        if buy_ratio > 65:
            reasons.append(f"Buy pressure kuat 24h: {buy_ratio:.1f}% buys ({buys} vs {sells} sells)")
        elif buy_ratio < 35:
            score -= 10
            reasons.append(f"Sell pressure 24h: hanya {buy_ratio:.1f}% buys ({buys} vs {sells}) (-10)")
            flags.append("SELL_PRESSURE")
        else:
            reasons.append(f"Tx balance 24h: {buy_ratio:.1f}% buys")

    score = max(0, min(100, score))
    return score, reasons, flags


def attribute_move(dex, rug, btc_ctx, cg_token):
    """
    Attribution engine: kenapa naik/turun?
    Urutan cek (sesuai research):
    1. BTC/SOL correlation + beta amplification
    2. Whale concentration risk
    3. Volume/liquidity
    4. Sentiment proxy (tx ratio + priceChange)
    """
    reasons = []
    primary = "UNKNOWN"

    if not dex:
        return "DATA_MISSING", ["Data DEX tidak ada"]

    price_change_24h = dex.get("priceChange", {}).get("h24")
    price_change_1h = dex.get("priceChange", {}).get("h1")
    if price_change_24h is None:
        price_change_24h = 0
    try:
        pc = float(price_change_24h)
    except:
        pc = 0

    btc_ch = 0
    if btc_ctx and btc_ctx.get("btc_24h_change") is not None:
        try:
            btc_ch = float(btc_ctx["btc_24h_change"])
        except:
            btc_ch = 0

    sol_ch = 0
    if btc_ctx and btc_ctx.get("sol_24h_change") is not None:
        try:
            sol_ch = float(btc_ctx["sol_24h_change"])
        except:
            sol_ch = 0

    buys = dex.get("txns_24h_buys", 0)
    sells = dex.get("txns_24h_sells", 0)
    is_up = pc > 5
    is_down = pc < -5
    is_flat = -5 <= pc <= 5

    # 1. BTC / SOL beta: jika BTC/SOL naik dan token naik lebih kencang = beta amplification (khas meme)
    if abs(btc_ch) > 3 and pc > 0 and btc_ch > 0:
        if abs(pc - btc_ch) < 7:
            reasons.append(f"BTC-driven: BTC {btc_ch:+.1f}% 24h, token {pc:+.1f}% (korelasi 1:1)")
            primary = "BTC_CORRELATED"
        elif pc > btc_ch + 5:
            reasons.append(f"BTC beta amplification: BTC {btc_ch:+.1f}% tapi token {pc:+.1f}% (meme beta {pc/btc_ch:.1f}x) - rotasi risk-on ke meme")
            primary = "BTC_BETA_AMPLIFIED"
    elif abs(btc_ch) > 3 and pc < 0 and btc_ch < 0:
        if abs(pc - btc_ch) < 7:
            reasons.append(f"BTC-driven crash: BTC {btc_ch:+.1f}% 24h, token {pc:+.1f}%")
            primary = "BTC_CORRELATED_DOWN"
        elif pc < btc_ch - 5:
            reasons.append(f"BTC beta crash: BTC {btc_ch:+.1f}% tapi token {pc:+.1f}% (jatuh lebih dalam {abs(pc/btc_ch):.1f}x)")
            primary = "BTC_BETA_CRASH"

    # SOL echo (karena Solana meme, SOL sering jadi leading indicator)
    if abs(sol_ch) > 3 and primary == "UNKNOWN":
        if abs(pc - sol_ch) < 5:
            reasons.append(f"SOL ecosystem: SOL {sol_ch:+.1f}% 24h, token {pc:+.1f}% - rotasi ekosistem Solana")
            primary = "SOL_CORRELATED"

    # 2. Whale risk
    top10 = rug.get("top10_pct", 0) if rug else 0
    if top10 > 30:
        reasons.append(f"Whale Risk: Top10 {top10:.1f}% (>30%) - 1 whale jual bisa crash 50-90% karena liquidity tipis (MCAP illusion)")
        if is_down and primary == "UNKNOWN":
            primary = "WHALE_DISTRIBUTION_SUSPECTED"

    # 3. Liquidity amplification
    liq = dex.get("total_liquidity_usd", 0)
    mcap = dex.get("market_cap", 0)
    liq_ratio = (liq / mcap * 100) if mcap else 0
    cex_vol = cg_token.get("volume_24h") if cg_token else 0
    if (cex_vol or 0) < 1_000_000 and liq_ratio < 0.1 and abs(pc) > 20:
        reasons.append(f"Low Liquidity Amplification: MCAP ${mcap:,.0f} tapi DEX liq ${liq:,.0f} ({liq_ratio:.4f}%) - move {pc:+.1f}% bisa dari modal kecil LPI (median $54 bisa +500%)")
        if primary == "UNKNOWN":
            primary = "LOW_LIQUIDITY_AMPLIFICATION"

    # 4. Sentiment / FOMO proxy
    total_tx = buys + sells
    buy_ratio = (buys / total_tx * 100) if total_tx else 50
    if is_up and buy_ratio > 65 and total_tx > 50:
        reasons.append(f"Sentiment-driven: Buy ratio {buy_ratio:.0f}% ({buys} buys vs {sells} sells) + price {pc:+.1f}% - FOMO / viral mungkin")
        if primary == "UNKNOWN":
            primary = "SENTIMENT_FOMO"
    elif is_down and buy_ratio < 35:
        reasons.append(f"Sell pressure: Buy ratio cuma {buy_ratio:.0f}% ({buys} vs {sells}) + price {pc:+.1f}% - distribusi / take profit")
        if primary == "UNKNOWN":
            primary = "SELL_PRESSURE"

    # 5. Volume thin = manipulasi curiga
    vol = dex.get("total_vol_24h", 0)
    if vol < 100_000 and abs(pc) > 30:
        reasons.append(f"Volume tipis ${vol:,.0f} tapi price {pc:+.1f}% - curiga wash trading / LPI (82.8% high-return coin manipulatif)")
        if primary == "UNKNOWN":
            primary = "SUSPECTED_MANIPULATION"

    if is_flat:
        reasons.append(f"Sideways: token {pc:+.1f}% 24h, BTC {btc_ch:+.1f}%, SOL {sol_ch:+.1f}% - tidak ada katalis kuat, tunggu breakout")
        if primary == "UNKNOWN":
            primary = "SIDEWAYS_NO_CATALYST"

    if not reasons:
        reasons.append(f"Move {pc:+.1f}% 24h tanpa sinyal kuat di data gratis - butuh cek social (X/Telegram) manual & cek holder flow histori")

    return primary, reasons


def save_snapshot(mint, dex, rug):
    """Simpan snapshot untuk komparasi whale cabut next run."""
    snap = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "mint": mint,
        "price_usd": dex.get("price_usd") if dex else None,
        "top10_pct": rug.get("top10_pct") if rug else None,
        "top_holders": rug.get("top_holders")[:5] if rug else [],
        "total_holders": rug.get("total_holders") if rug else None,
        "liquidity": dex.get("total_liquidity_usd") if dex else None,
        "volume_24h": dex.get("total_vol_24h") if dex else None,
    }
    path = os.path.join(SNAPSHOT_DIR, f"{mint[:8]}.json")
    # load old untuk diff
    old = None
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                old = json.load(f)
        except:
            old = None
    with open(path, "w") as f:
        json.dump(snap, f, indent=2)
    return old, snap


def main():
    parser = argparse.ArgumentParser(description="Solana Meme Screener & Attribution (Free Stack)")
    parser.add_argument("--mint", required=True, help="Solana mint address (CA)")
    parser.add_argument("--explain", action="store_true", help="Jelaskan detail scoring")
    parser.add_argument("--snapshot", action="store_true", help="Simpan snapshot & bandingkan dengan run sebelumnya (deteksi whale cabut)")
    args = parser.parse_args()

    mint = args.mint.strip()
    print(f"\n{'='*70}")
    print(f"MEME SCREENER SOLANA - Free Stack | {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print(f"Mint: {mint}")
    print(f"{'='*70}")

    # Fetch semua
    print("[1/4] Fetch DexScreener...")
    dex, dex_err = fetch_dexscreener(mint)
    if dex_err:
        print(f"  ! Error: {dex_err}")
    else:
        print(f"  OK: {dex['all_pairs_count']} pairs, price ${dex['price_usd']:.6f}, MCAP ${dex['market_cap']:,.0f}, Liq ${dex['total_liquidity_usd']:,.0f}, Vol24h ${dex['total_vol_24h']:,.0f}")

    print("[2/4] Fetch RugCheck...")
    rug, rug_err = fetch_rugcheck(mint)
    if rug_err:
        print(f"  ! Error: {rug_err}")
    else:
        print(f"  OK: Score {rug['score']} (norm {rug['score_normalised']}), Holders {rug['total_holders']}, Top10 {rug['top10_pct']:.1f}%, Risks {len(rug['risks'])}")

    print("[3/4] Fetch BTC/SOL context...")
    btc_ctx, btc_err = fetch_coingecko_context()
    if btc_err:
        print(f"  ! Error: {btc_err}")
        btc_ctx = {"btc_24h_change": 0, "sol_24h_change": 0}
    else:
        print(f"  OK: BTC {btc_ctx['btc_24h_change']:+.2f}% 24h, SOL {btc_ctx['sol_24h_change']:+.2f}% 24h")

    print("[4/4] Fetch CoinGecko CEX volume (jika large cap)...")
    cg_tok = fetch_coingecko_token_by_search(mint)
    if cg_tok:
        print(f"  OK: CEX {cg_tok['id']} Vol24h ${cg_tok['volume_24h']:,.0f} MCAP ${cg_tok['market_cap']:,.0f}")
        # Override DEX MCAP yang sering ngawur untuk pair aneh (BONK/JUP case)
        if cg_tok.get("market_cap") and dex:
            # jika selisih >5x, pakai CoinGecko
            dex_mcap = dex.get("market_cap") or 0
            cg_mcap = cg_tok["market_cap"]
            if dex_mcap and cg_mcap and abs(dex_mcap - cg_mcap) / max(cg_mcap, 1) > 0.5:
                print(f"  -> Override MCAP DEX ${dex_mcap:,.0f} -> CEX ${cg_mcap:,.0f} (lebih akurat)")
                dex["market_cap"] = cg_mcap
                dex["price_usd"] = cg_tok.get("price_usd") or dex["price_usd"]
    else:
        print("  - Tidak ada data CEX (token kecil / belum listing CoinGecko)")

    print(f"\n{'-'*70}")
    if not dex or not rug:
        print("GAGAL: Data tidak lengkap, tidak bisa scoring.")
        if dex_err:
            print(" DexScreener err:", dex_err)
        if rug_err:
            print(" RugCheck err:", rug_err)
        sys.exit(1)

    # Scoring
    score, reasons, flags = calculate_durability(dex, rug, cg_tok)
    level = "AMAN" if score >= 75 else "WASPADA" if score >= 50 else "BERBAHAYA" if score >= 30 else "EXTREME RISK"
    emoji = "[OK]" if score >=75 else "[WARN]" if score >=50 else "[RISK]" if score >=30 else "[DANGER]"

    print(f"DURABILITY SCORE: {score}/100 {emoji} [{level}]")
    print(f"Flags: {', '.join(flags) if flags else 'None'}")
    if args.explain or score < 70:
        print("\nDetail Scoring:")
        for r in reasons:
            print(f"  - {r}")

    # Attribution
    primary, attr_reasons = attribute_move(dex, rug, btc_ctx, cg_tok)
    pc24 = dex.get("priceChange", {}).get("h24", 0)
    pc1 = dex.get("priceChange", {}).get("h1", 0)
    print(f"\n{'-'*70}")
    print(f"ATTRIBUTION ENGINE (Kenapa Naik/Turun?)")
    print(f"Price: {pc24:+.1f}% 24h | {pc1:+.1f}% 1h | BTC {btc_ctx['btc_24h_change']:+.2f}% | SOL {btc_ctx['sol_24h_change']:+.2f}%")
    print(f"Primary Driver: {primary}")
    for r in attr_reasons:
        print(f"  - {r}")

    # Snapshot diff
    if args.snapshot:
        old, new = save_snapshot(mint, dex, rug)
        print(f"\n{'-'*70}")
        print("SNAPSHOT (Whale Cabut Detector):")
        if old:
            # diff top10
            old_top10 = old.get("top10_pct") or 0
            new_top10 = new.get("top10_pct") or 0
            diff_top10 = new_top10 - old_top10
            old_price = old.get("price_usd") or 0
            new_price = new.get("price_usd") or 0
            price_diff_pct = ((new_price - old_price)/old_price*100) if old_price else 0
            print(f"  Prev: {old['timestamp']} price ${old_price:.6f} top10 {old_top10:.1f}%")
            print(f"  Now : {new['timestamp']} price ${new_price:.6f} top10 {new_top10:.1f}%")
            print(f"  Delta: price {price_diff_pct:+.2f}% top10 {diff_top10:+.2f}ppt holders {old.get('total_holders')} -> {new.get('total_holders')}")
            if diff_top10 < -2:
                print("  >> ALERT: Top10 turun >2ppt = whale distribusi / cabut terdeteksi!")
            elif diff_top10 > 2:
                print("  >> Top10 naik = akumulasi whale")
            else:
                print("  >> Tidak ada perubahan whale signifikan")
        else:
            print(f"  Snapshot disimpan ke snapshots/{mint[:8]}.json (run lagi nanti untuk deteksi perubahan)")

    # Rekomendasi action
    print(f"\n{'-'*70}")
    print("REKOMENDASI (bukan financial advice):")
    if score >= 75:
        print("  Hold / Monitoring rutin. Cek snapshot harian untuk whale flow.")
    elif score >= 50:
        print("  Waspada: position size kecil saja, set stop. Pantau whale & BTC.")
    elif score >= 30:
        print("  Berbahaya: hindari entry baru, jika hold pertimbangkan reduce.")
    else:
        print("  Extreme Risk: 95% token seperti ini mati di <90 hari. Skip.")

    # Raw detail untuk debug
    if args.explain:
        print(f"\n{'-'*70}")
        print("RAW DEX Best Pair:")
        print(json.dumps(dex["best_pair"], indent=2)[:2000])
        print("\nRAW Rug TopHolders (5):")
        for h in rug["top_holders"][:5]:
            print(f"  {h.get('address')[:12]}... {h.get('pct'):.2f}%")

    print(f"{'='*70}\n")


if __name__ == "__main__":
    main()
