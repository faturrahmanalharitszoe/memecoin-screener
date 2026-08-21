# Meme Screener Solana - Free Stack + Dashboard

**Stack 100% Gratis - No API Key Required**
- DexScreener API (price, liquidity, volume, txns)
- RugCheck API (holder distribution, whale concentration, risks)
- CoinGecko Free API (BTC/SOL context + CEX volume + community)
- **Dashboard** `dashboard_app.py` (Flask + Tailwind + Chart.js) + **Social Velocity** (Tx proxy + CoinGecko + LunarCrush optional)

> **WIF di Solana? Ya.** Mint `EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm` native Solana SPL, pair WIF/SOL Raydium.

## Kenapa WIF di Solana?
Jawaban: **Ya, WIF (dogwifhat) native di Solana.**
- Mint: `EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm`
- Chain: Solana SPL Token
- Pair utama: WIF/SOL di Raydium (EP2ib6...), likuid di Binance/Bybit juga (CEX volume $81M/hari)
- BONK juga Solana: `DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263`

## Install
```bash
pip install -r requirements.txt
```

## Dashboard (Baru)
```bash
py dashboard_app.py
# Buka http://localhost:5001
# API: http://localhost:5001/api/screen/<mint>
```
Fitur dashboard:
- Input mint + preset WIF/BONK/RAY
- Durability Score 0-100 dengan gauge + flags + reasons
- Price & Market (price, MCAP, liq, vol, chart h5/h1/h6/h24)
- Attribution Engine (BTC_BETA_AMPLIFIED, SENTIMENT_FOMO, WHALE, LPI, dll + BTC/SOL context)
- Holder & Whale (holders, Top5/10, bar, risks, mint/freeze, insider)
- **Social Velocity** (score 0-100, buy ratio, tx 24h, vol velocity, Telegram/Twitter, LunarCrush jika ada key, chart tx)
- Whale Cabut Detector (snapshot, delta top10)
- Auto refresh 60s, snapshot button

Social velocity detail:
- **Tanpa API key**: pakai Tx proxy (DexScreener buys/sells, volume momentum) + CoinGecko community (Telegram members, twitter handle). Skor 85 = VIRAL, 60+ = ACCELERATING.
- **Dengan LunarCrush key**: set `LUNARCRUSH_API_KEY` di env atau `.env`, maka fetch real `social_volume`, `social_score`, `galaxy_score` (lihat `.env.example`).

## CLI Usage

### 1. Screening Single Token
```bash
py meme_screener.py --mint EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm --explain --snapshot
py meme_screener.py --mint DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 --explain
py meme_screener.py --mint <PUMP_FUN_MINT> --explain
```

### 2. Output yang Dihasilkan
- **Durability Score 0-100** (framework 4 pilar)
  - Holder distribution
  - Whale concentration (Top5 >20% / Top10 >30% = red flag)
  - Liquidity/MCAP ratio (MCAP illusion detector)
  - Rug risks (mint/freeze, honeypot)
- **Attribution Engine** (kenapa naik/turun):
  - `BTC_BETA_AMPLIFIED` - meme naik lebih kencang dari BTC (rotasi risk-on)
  - `BTC_CORRELATED` - ikut BTC
  - `SENTIMENT_FOMO` - buy ratio >65%
  - `SELL_PRESSURE` - buy ratio <35%
  - `LOW_LIQUIDITY_AMPLIFICATION` - LPI wash trading (median $54 bisa +500%)
  - `WHALE_DISTRIBUTION_SUSPECTED`
  - `SUSPECTED_MANIPULATION` (82.8% high-return coin manipulatif)
  - `SIDEWAYS_NO_CATALYST`
- **Whale Cabut Detector**: pakai `--snapshot` untuk simpan state dan bandingkan top10 next run. Alert jika top10 turun >2ppt.

### 3. Contoh Hasil Real 2026-08-21

**WIF - 95/100 AMAN**
```
MCAP $185M, Liq DEX $5.2M, Vol CEX $81M, Holders 772k, Top10 44% [DISKON CEX]
Attribution: BTC_BETA_AMPLIFIED (BTC +8.2% -> WIF +19% = 2.3x beta)
```
-> Naik karena BTC pump + rotasi ke meme, bukan sentimen murni. Aman di-hold tapi whale risk tetap ada.

**BONK - 41/100 BERBAHAYA**
```
Holders 2M, Top10 38%, Risks: LP Vault unlocked, Mutable metadata
Attribution: BTC_CORRELATED (BTC +8% -> BONK +10%)
```
-> Score rendah karena RugCheck flag vault unlocked (banyak pool Meteora DLMM). Secara komunitas kuat tapi struktur on-chain flag.

**PUMP Copycat (9593dF...) - 16/100 EXTREME RISK**
```
Holders 39, Top10 100%, Vol $305k
```
-> Contoh 95% token yang mati <90 hari. Skip.

## Framework Scoring Detail
Lihat `meme_screener.py:calculate_durability()` line 185
- Holder <500: -20
- Top10 >30%: -20 (diskon 5 jika large cap CEX-listed)
- MCAP illusion (liq/mcap <0.05%): -25
- Volume <50k: -15
- Rug risk per flag: -8 (max -25)
- Insider network >100: -15 (kecuali score RugCheck aman)

## Snapshot & Monitoring
```bash
# Run pertama simpan baseline
py meme_screener.py --mint EKpQGSJ... --snapshot
# Run besok bandingkan - deteksi whale cabut
py meme_screener.py --mint EKpQGSJ... --snapshot
```

File snapshot tersimpan di `snapshots/<mint8>.json`

## Keterbatasan Free Stack
- Social momentum (X/Telegram velocity) belum included - butuh LunarCrush API key (gratis tier 100 req/hari) atau scraping. Proxy sekarang pakai Tx buy/sell ratio.
- Whale flow histori butuh cron snapshot harian - sudah ada fitur snapshot tapi belum auto.
- Untuk token kecil, DEX data akurat. Untuk large cap, pakai CoinGecko override biar MCAP tidak ngawur.

## Next Step (Opsional Berbayar/Tingkat Lanjut)
- Tambah LunarCrush/Birdeye untuk social velocity & holder timeline
- Auto watcher `watch.py` dengan Telegram alert
- Dashboard web (Next.js) untuk portfolio tracking

## File
- `meme_screener.py` - core engine
- `snapshots/` - storage whale snapshot
- `requirements.txt`
