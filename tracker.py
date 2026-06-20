import asyncio
import json
import os
import sys
import time
import threading
from datetime import datetime, time as datetime_time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import requests

# Import local modules
import db_manager
import watchlist_manager
import analyzer
import bhavcopy_scraper

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LAST_EOD_RUN_DATE = None
WATCHLIST = []
DB_WRITE_LOCK = threading.Lock()

# Global cache for latest OI data
LATEST_OI_CACHE = {}
LAST_OI_FETCH_DATE = None

def refresh_oi_cache():
    global LATEST_OI_CACHE, LAST_OI_FETCH_DATE
    print("  📡 Fetching latest F&O Bhavcopy for OI details...")
    try:
        date_str, metrics = bhavcopy_scraper.get_latest_oi_data()
        if date_str and metrics:
            LATEST_OI_CACHE = metrics
            LAST_OI_FETCH_DATE = date_str
            print(f"  ✅ OI Cache refreshed successfully for trading date: {date_str}. Loaded {len(metrics)} symbols.")
            return True
        else:
            print("  ⚠️ Could not fetch latest OI details. Retrying on next poll.")
            return False
    except Exception as e:
        print(f"  ⚠️ Error refreshing OI cache: {e}")
        return False

def is_market_hours():
    now = datetime.now()
    # 5 = Saturday, 6 = Sunday
    if now.weekday() >= 5:
        return False
    
    current_time = now.time()
    # Market open at 9:15 AM and close at 3:30 PM (15:30)
    return datetime_time(9, 15) <= current_time <= datetime_time(15, 30)

def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config.json: {e}")
    return {"poll_interval_minutes": 2.0, "database_path": "db/macd_history.db", "momentum_threshold": 5.0, "min_macd_increase_alert": 0.2}

class TrackerWebHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def send_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path in ('/', '/dashboard', '/alerts_dashboard.html'):
            self.send_response(200)
            self.send_header('Content-Type', 'text/html')
            self.send_cors_headers()
            self.end_headers()
            dashboard_file = os.path.join(BASE_DIR, "alerts_dashboard.html")
            if os.path.exists(dashboard_file):
                with open(dashboard_file, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.wfile.write(b"<h1>Dashboard is generating. Please refresh in 5 seconds...</h1>")
        elif parsed.path == '/config':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_cors_headers()
            self.end_headers()
            with open(CONFIG_PATH, "rb") as f:
                self.wfile.write(f.read())
        else:
            self.send_response(404)
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(b"Page not found")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == '/config':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                new_config = json.loads(post_data.decode('utf-8'))
                old_config = {}
                if os.path.exists(CONFIG_PATH):
                    with open(CONFIG_PATH, "r") as f:
                        old_config = json.load(f)
                old_config.update(new_config)
                
                with open(CONFIG_PATH, "w") as f:
                    json.dump(old_config, f, indent=2)
                    
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "saved"}).encode('utf-8'))
                print("  ⚙️ Config dynamically updated from dashboard Web UI.")
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        elif parsed.path == '/force_fetch':
            try:
                global WATCHLIST
                if not WATCHLIST:
                    from watchlist_manager import WATCHLIST_PATH
                    if os.path.exists(WATCHLIST_PATH):
                        with open(WATCHLIST_PATH, "r") as f:
                            WATCHLIST = json.load(f)
                    else:
                        WATCHLIST = watchlist_manager.fetch_and_initialize_fo_list()
                
                print("⚡ [Web Request] Force fetch triggered via Web Dashboard.")
                poll_and_save(WATCHLIST, force=True)
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "message": "Force fetch completed successfully"}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self.send_cors_headers()
            self.end_headers()

def run_web_server():
    server_address = ('', 8080)
    try:
        httpd = HTTPServer(server_address, TrackerWebHandler)
        print("🚀 Dashboard Web Server running on http://localhost:8080/")
        httpd.serve_forever()
    except Exception as e:
        print(f"  ⚠️ Error starting web server: {e}")

def chunk_list(lst, n):
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def query_tradingview_batch(symbols):
    url = "https://scanner.tradingview.com/india/scan"
    payload = {
        "symbols": {
            "tickers": symbols
        },
        "columns": [
            "close",
            "change",
            "MACD.macd|15",
            "MACD.signal|15",
            "RSI|15",
            "volume",
            "average_volume",
            "RSI|30",
            "RSI|60",
            "MACD.macd",
            "MACD.signal",
            "RSI"
        ]
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=15)
        if response.status_code == 200:
            return response.json().get("data", [])
        else:
            print(f"  ⚠️ TradingView API returned status code {response.status_code}: {response.text[:200]}")
            return []
    except Exception as e:
        print(f"  ⚠️ Exception querying TradingView batch: {e}")
        return []

def poll_and_save(watchlist, force=False):
    with DB_WRITE_LOCK:
        return _poll_and_save_impl(watchlist, force)

def _poll_and_save_impl(watchlist, force=False):
    global LAST_EOD_RUN_DATE, LATEST_OI_CACHE, LAST_OI_FETCH_DATE
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Check if EOD Bhavcopy is ready (usually uploaded by 6:00 PM IST)
    now = datetime.now()
    current_date_str = now.strftime("%Y-%m-%d")
    if now.hour >= 18 and now.weekday() < 5 and LAST_OI_FETCH_DATE != current_date_str:
        refresh_oi_cache()
    
    # Check if inside market hours
    if not force and not is_market_hours():
        print(f"💤 [Market Closed] {timestamp_str} - Outside market hours (9:15 AM - 3:30 PM weekdays). Skipping TradingView API query.")
        
        # Check if we should run today's EOD retrospective (in case it hasn't run yet)
        now = datetime.now()
        current_date_str = now.strftime("%Y-%m-%d")
        if now.hour > 15 or (now.hour == 15 and now.minute >= 30):
            if LAST_EOD_RUN_DATE != current_date_str:
                print(f"  🔍 EOD Market Closed. Running EOD Retrospective for {current_date_str}...")
                analyzer.run_eod_retrospective(current_date_str)
                LAST_EOD_RUN_DATE = current_date_str
                # Re-generate the dashboard so EOD stats show up
                analyzer.generate_dashboard(watchlist)
        return
        
    if force:
        print(f"\n⚡ [Force Fetch Started] {timestamp_str} - Querying {len(watchlist)} F&O symbols (Bypassing market hours)...")
    else:
        print(f"\n⚡ [Poll Started] {timestamp_str} - Querying {len(watchlist)} F&O symbols...")
    
    batches = list(chunk_list(watchlist, 50))
    all_data = []
    
    for idx, batch in enumerate(batches):
        print(f"  📡 Querying batch {idx+1}/{len(batches)} ({len(batch)} symbols)...")
        batch_results = query_tradingview_batch(batch)
        all_data.extend(batch_results)
        time.sleep(0.5)
        
    print(f"  ✅ Retrieved data for {len(all_data)} symbols.")
    
    records_to_insert = []
    for item in all_data:
        symbol = item.get("s")
        d_vals = item.get("d", [])
        if len(d_vals) >= 12:
            close_price = d_vals[0]
            day_change = d_vals[1]
            macd_line = d_vals[2]
            signal_line = d_vals[3]
            rsi = d_vals[4]
            volume = d_vals[5]
            average_volume = d_vals[6]
            rsi_30 = d_vals[7]
            rsi_60 = d_vals[8]
            macd_day = d_vals[9]
            macd_signal_day = d_vals[10]
            rsi_day = d_vals[11]
            
            histogram = None
            if macd_line is not None and signal_line is not None:
                histogram = macd_line - signal_line
                
            macd_hist_day = None
            if macd_day is not None and macd_signal_day is not None:
                macd_hist_day = macd_day - macd_signal_day
                
            clean_symbol = symbol
            if clean_symbol.startswith("NSE:"):
                clean_symbol = clean_symbol[4:]
                
            oi_data = LATEST_OI_CACHE.get(clean_symbol, {})
            total_ce_oi = oi_data.get("total_ce_oi")
            total_pe_oi = oi_data.get("total_pe_oi")
            pcr = oi_data.get("pcr")
            futures_oi = oi_data.get("futures_oi")
            futures_oi_change_pct = oi_data.get("futures_oi_change_pct")

            records_to_insert.append((
                timestamp_str,
                symbol,
                close_price,
                day_change,
                macd_line,
                signal_line,
                histogram,
                rsi,
                volume,
                average_volume,
                total_ce_oi,
                total_pe_oi,
                pcr,
                futures_oi,
                futures_oi_change_pct,
                rsi_30,
                rsi_60,
                macd_day,
                macd_signal_day,
                macd_hist_day,
                rsi_day
            ))
            
    if records_to_insert:
        db_manager.insert_records(records_to_insert)
        print(f"  💾 Saved {len(records_to_insert)} records to SQLite database.")
        
        # Housekeeping: delete records older than 30 days
        db_manager.cleanup_old_records(days=30)
        
        # Trigger analyzer
        print("  🔍 Running analyzer...")
        alerts = analyzer.analyze_all_symbols(watchlist)
        print(f"  🔔 Analyzer completed. {len(alerts)} alerts triggered this poll.")
        
        # Check if we should run EOD retrospective (after 3:30 PM)
        now = datetime.now()
        current_date_str = now.strftime("%Y-%m-%d")
        if now.hour > 15 or (now.hour == 15 and now.minute >= 30):
            if LAST_EOD_RUN_DATE != current_date_str:
                print(f"  🔍 EOD Market Closed. Running EOD Retrospective for {current_date_str}...")
                analyzer.run_eod_retrospective(current_date_str)
                LAST_EOD_RUN_DATE = current_date_str
                # Re-generate the dashboard so EOD stats show up
                analyzer.generate_dashboard(watchlist)
    else:
        print("  ⚠️ No valid records to save.")

def main():
    print("==========================================================")
    print("🚀 F&O MACD MOMENTUM TRACKER DAEMON")
    print("==========================================================")
    
    db_manager.init_db()
    
    global WATCHLIST
    WATCHLIST = watchlist_manager.fetch_and_initialize_fo_list()
    watchlist = WATCHLIST
    if not watchlist:
        print("Fatal: Could not initialize F&O symbols watchlist.")
        sys.exit(1)
        
    # Start web server thread
    web_thread = threading.Thread(target=run_web_server, daemon=True)
    web_thread.start()
    
    # Initialize OI cache on startup
    refresh_oi_cache()
        
    config = load_config()
    interval_seconds = config.get("poll_interval_minutes", 2.0) * 60
    
    print(f"Configured poll interval: {config.get('poll_interval_minutes')} minutes ({interval_seconds} seconds)")
    print("Press Ctrl+C to stop the daemon.\n")
    
    # Run EOD retrospective recovery on startup
    print("  🔍 Checking for missing EOD retrospectives on startup...")
    try:
        analyzer.run_eod_retrospective()  # Scans last 30 days and catches up on missing evaluations
        analyzer.generate_dashboard(watchlist)
    except Exception as e:
        print(f"  ⚠️ Error running startup retrospectives: {e}")
        
    poll_and_save(watchlist)
    
    while True:
        try:
            print(f"\nSleeping for {config.get('poll_interval_minutes')} minutes...")
            time.sleep(interval_seconds)
            config = load_config()
            interval_seconds = config.get("poll_interval_minutes", 2.0) * 60
            poll_and_save(watchlist)
        except KeyboardInterrupt:
            print("\nStopping MACD Momentum Tracker Daemon...")
            sys.exit(0)
        except Exception as e:
            print(f"Error in tracking loop: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
