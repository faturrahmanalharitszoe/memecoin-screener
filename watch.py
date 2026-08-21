#!/usr/bin/env python3
"""
Watcher sederhana - monitor WIF/BONK tiap interval, log attribution
Usage: py watch.py --mints EKpQGSJ...,DezXAZ8... --interval 300
Free stack tetap, tanpa API key
"""
import argparse
import time
import subprocess
import sys

def watch(mints, interval):
    print(f"[WATCH] Monitoring {mints} tiap {interval}s - Ctrl+C untuk stop")
    while True:
        for mint in mints:
            print(f"\n{'='*20} CHECK {mint[:8]} {time.strftime('%H:%M:%S')} {'='*20}")
            subprocess.run([sys.executable, "meme_screener.py", "--mint", mint, "--snapshot"])
        print(f"\n[WATCH] Sleep {interval}s...")
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n[WATCH] Stopped")
            break

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--mints", default="EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm,DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263", help="comma separated mints")
    p.add_argument("--interval", type=int, default=300, help="seconds")
    args = p.parse_args()
    watch([m.strip() for m in args.mints.split(",")], args.interval)
