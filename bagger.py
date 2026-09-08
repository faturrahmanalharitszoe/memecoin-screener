"""
Bagger Hunter - filter micin yang potensi 10x-100x
Kriteria: mcap $0.5M-50M, holder 500-50k, top10 <35%, vol/mcap 10-50%, durability >55, social 65+, umur 7-90 hari
"""
import requests
import time

HEADERS = {"User-Agent": "meme-screener-bagger/1.0"}

# Exclude stable/large cap yang bukan micin bagger
EXCLUDE_SYMBOLS = {"SOL", "WSOL", "WETH", "WBNB", "USDC", "USDT", "WLD", "PYTH", "JUP", "RAY", "ORCA"}  # only base, not meme
EXCLUDE_MINTS = set()  # bisa tambah mint yang mau exclude

# Cache untuk trending
TRENDING_CACHE = {"data": None, "ts": 0}
TRENDING_TTL = 300  # 5 menit

def fetch_trending_solana(limit=15, beyond_trending=False):
    """Ambil trending + new micin dari DexScreener + Pump.fun (all-chain). beyond_trending=True = scan new pump.fun juga"""
    # cache key beda untuk beyond
    cache_key = f"beyond_{limit}" if beyond_trending else f"trending_{limit}"
    now = time.time()
    # simple cache per limit+mode
    if TRENDING_CACHE["data"] and now - TRENDING_CACHE["ts"] < TRENDING_TTL and TRENDING_CACHE.get("key") == cache_key:
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
        # Filter: ambil semua chain, sort by volume, exclude stable/large cap
        seen = set()
        for p in sorted(all_pairs, key=lambda x: (x.get("volume", {}).get("h24") or 0), reverse=True):
            mint = p.get("baseToken", {}).get("address")
            chain = p.get("chainId")
            symbol = (p.get("baseToken", {}).get("symbol") or "").upper()
            # skip stable/large cap
            if symbol in EXCLUDE_SYMBOLS:
                continue
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
    
    # 2. Pump.fun trending (micin beneran, bukan stable)
    try:
        r = requests.get("https://frontend-api.pump.fun/coins/trending", headers=HEADERS, timeout=10)
        if r.status_code == 200:
            j = r.json()
            for c in j[:20]:
                mint = c.get("mint")
                symbol = (c.get("symbol") or "").upper()
                if symbol in EXCLUDE_SYMBOLS:
                    continue
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

    # 3. Jika beyond_trending, tambah new Pump.fun coins (bukan cuma trending)
    if beyond_trending:
        try:
            # Pump.fun new coins (bukan trending)
            r = requests.get("https://frontend-api.pump.fun/coins?offset=0&limit=30&sort=created_timestamp&order=DESC&includeNsfw=false", headers=HEADERS, timeout=8)
            if r.status_code == 200:
                j = r.json()
                # bisa array atau object dengan coins
                coins = j if isinstance(j, list) else j.get("coins", [])
                for c in coins[:20]:
                    mint = c.get("mint")
                    symbol = (c.get("symbol") or "").upper()
                    if symbol in EXCLUDE_SYMBOLS:
                        continue
                    if mint and mint not in [t["mint"] for t in tokens] and len(tokens) < limit + 10:
                        tokens.append({
                            "mint": mint,
                            "chain": "solana",
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
        # DexScreener new pairs (all-chain)
        try:
            r = requests.get("https://api.dexscreener.com/latest/dex/search/?q=pepe", headers=HEADERS, timeout=8)
            # sudah di atas, skip
            pass
        except:
            pass

    TRENDING_CACHE["data"] = tokens
    TRENDING_CACHE["ts"] = now
    TRENDING_CACHE["key"] = cache_key
    return tokens

def is_bagger_candidate(dex, rug, social, durability_score, relaxed=False):
    """Cek apakah token potensi bagger"""
    # threshold
    mcap_max = 100_000_000 if relaxed else 50_000_000
    durability_min = 45 if relaxed else 55
    social_min = 50 if relaxed else 65
    top10_max = 40 if relaxed else 35
    vol_ratio_min = 5 if relaxed else 10
    holders_min = 300 if relaxed else 500
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

    # Market cap 0.5M - 50M (100M kalau relaxed)
    if mcap < 500_000:
        is_bagger = False
        reasons.append(f"mcap terlalu kecil ${mcap:,.0f} (<500k) - risiko scam")
    elif mcap > mcap_max:
        is_bagger = False
        reasons.append(f"mcap besar ${mcap:,.0f} (>{mcap_max/1_000_000:.0f}M) - sudah bukan micin bagger")

    # Liquidity
    if liq < 50_000:
        is_bagger = False
        reasons.append(f"liq tipis ${liq:,.0f} (<50k)")
    if liq_ratio < 2:
        is_bagger = False
        reasons.append(f"liq/mcap {liq_ratio:.2f}% (<2%) MCAP illusion")

    # Holders
    if holders < holders_min:
        is_bagger = False
        reasons.append(f"holders {holders} (<{holders_min}) terlalu sepi")
    elif holders > 50000:
        # masih bisa bagger tapi sudah ramai
        reasons.append(f"holders {holders} (>50k) ramai - bagger potensi menipis")

    # Whale
    if top10 > top10_max:
        is_bagger = False
        reasons.append(f"top10 {top10:.1f}% (>{top10_max}%) whale risk")

    # Volume
    if vol < 100_000:
        is_bagger = False
        reasons.append(f"vol 24h ${vol:,.0f} (<100k) sepi")
    if vol_ratio < vol_ratio_min:
        is_bagger = False
        reasons.append(f"vol/mcap {vol_ratio:.1f}% (<{vol_ratio_min}%) kurang aktif")
    if vol_ratio > 50:
        reasons.append(f"vol/mcap {vol_ratio:.1f}% (>50%) wash curiga")

    # Durability
    if durability_score < durability_min:
        is_bagger = False
        reasons.append(f"durability {durability_score} (<{durability_min}) struktur lemah")

    # Social
    if social_score < social_min:
        is_bagger = False
        reasons.append(f"social {social_score} (<{social_min}) belum viral")

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
