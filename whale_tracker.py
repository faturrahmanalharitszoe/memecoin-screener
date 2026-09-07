"""
Whale Tracker - untuk micin bagger + Robinhood whales
"""
import requests
import time

HEADERS = {"User-Agent": "meme-screener-whale/1.0"}

# Robinhood known wallets (public Arkham)
ROBINHOOD_WALLETS = {
    "BTC": ["3D2oLMp5BmY6uC8uC8uC8uC8uC8uC8uC8uC8uC8"],  # placeholder - real: 3D2o... is example
    "DOGE": ["DH5yaieqoZN36fDVciNyRueRG4D5aCb7"],  # Robinhood DOGE cold
    "SHIB": ["0x..."],  # Robinhood SHIB
    "SOL": ["..."],  # Robinhood SOL hot wallet (need real address from Arkham)
}

# Known Solana whale wallets for meme coins (from Birdeye/Arkham)
SOLANA_WHALE_WALLETS = {
    "WIF": ["9HSgJUDbGigu6Qj1ya1yuwGqg8CAatEMra8sWwDRA7rH"],  # top holder
}

def get_robinhood_wallets():
    """Return known Robinhood wallets - bisa diupdate via Arkham API"""
    # Untuk sekarang hardcode, nanti bisa fetch dari Arkham: https://api.arkhamintelligence.com/intelligence/address/{addr}
    return ROBINHOOD_WALLETS

def fetch_whale_transactions(mint, holder_address, limit=10):
    """Fetch recent tx untuk holder via Helius/RPC (free fallback ke SolScan)"""
    # Try Helius first if key exists
    import os
    helius_key = os.getenv("HELIUS_API_KEY", "").strip()
    if helius_key:
        try:
            url = f"https://api.helius.xyz/v0/addresses/{holder_address}/transactions?api-key={helius_key}"
            r = requests.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                return r.json()[:limit]
        except:
            pass
    # Fallback: SolScan API (public, kadang 404)
    try:
        url = f"https://public-api.solscan.io/account/transactions?account={holder_address}&limit={limit}"
        r = requests.get(url, headers=HEADERS, timeout=10)
        if r.status_code == 200:
            return r.json()[:limit]
    except:
        pass
    return []

def analyze_whale_flow(top_holders, dex_price=None):
    """Analisa whale flow: apakah akumulasi atau distribusi"""
    if not top_holders:
        return {"signal": "NEUTRAL", "details": "no holder data"}
    
    top10_pct = sum(h.get("pct", 0) for h in top_holders[:10])
    # Simple heuristic: jika top10 <30% dan holder banyak = distribusi sehat
    # Jika top10 naik vs snapshot sebelumnya = akumulasi whale
    # Untuk sekarang, cek konsentrasi
    if top10_pct > 50:
        return {"signal": "DISTRIBUTION_RISK", "details": f"top10 {top10_pct:.1f}% sangat terkonsentrasi, 1 whale bisa dump"}
    elif top10_pct > 35:
        return {"signal": "WHALE_RISK", "details": f"top10 {top10_pct:.1f}% >35% - waspada"}
    elif top10_pct < 20:
        return {"signal": "HEALTHY", "details": f"top10 {top10_pct:.1f}% distribusi sehat"}
    else:
        return {"signal": "NEUTRAL", "details": f"top10 {top10_pct:.1f}% normal"}

def get_bagger_whales(mint, top_holders):
    """Untuk bagger, return whale wallets yang perlu di-track"""
    # Filter top holders yang >2% supply - ini whale yang gerakannya ngaruh
    whales = [h for h in top_holders if h.get("pct", 0) > 2]
    # Sort by pct desc
    whales = sorted(whales, key=lambda x: x["pct"], reverse=True)[:5]
    result = []
    for w in whales:
        addr = w.get("address") or w.get("account") or ""
        result.append({
            "address": addr,
            "pct": w.get("pct"),
            "balance": w.get("balance") or w.get("amount"),
            "is_robinhood": addr in [a for lst in ROBINHOOD_WALLETS.values() for a in lst],
        })
    return result
