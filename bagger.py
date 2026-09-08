"""
Bagger Hunter - filter micin yang potensi 10x-100x
Kriteria: mcap $0.5M-50M, holder 500-50k, top10 <35%, vol/mcap 10-50%, durability >55, social 65+, umur 7-90 hari
"""
import requests
import time

HEADERS = {"User-Agent": "meme-screener-bagger/1.0"}

# Exclude stable/large cap yang bukan micin bagger
EXCLUDE_SYMBOLS = {"SOL", "WSOL", "WETH", "WBNB", "USDC", "USDT", "WLD", "PYTH", "JUP", "RAY", "ORCA"}  # only base, not meme
# Copycat symbols yang sering bikin sampah di Solana
COPYCAT_SYMBOLS = {"PEPE", "DOGE", "SHIB", "FLOKI", "BOME", "POPCAT", "WIF", "BONK"}
EXCLUDE_MINTS = set()  # bisa tambah mint yang mau exclude

# Chain mapping for GeckoTerminal -> DexScreener
GECKO_CHAIN_MAP = {"solana": "solana", "bsc": "bsc", "eth": "ethereum", "base": "base"}

# Known whale wallets (Robinhood, Market Maker) - detect when they buy new micin
KNOWN_WHALE_WALLETS = {
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9",  # Robinhood SOL
    "GJRs4FwHtemZ5ZE9x3FNvJ8TMwitKTh96QfTiX4eLrPt",  # Robinhood SOL 2
    "HWfEc9MXxKANXq3uD2A4sFJEb3k8ZXCVnx1Ah4eXb1R",  # Robinhood SOL 3
}

# Cache untuk trending
TRENDING_CACHE = {"data": None, "ts": 0}
TRENDING_TTL = 300  # 5 menit

def fetch_new_micin(limit=20):
    """Scan newly created micin tokens - GeckoTerminal new pools + DexScreener boosted"""
    tokens = []
    # 1. GeckoTerminal new pools (semua chain) - genuine new tokens
    for net in ["solana", "bsc", "eth", "base"]:
        try:
            r = requests.get(f"https://api.geckoterminal.com/api/v2/networks/{net}/new_pools?page=1",
                           headers=HEADERS, timeout=8)
            if r.status_code == 200:
                for pool in r.json().get("data", [])[:8]:
                    attrs = pool.get("attributes", {})
                    name = attrs.get("name", "")
                    symbol = name.split(" / ")[0] if " / " in name else name[:10]
                    if symbol.upper() in EXCLUDE_SYMBOLS or symbol.upper() in COPYCAT_SYMBOLS:
                        continue
                    try:
                        fdv = float(attrs.get("fdv_usd") or 0)
                    except:
                        fdv = 0
                    # Hanya ambil yang MC < $500k (genuinely new)
                    if fdv > 500000:
                        continue
                    pool_id = pool.get("id", "")
                    pair_addr = pool_id.split("_")[-1] if "_" in pool_id else pool_id
                    # Resolve token address
                    token_addr = pair_addr
                    try:
                        ds = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={symbol}",
                                        headers=HEADERS, timeout=6)
                        if ds.status_code == 200:
                            for pp in (ds.json().get("pairs") or []):
                                if pp.get("chainId") == GECKO_CHAIN_MAP.get(net) and \
                                   pp.get("baseToken",{}).get("symbol","").upper() == symbol.upper():
                                    token_addr = pp.get("baseToken",{}).get("address") or pair_addr
                                    break
                    except:
                        pass
                    key = f"{net}:{token_addr}"
                    if token_addr not in [x["mint"] for x in tokens] and len(tokens) < limit:
                        tokens.append({
                            "mint": token_addr, "chain": net, "symbol": symbol,
                            "name": name, "priceUsd": attrs.get("base_token_price_usd"),
                            "volume24h": None, "liquidity": None, "fdv": fdv,
                            "pairUrl": f"https://www.geckoterminal.com/{net}/pools/{attrs.get('address')}",
                            "source": "new_pool",
                        })
            time.sleep(0.1)
        except:
            continue
    # 2. DexScreener boosted (promoted =有人 bayar promote = whale activity signal)
    try:
        r = requests.get("https://api.dexscreener.com/token-boosts/top/v1", headers=HEADERS, timeout=8)
        if r.status_code == 200:
            for item in r.json()[:15]:
                chain = item.get("chainId", "")
                mint = item.get("tokenAddress", "")
                if not mint or chain in ["robinhood"]:
                    continue  # skip robinhood chain buat sekarang
                # resolve via search
                try:
                    ds = requests.get(f"https://api.dexscreener.com/latest/dex/pairs/{chain}/{mint}",
                                    headers=HEADERS, timeout=6)
                    if ds.status_code == 200:
                        pairs = ds.json().get("pairs") or []
                        for pp in pairs:
                            if pp.get("chainId") == chain:
                                real_mint = pp.get("baseToken",{}).get("address") or mint
                                sym = pp.get("baseToken",{}).get("symbol","")
                                fdv = pp.get("fdv") or pp.get("marketCap") or 0
                                if fdv and fdv < 500000 and sym.upper() not in EXCLUDE_SYMBOLS:
                                    key = f"{chain}:{real_mint}"
                                    if real_mint not in [x["mint"] for x in tokens] and len(tokens) < limit:
                                        tokens.append({
                                            "mint": real_mint, "chain": chain, "symbol": sym,
                                            "name": pp.get("baseToken",{}).get("name",""),
                                            "priceUsd": pp.get("priceUsd"),
                                            "volume24h": pp.get("volume",{}).get("h24"),
                                            "liquidity": pp.get("liquidity",{}).get("usd"),
                                            "fdv": fdv, "pairUrl": pp.get("url",""),
                                            "source": "boosted",
                                        })
                                    break
                except:
                    continue
                time.sleep(0.05)
    except:
        pass
    return tokens


def detect_whale_signal(dex):
    """Deteksi whale accumulation signal dari volume/buy pattern"""
    if not dex:
        return {"signal": False, "strength": 0, "reasons": []}
    
    reasons = []
    strength = 0
    
    txns = dex.get("txns") or {}
    m5 = txns.get("m5") or {}
    h1 = txns.get("h1") or {}
    buys_m5 = m5.get("buys", 0)
    sells_m5 = m5.get("sells", 0)
    buys_h1 = h1.get("buys", 0)
    sells_h1 = h1.get("sells", 0)
    
    vol = dex.get("volume") or {}
    vol_h1 = vol.get("h1", 0) or 0
    vol_h6 = vol.get("h6", 0) or 0
    vol_h24 = vol.get("h24", 0) or 0
    mcap = dex.get("market_cap") or dex.get("fdv") or 1
    
    # 1. Buy pressure: buys >> sells dalam 5 menit
    if buys_m5 > 0 and sells_m5 == 0:
        strength += 30
        reasons.append("zero sells in 5m (pure accumulation)")
    elif buys_m5 > sells_m5 * 2 and buys_m5 >= 3:
        strength += 20
        reasons.append("buy pressure " + str(buys_m5) + ":" + str(sells_m5))
    
    # 2. Volume spike: vol h1 > rata-rata h6
    if vol_h6 > 0 and vol_h1 > 0:
        avg_h = vol_h6 / 6
        if avg_h > 0 and vol_h1 > avg_h * 1.5:
            strength += 25
            reasons.append("vol spike " + str(round(vol_h1/avg_h, 1)) + "x avg")
    
    # 3. Vol/Mcap ratio tinggi (volume organik)
    vol_mcap = (vol_h24 / mcap * 100) if mcap and vol_h24 else 0
    if vol_mcap > 10:
        strength += 15
        reasons.append("vol/mcap " + str(round(vol_mcap, 1)) + "%")
    
    # 4. Price naik (priceChange h1 > 5%)
    pc = dex.get("priceChange") or {}
    h1_chg = pc.get("h1", 0) or 0
    if h1_chg > 10:
        strength += 15
        reasons.append("+" + str(round(h1_chg, 1)) + "% h1")
    elif h1_chg > 5:
        strength += 10
        reasons.append("+" + str(round(h1_chg, 1)) + "% h1")
    
    # 5. Micro cap + liquidity ratio bagus
    liq = dex.get("total_liquidity_usd") or dex.get("liquidity") or 0
    if mcap and liq:
        liq_ratio = liq / mcap * 100
        if 5 < liq_ratio < 30:
            strength += 10
            reasons.append("liq/mcap " + str(round(liq_ratio, 1)) + "%")
    
    signal = strength >= 25
    return {"signal": signal, "strength": strength, "reasons": reasons}


def detect_whale_wallet_activity(mint, chain="solana"):
    """Cek apakah known whale wallet baru beli token ini"""
    if chain != "solana":
        return False
    try:
        # DexScreener: cek recent trades / makers
        r = requests.get(f"https://api.dexscreener.com/latest/dex/pairs/solana/{mint}",
                        headers=HEADERS, timeout=6)
        if r.status_code == 200:
            pairs = r.json().get("pairs") or []
            for p in pairs:
                info = p.get("info") or {}
                makers = info.get("makers") or []
                for m in makers:
                    if m.get("address") in KNOWN_WHALE_WALLETS:
                        return True
    except:
        pass
    return False


def fetch_trending_solana(limit=15, beyond_trending=False):
    """Ambil trending + new micin dari DexScreener + Pump.fun (all-chain). beyond_trending=True = scan new pump.fun juga"""
    # cache key beda untuk beyond
    cache_key = f"beyond_{limit}" if beyond_trending else f"trending_{limit}"
    now = time.time()
    # simple cache per limit+mode
    if TRENDING_CACHE["data"] and now - TRENDING_CACHE["ts"] < TRENDING_TTL and TRENDING_CACHE.get("key") == cache_key:
        return TRENDING_CACHE["data"]
    
    tokens = []
    # 0. GeckoTerminal Top Volume (BNC4, 4Stock, quq kayak di screenshot Top Volume)
    try:
        for net in ["bsc", "solana", "eth", "base"]:
            try:
                r = requests.get(f"https://api.geckoterminal.com/api/v2/networks/{net}/trending_pools", headers=HEADERS, timeout=8)
                if r.status_code == 200:
                    j = r.json()
                    for pool in j.get("data", [])[:5]:
                        attrs = pool.get("attributes", {})
                        name = attrs.get("name", "")
                        symbol = name.split(" / ")[0] if " / " in name else name[:10]
                        if symbol.upper() in EXCLUDE_SYMBOLS:
                            continue
                        try:
                            fdv = float(attrs.get("fdv_usd") or attrs.get("market_cap_usd") or 0)
                        except:
                            fdv = 0
                        pool_id = pool.get("id", "")
                        pair_addr = pool_id.split("_")[-1] if "_" in pool_id else pool_id
                        chain = net
                        key = f"{chain}:{pair_addr}"
                        if pair_addr and key not in [f"{x['chain']}:{x['mint']}" for x in tokens] and len(tokens) < limit:
                            # Resolve token address via DexScreener search (Gecko kasih pair addr, bukan token addr)
                            token_addr = pair_addr
                            try:
                                ds = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={symbol}", headers=HEADERS, timeout=6)
                                if ds.status_code == 200:
                                    dp = ds.json().get("pairs") or []
                                    # cari yang chain match & symbol match
                                    for pp in dp:
                                        if pp.get("chainId") == chain and pp.get("baseToken",{}).get("symbol","").upper() == symbol.upper():
                                            token_addr = pp.get("baseToken",{}).get("address") or pair_addr
                                            break
                            except:
                                pass
                            tokens.append({
                                "mint": token_addr,
                                "chain": chain,
                                "symbol": symbol,
                                "name": name,
                                "priceUsd": attrs.get("base_token_price_usd"),
                                "volume24h": None,
                                "liquidity": None,
                                "fdv": fdv,
                                "pairUrl": f"https://www.geckoterminal.com/{net}/pools/{attrs.get('address')}",
                                "is_gecko": True,
                            })
            except:
                continue
    except:
        pass
    # 0. GeckoTerminal trending All-Chain (real trending kayak di screenshot BNC4, 4Stock)
    try:
        for net in ["solana", "bsc", "eth", "base"]:
            try:
                r = requests.get(f"https://api.geckoterminal.com/api/v2/networks/{net}/trending_pools", headers=HEADERS, timeout=8)
                if r.status_code == 200:
                    j = r.json()
                    for pool in j.get("data", [])[:8]:
                        attrs = pool.get("attributes", {})
                        # ambil base token dari pool id
                        pool_id = pool.get("id", "")
                        # Gecko pool id format: solana_0x... or bsc_0x...
                        # Untuk simplicity, ambil symbol dari name
                        name = attrs.get("name", "")
                        symbol = name.split(" / ")[0] if " / " in name else name[:8]
                        if symbol.upper() in EXCLUDE_SYMBOLS or symbol.upper() in COPYCAT_SYMBOLS:
                            continue
                        # fdv/mcap
                        try:
                            fdv = float(attrs.get("fdv_usd") or attrs.get("market_cap_usd") or 0)
                        except:
                            fdv = 0
                        if fdv and fdv < 500000:
                            continue
                        pair_addr = pool_id.split("_")[-1] if "_" in pool_id else pool_id
                        chain = net
                        key = f"{chain}:{pair_addr}"
                        if pair_addr and key not in [f"{x['chain']}:{x['mint']}" for x in tokens] and len(tokens) < limit:
                            token_addr = pair_addr
                            try:
                                ds = requests.get(f"https://api.dexscreener.com/latest/dex/search?q={symbol}", headers=HEADERS, timeout=6)
                                if ds.status_code == 200:
                                    dp = ds.json().get("pairs") or []
                                    for pp in dp:
                                        if pp.get("chainId") == chain and pp.get("baseToken",{}).get("symbol","").upper() == symbol.upper():
                                            token_addr = pp.get("baseToken",{}).get("address") or pair_addr
                                            break
                            except:
                                pass
                            tokens.append({
                                "mint": token_addr,
                                "chain": chain,
                                "symbol": symbol,
                                "name": name,
                                "priceUsd": attrs.get("base_token_price_usd"),
                                "volume24h": None,
                                "liquidity": None,
                                "fdv": fdv,
                                "pairUrl": f"https://www.geckoterminal.com/{net}/pools/{attrs.get('address')}",
                            })
            except:
                continue
    except:
        pass
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
            # skip copycat semua chain - PEPE/DOGE copy dimana-mana, bukan micin beneran
            if symbol in COPYCAT_SYMBOLS:
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
                if symbol in EXCLUDE_SYMBOLS or symbol in COPYCAT_SYMBOLS:
                    # untuk pump trending, skip copycat juga kalau holder sepi
                    # cek holder via c.get("reply_count")? Skip aja
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

    # 3. Beyond trending: scan NEW micin dari GeckoTerminal new pools + DexScreener boosted
    if beyond_trending:
        new_tokens = fetch_new_micin(limit=limit)
        for nt in new_tokens:
            key = f"{nt['chain']}:{nt['mint']}"
            if key not in [f"{x['chain']}:{x['mint']}" for x in tokens] and len(tokens) < limit:
                tokens.append(nt)

    TRENDING_CACHE["data"] = tokens
    TRENDING_CACHE["ts"] = now
    TRENDING_CACHE["key"] = cache_key
    return tokens

def is_bagger_candidate(dex, rug, social, durability_score, relaxed=False):
    """Cek apakah token potensi bagger - support bonding progress filter user: new bonding >=15% mc<=10k, bonding radar 35-99% mc>=10k, momentum mc>=10k+vol"""
    # threshold
    mcap_max = 100_000_000 if relaxed else 50_000_000
    durability_min = 45 if relaxed else 55
    social_min = 50 if relaxed else 65
    top10_max = 40 if relaxed else 35
    vol_ratio_min = 5 if relaxed else 10
    holders_min = 300 if relaxed else 500

    # --- Bonding progress filter (Pump.fun) ---
    # Jika token adalah pump.fun (cek via pairUrl atau dexId), hitung progress dari fdv/liq
    # progress = (fdv / 60000) *100? Atau dari liquidity: progress = liq_usd / (85*SOL_price) *100
    # Untuk sekarang, coba ambil progress dari dex data jika ada field 'progress', else estimasi
    bonding_progress = None
    try:
        # DexScreener kadang kasih fdv, mcap, liq - untuk pump.fun, fdv ~ mcap saat bonding
        mcap_for_bonding = dex.get("market_cap") or dex.get("fdv") or 0
        # Estimasi progress: mcap 60k = 100% (graduation), jadi progress = mcap/60000*100 capped 100
        if mcap_for_bonding and mcap_for_bonding < 100000:
            bonding_progress = min(99, (mcap_for_bonding / 60000 * 100))
            # Jika ada liq, cross-check: progress dari liq
            liq_usd = dex.get("total_liquidity_usd") or 0
            if liq_usd and mcap_for_bonding:
                # SOL price ~150, 85 SOL = 12750 USD, progress liq = liq / 12750 *100
                sol_price = 150  # fallback, bisa fetch live
                try:
                    import requests
                    r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=solana&vs_currencies=usd", timeout=3)
                    if r.status_code == 200:
                        sol_price = r.json().get("solana", {}).get("usd", 150)
                except:
                    pass
                progress_liq = min(99, (liq_usd / (85 * sol_price) * 100)) if sol_price else bonding_progress
                # ambil max dari dua estimasi
                bonding_progress = max(bonding_progress, progress_liq)
    except:
        pass
    if not dex:
        return False, "data tidak lengkap"
    
    mcap = dex.get("market_cap") or dex.get("fdv") or 0
    liq = dex.get("total_liquidity_usd") or 0
    holders = rug.get("total_holders") or 0 if rug else 0
    top10 = rug.get("top10_pct") or 0 if rug else 0
    vol = dex.get("total_vol_24h") or 0
    liq_ratio = (liq / mcap * 100) if mcap else 0
    vol_ratio = (vol / mcap * 100) if mcap else 0
    social_score = social.get("score", 50) if social else 50

    reasons = []
    is_bagger = True

    # --- Bonding filter user: new bonding / radar / momentum ---
    # Jika bonding_progress terdeteksi (pump.fun), pakai kriteria bonding
    if bonding_progress is not None:
        mc_val = mcap  # untuk pump.fun, mcap = fdv
        if bonding_progress >= 15 and mc_val <= 10000:
            # new bonding - lolos langsung sebagai bagger early
            reasons.append(f"new bonding progress {bonding_progress:.1f}% mc ${mc_val:,.0f} (≥15% & ≤10k) - EARLY")
            # jangan fail di mcap/holder checks di bawah untuk early, tapi tetap cek whale/durability
            # skip mcap/holder strict untuk early
            pass
        elif 35 <= bonding_progress <= 99 and mc_val >= 10000:
            reasons.append(f"bonding radar {bonding_progress:.1f}% mc ${mc_val:,.0f} (35-99% & ≥10k)")
            pass
        elif mc_val >= 10000 and vol > 50000:
            reasons.append(f"momentum mc ${mc_val:,.0f} vol ${vol:,.0f} (≥10k + gerak)")
            pass
        else:
            # jika bonding progress ada tapi tidak masuk kriteria, tetap lanjut cek strict
            pass
        # Untuk bonding, mcap check pakai mc_val bukan mcap_max strict
        if mc_val < 500_000 and mc_val > 10000:
            # untuk bonding, mcap kecil masih ok asal progress sesuai
            pass
        elif mc_val < 500_000 and bonding_progress is None:
            is_bagger = False
            reasons.append(f"mcap terlalu kecil ${mc_val:,.0f} (<500k) - risiko scam")
        elif mc_val > mcap_max and bonding_progress is None:
            is_bagger = False
            reasons.append(f"mcap besar ${mc_val:,.0f} (>{mcap_max/1_000_000:.0f}M) - sudah bukan micin bagger")
        # skip strict mcap check for bonding - already handled
    else:
        # Market cap 0.5M - 50M (100M kalau relaxed) untuk non-bonding
        if mcap < 500_000:
            is_bagger = False
            reasons.append(f"mcap terlalu kecil ${mcap:,.0f} (<500k) - risiko scam")
        elif mcap > mcap_max:
            is_bagger = False
            reasons.append(f"mcap besar ${mcap:,.0f} (>{mcap_max/1_000_000:.0f}M) - sudah bukan micin bagger")

    # Liquidity
    if liq < 1000:
        is_bagger = False
        reasons.append(f"liq tipis ${liq:,.0f} (<50k)")
    if liq_ratio < 2:
        is_bagger = False
        reasons.append(f"liq/mcap {liq_ratio:.2f}% (<2%) MCAP illusion")

    # Holders - untuk bonding new, holder 25 pun ok (early)
    # Jika bonding new (progress 15-35% & mc <=10k), holder 10+ aja cukup
    is_new_bonding = bonding_progress is not None and bonding_progress >= 15 and (dex.get("market_cap") or dex.get("fdv") or 0) <= 10000
    if is_new_bonding:
        if holders < 10:
            is_bagger = False
            reasons.append(f"holders {holders} (<10) terlalu sepi untuk new bonding")
        # top10 untuk new bonding boleh 100% (belum distribusi)
        if top10 > 100:
            is_bagger = False
            reasons.append(f"top10 {top10:.1f}% (>95%) whale risk untuk new bonding")
    else:
        if holders < holders_min:
            is_bagger = False
            reasons.append(f"holders {holders} (<{holders_min}) terlalu sepi")
        elif holders > 50000:
            reasons.append(f"holders {holders} (>50k) ramai - bagger potensi menipis")
        if top10 > top10_max:
            is_bagger = False
            reasons.append(f"top10 {top10:.1f}% (>{top10_max}%) whale risk")

    # Volume - untuk new bonding, vol kecil masih ok asal ada gerak
    if is_new_bonding:
        if vol < 1000:
            is_bagger = False
            reasons.append(f"vol 24h ${vol:,.0f} (<1k) sepi untuk new bonding")
    else:
        if vol < 100_000:
            is_bagger = False
            reasons.append(f"vol 24h ${vol:,.0f} (<100k) sepi")
        if vol_ratio < vol_ratio_min:
            is_bagger = False
            reasons.append(f"vol/mcap {vol_ratio:.1f}% (<{vol_ratio_min}%) kurang aktif")
    if vol_ratio > 50:
        reasons.append(f"vol/mcap {vol_ratio:.1f}% (>50%) wash curiga")

    # Durability - untuk new bonding, durability 15 pun ok (baru bonding)
    if is_new_bonding:
        if durability_score < 10:
            is_bagger = False
            reasons.append(f"durability {durability_score} (<10) struktur lemah untuk new bonding")
        if social_score < 20:
            is_bagger = False
            reasons.append(f"social {social_score} (<20) belum ada gerak untuk new bonding")
    else:
        if durability_score < durability_min:
            is_bagger = False
            reasons.append(f"durability {durability_score} (<{durability_min}) struktur lemah")
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
