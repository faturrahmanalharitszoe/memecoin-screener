"""
Bagger Hunter - filter micin yang potensi 10x-100x
Kriteria: mcap $0.5M-50M, holder 500-50k, top10 <35%, vol/mcap 10-50%, durability >55, social 65+, umur 7-90 hari
"""
import requests
import time

HEADERS = {"User-Agent": "meme-screener-bagger/1.0"}

# Cache untuk trending
TRENDING_CACHE = {"data": None, "ts": 0}
TRENDING_TTL = 300  # 5 menit

def fetch_trending_solana(limit=15):
    """Ambil trending Solana tokens dari DexScreener + Pump.fun"""
    now = time.time()
    if TRENDING_CACHE["data"] and now - TRENDING_CACHE["ts"] < TRENDING_TTL:
        return TRENDING_CACHE["data"]
    
    tokens = []
    # 1. DexScreener trending All-Chain (Solana, ETH, BSC, Base, Robinhood chain)
    try:
        # Coba trending all-chain dulu, fallback ke search SOL
        trending_urls = [
            "https://api.dexscreener.com/latest/dex/search/?q=PEPE",
            "https://api.dexscreener.com/latest/dex/search/?q=DOGE",
            "https://api.dexscreener.com/latest/dex/search/?q=SOL",
        ]
        all_pairs = []
        for turl in trending_urls:
            try:
                r = requests.get(turl, headers=HEADERS, timeout=8)
                if r.status_code == 200:
                    j = r.json()
                    all_pairs.extend(j.get("pairs", [])[:30])
            except:
                continue
        # Filter: ambil semua chain, sort by volume
        seen = set()
        for p in sorted(all_pairs, key=lambda x: (x.get("volume", {}).get("h24") or 0), reverse=True):
            mint = p.get("baseToken", {}).get("address")
            chain = p.get("chainId")
            # key unik mint+chain biar gak duplikat lintas chain
            key = f"{chain}:{mint}"
            if mint and key not in seen and len(tokens) < limit:
                seen.add(key)
                tokens.append({
                    "mint": mint,
                    "chain": chain,
                    "symbol": p.get("baseToken", {}).get("symbol"),
                    "name": p.get("baseToken", {}).get("name"),
                    "priceUsd": p.get("priceUsd"),
                    "volume24h": p.get("volume", {}).get("h24"),
                    "liquidity": p.get("liquidity", {}).get("usd"),
                    "fdv": p.get("fdv"),
                    "pairUrl": p.get("url"),
                })
    except Exception as e:
        print(f"[BAGGER] DexScreener trending fail {e}")
    
    # 2. Pump.fun trending (jika ada)
    try:
        r = requests.get("https://frontend-api.pump.fun/coins/trending", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            j = r.json()
            for c in j[:20]:
                mint = c.get("mint")
                if mint and mint not in [t["mint"] for t in tokens] and len(tokens) < limit:
                    tokens.append({
                        "mint": mint,
                        "symbol": c.get("symbol"),
                        "name": c.get("name"),
                        "priceUsd": None,
                        "volume24h": None,
                        "liquidity": None,
                        "fdv": None,
                        "pairUrl": f"https://pump.fun/coin/{mint}",
                    })
    except:
        pass

    TRENDING_CACHE["data"] = tokens
    TRENDING_CACHE["ts"] = now
    return tokens

def is_bagger_candidate(dex, rug, social, durability_score):
    """Cek apakah token potensi bagger"""
    if not dex or not rug:
        return False, "data tidak lengkap"
    
    mcap = dex.get("market_cap") or dex.get("fdv") or 0
    liq = dex.get("total_liquidity_usd") or 0
    holders = rug.get("total_holders") or 0
    top10 = rug.get("top10_pct") or 0
    vol = dex.get("total_vol_24h") or 0
    liq_ratio = (liq / mcap * 100) if mcap else 0
    vol_ratio = (vol / mcap * 100) if mcap else 0
    social_score = social.get("score", 50) if social else 50

    reasons = []
    is_bagger = True

    # Market cap 0.5M - 50M
    if mcap < 500_000:
        is_bagger = False
        reasons.append(f"mcap terlalu kecil ${mcap:,.0f} (<500k) - risiko scam")
    elif mcap > 50_000_000:
        is_bagger = False
        reasons.append(f"mcap besar ${mcap:,.0f} (>50M) - sudah bukan micin bagger")

    # Liquidity
    if liq < 50_000:
        is_bagger = False
        reasons.append(f"liq tipis ${liq:,.0f} (<50k)")
    if liq_ratio < 2:
        is_bagger = False
        reasons.append(f"liq/mcap {liq_ratio:.2f}% (<2%) MCAP illusion")

    # Holders
    if holders < 500:
        is_bagger = False
        reasons.append(f"holders {holders} (<500) terlalu sepi")
    elif holders > 50000:
        # masih bisa bagger tapi sudah ramai
        reasons.append(f"holders {holders} (>50k) ramai - bagger potensi menipis")

    # Whale
    if top10 > 35:
        is_bagger = False
        reasons.append(f"top10 {top10:.1f}% (>35%) whale risk")

    # Volume
    if vol < 100_000:
        is_bagger = False
        reasons.append(f"vol 24h ${vol:,.0f} (<100k) sepi")
    if vol_ratio < 10:
        is_bagger = False
        reasons.append(f"vol/mcap {vol_ratio:.1f}% (<10%) kurang aktif")
    if vol_ratio > 50:
        reasons.append(f"vol/mcap {vol_ratio:.1f}% (>50%) wash curiga")

    # Durability
    if durability_score < 55:
        is_bagger = False
        reasons.append(f"durability {durability_score} (<55) struktur lemah")

    # Social
    if social_score < 65:
        is_bagger = False
        reasons.append(f"social {social_score} (<65) belum viral")

    # Price already pumped?
    pc24 = dex.get("priceChange", {}).get("h24") or 0
    try:
        pc24_f = float(pc24)
        if pc24_f > 300:
            is_bagger = False
            reasons.append(f"udah pump +{pc24_f:.0f}% 24h - telat")
    except:
        pass

    if is_bagger:
        reasons.append(f"bagger candidate: mcap ${mcap:,.0f} holders {holders} top10 {top10:.1f}% vol {vol_ratio:.1f}% durability {durability_score} social {social_score}")

    return is_bagger, "; ".join(reasons)
