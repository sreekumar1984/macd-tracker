import csv
import json
import os
import requests

WATCHLIST_PATH = "/Users/sree/macd_momentum_tracker/watchlist.json"

def fetch_and_initialize_fo_list():
    # We fetch it fresh every time or load if exists and force_fresh is False
    # For this task, we want to fetch the complete F&O list dynamically.
    url = "https://api.kite.trade/instruments"
    print(f"Fetching complete F&O list from Kite API: {url}...")
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            lines = resp.text.splitlines()
            reader = csv.reader(lines)
            headers = next(reader)
            
            exchange_idx = headers.index('exchange')
            name_idx = headers.index('name')
            type_idx = headers.index('instrument_type')
            
            symbols = set()
            for row in reader:
                if len(row) > max(exchange_idx, name_idx, type_idx):
                    exchange = row[exchange_idx].strip()
                    inst_type = row[type_idx].strip()
                    name = row[name_idx].strip()
                    
                    if exchange == "NFO" and inst_type == "FUT" and name:
                        # Format for TradingView (replace hyphens with underscores)
                        formatted_name = name.replace("-", "_")
                        symbols.add(f"NSE:{formatted_name}")
            
            tv_symbols = sorted(list(symbols))
            
            # Write to watchlist.json
            with open(WATCHLIST_PATH, "w") as f:
                json.dump(tv_symbols, f, indent=2)
                
            print(f"Successfully loaded and saved {len(tv_symbols)} F&O symbols to {WATCHLIST_PATH}.")
            return tv_symbols
        else:
            print(f"Failed to fetch from Kite: Status Code {resp.status_code}. Using fallback list...")
            return use_fallback_list()
    except Exception as e:
        print(f"Error fetching from Kite API: {e}. Using fallback list...")
        return use_fallback_list()

def use_fallback_list():
    # A robust fallback list of top NSE F&O stocks in case of network issues
    fallback = [
        "NSE:TRENT", "NSE:RELIANCE", "NSE:TCS", "NSE:INFY", "NSE:HDFCBANK", 
        "NSE:ICICIBANK", "NSE:SBIN", "NSE:BHARTIARTL", "NSE:ITC", "NSE:LTIM",
        "NSE:TATAMOTORS", "NSE:KOTAKBANK", "NSE:AXISBANK", "NSE:LT", "NSE:BAJFINANCE",
        "NSE:MARUTI", "NSE:SUNPHARMA", "NSE:HINDUNILVR", "NSE:ADANIENT", "NSE:NIFTY",
        "NSE:BANKNIFTY", "NSE:FINNIFTY"
    ]
    with open(WATCHLIST_PATH, "w") as f:
        json.dump(fallback, f, indent=2)
    print(f"Saved fallback watchlist of {len(fallback)} major symbols.")
    return fallback

if __name__ == "__main__":
    fetch_and_initialize_fo_list()
