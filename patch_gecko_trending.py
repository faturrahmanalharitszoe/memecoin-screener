import pathlib
p = pathlib.Path(r'C:\Personal Project\meme-screener-solana\bagger.py')
t = p.read_text(encoding='utf-8')
old = """    # 1. DexScreener trending All-Chain (Solana, ETH, BSC, Base, Robinhood chain)
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
            symbol = (p.get("baseToken", {}).get("symbol") or "").upper()
            # skip stable/large cap
            if symbol in EXCLUDE_SYMBOLS:
                continue
            # skip copycat Solana semua - DOGE/PEPE di Solana itu copyan, bukan micin
            if symbol in COPYCAT_SYMBOLS and chain == "solana":
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
                })"""
new = """    # 1. GeckoTerminal trending All-Chain (real trending kayak di screenshot lu) + DexScreener fallback
    try:
        # GeckoTerminal trending pools - ini yang lu lihat di screenshot (BNC4, 4Stock, quq, WETH etc.)
        gecko_networks = ["solana", "bsc", "eth", "base", "polygon", "arbitrum"]
        all_gecko_pools = []
        for net in gecko_networks:
            try:
                r = requests.get(f"https://api.geckoterminal.com/api/v2/networks/{net}/trending_pools", headers=HEADERS, timeout=8)
                if r.status_code == 200:
                    j = r.json()
                    for pool in j.get("data", [])[:10]:
                        attrs = pool.get("attributes", {})
                        # ambil base token dari pool name (e.g., "4Stock / USDT" -> 4Stock)
                        name = attrs.get("name", "")
                        symbol = name.split(" / ")[0] if " / " in name else name[:10]
                        # mcap/fdv dari pool
                        fdv = float(attrs.get("fdv_usd") or attrs.get("market_cap_usd") or 0)
                        # filter mcap 0.5M-100M untuk micin
                        if fdv and (fdv < 500000 or fdv > 100000000):
                            # skip yang terlalu kecil atau terlalu besar untuk trending micin, tapi tetap ambil kalau beyond
                            pass
                        all_gecko_pools.append({
                            "mint": pool.get("id", "").split("_")[-1] if "_" in pool.get("id","") else pool.get("id"),
                            "chain": net,
                            "symbol": symbol,
                            "name": name,
                            "priceUsd": attrs.get("base_token_price_usd"),
                            "volume24h": None,  # Gecko volume ada di transactions, tapi kita ambil dari DexScreener nanti
                            "liquidity": None,
                            "fdv": fdv,
                            "pairUrl": f"https://www.geckoterminal.com/{net}/pools/{attrs.get('address')}",
                            "pool_address": attrs.get("address"),
                        })
            except:
                continue
        # Jika Gecko dapet, pakai itu
        if all_gecko_pools:
            seen = set()
            for p in all_gecko_pools:
                key = f"{p['chain']}:{p['mint']}"
                if p["mint"] and key not in seen and len(tokens) < limit:
                    seen.add(key)
                    # skip stable
                    if p["symbol"].upper() in EXCLUDE_SYMBOLS:
                        continue
                    if p["symbol"].upper() in COPYCAT_SYMBOLS and p["chain"] == "solana":
                        # untuk Gecko, copycat Solana juga skip
                        # cek fdv
                        try:
                            fdv_f = float(p["fdv"] or 0)
                            if fdv_f < 5000000:
                                continue
                        except:
                            pass
                    tokens.append(p)
        # Fallback DexScreener kalau Gecko kosong
        if not tokens:
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
            seen = set()
            for p in sorted(all_pairs, key=lambda x: (x.get("volume", {}).get("h24") or 0), reverse=True):
                mint = p.get("baseToken", {}).get("address")
                chain = p.get("chainId")
                symbol = (p.get("baseToken", {}).get("symbol") or "").upper()
                if symbol in EXCLUDE_SYMBOLS:
                    continue
                if symbol in COPYCAT_SYMBOLS and chain == "solana":
                    try:
                        fdv_f = float(p.get("fdv") or 0)
                        if fdv_f < 5000000:
                            continue
                    except:
                        pass
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
                    })"""
if old in t:
    t = t.replace(old, new)
    p.write_text(t, encoding='utf-8')
    print('updated to GeckoTerminal trending')
else:
    print('not found dex trending')
