import asyncio
import json
import os
import sys
import time
import threading
import logging
from datetime import datetime, time as datetime_time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
import requests
import yfinance as yf
import pandas as pd

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

# Setup logging to both file and stdout
LOG_FILE_PATH = os.path.join(BASE_DIR, "tracker.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE_PATH),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("tracker")

def update_logging_level():
    config = load_config()
    if config.get("logging_enabled", True):
        logger.setLevel(logging.INFO)
    else:
        logger.setLevel(logging.WARNING)

def log_memory_usage():
    try:
        import resource
        import platform
        usage = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # On macOS, ru_maxrss is in bytes. On Linux, it is in kilobytes.
        if platform.system() == 'Darwin':
            usage_mb = usage / (1024 * 1024)
        else:
            usage_mb = usage / 1024
        logger.info(f"💾 Current process RAM usage: {usage_mb:.2f} MB")
    except Exception as e:
        pass

# Global status for tracking force fetch progress
FETCH_STATUS = {
    "running": False,
    "progress": 0,
    "total": 0,
    "current_symbol": "",
    "message": "Idle",
    "error": None
}

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
        elif parsed.path == '/force_fetch_status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(FETCH_STATUS).encode('utf-8'))
        elif parsed.path == '/api/dashboard_components':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_cors_headers()
            self.end_headers()
            components_file = os.path.join(BASE_DIR, "dashboard_components.json")
            if os.path.exists(components_file):
                with open(components_file, "rb") as f:
                    self.wfile.write(f.read())
            else:
                self.wfile.write(json.dumps({}).encode('utf-8'))
        else:
            self.send_response(404)
            self.send_cors_headers()
            self.end_headers()
            self.wfile.write(b"Page not found")

    def do_POST(self):
        global WATCHLIST
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
                was_active = old_config.get("tracking_active", True)
                is_active = new_config.get("tracking_active", True)
                
                old_config.update(new_config)
                with open(CONFIG_PATH, "w") as f:
                    json.dump(old_config, f, indent=2)
                
                update_logging_level()
                    
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "saved"}).encode('utf-8'))
                print("  ⚙️ Config dynamically updated from dashboard Web UI.")
                
                # If tracking was off and is now turned on, trigger an immediate background poll
                if is_active and not was_active:
                    print("⚡ Tracking activated. Triggering immediate poll in the background...")
                    def run_immediate_poll():
                        try:
                            poll_and_save(WATCHLIST)
                        except Exception as poll_err:
                            print(f"Error in immediate background poll: {poll_err}")
                    threading.Thread(target=run_immediate_poll, daemon=True).start()
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        elif parsed.path == '/force_fetch':
            if FETCH_STATUS["running"]:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Force fetch already in progress"}).encode('utf-8'))
                return
                
            try:
                if not WATCHLIST:
                    from watchlist_manager import WATCHLIST_PATH
                    if os.path.exists(WATCHLIST_PATH):
                        with open(WATCHLIST_PATH, "r") as f:
                            WATCHLIST = json.load(f)
                    else:
                        WATCHLIST = watchlist_manager.fetch_and_initialize_fo_list()
                
                print("⚡ [Web Request] Force fetch triggered via Web Dashboard. Starting background thread...")
                
                def run_force_fetch_async():
                    global FETCH_STATUS
                    try:
                        poll_and_save(WATCHLIST, force=True)
                    except Exception as e:
                        FETCH_STATUS["running"] = False
                        FETCH_STATUS["error"] = str(e)
                        FETCH_STATUS["message"] = f"Error during force fetch: {e}"
                        print(f"❌ Error during force fetch background thread: {e}")
                
                threading.Thread(target=run_force_fetch_async, daemon=True).start()
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "started", "message": "Force fetch started in background"}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        elif parsed.path == '/force_retro':
            try:
                if not WATCHLIST:
                    from watchlist_manager import WATCHLIST_PATH
                    if os.path.exists(WATCHLIST_PATH):
                        with open(WATCHLIST_PATH, "r") as f:
                            WATCHLIST = json.load(f)
                    else:
                        WATCHLIST = watchlist_manager.fetch_and_initialize_fo_list()
                
                logger.info("⚡ [Web Request] Force EOD Retrospective triggered via Web Dashboard. Starting background thread...")
                
                def run_force_retro_async():
                    try:
                        analyzer.run_eod_retrospective(force=True)
                        analyzer.generate_dashboard(WATCHLIST)
                        logger.info("  ✅ Manual EOD Retrospective completed.")
                    except Exception as e:
                        logger.error(f"❌ Error during manual retrospective background thread: {e}")
                
                threading.Thread(target=run_force_retro_async, daemon=True).start()
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "started", "message": "Manual retrospective run started in background"}).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        elif parsed.path == '/clear_logs':
            try:
                if os.path.exists(LOG_FILE_PATH):
                    with open(LOG_FILE_PATH, "w") as f:
                        f.write("")
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "cleared"}).encode('utf-8'))
                print("  📝 System log file cleared via dashboard UI request.")
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

def tv_to_yf_symbol(symbol):
    if symbol.startswith("NSE:"):
        clean = symbol[4:]
    else:
        clean = symbol
    if clean == "NIFTY":
        return "^NSEI"
    elif clean == "BANKNIFTY":
        return "^NSEBANK"
    elif clean == "FINNIFTY":
        return "NIFTY-FIN-SERVICE.NS"
    elif clean == "MIDCPNIFTY":
        return "^NSEMDCP50"
    
    clean_yf = clean.replace("_", "-")
    return f"{clean_yf}.NS"

def calculate_45m_macd_batch(watchlist):
    logger.info("Fetching 45-minute MACD from yfinance...")
    yf_symbols = [tv_to_yf_symbol(sym) for sym in watchlist]
    yf_to_tv = {tv_to_yf_symbol(sym): sym for sym in watchlist}
    
    results = {}
    import gc
    
    # Chunk the download into batches of 40 to avoid massive RAM spikes and OOM killer on 1GB instances
    chunk_size = 40
    for i in range(0, len(yf_symbols), chunk_size):
        chunk_yf_symbols = yf_symbols[i:i + chunk_size]
        logger.info(f"Downloading yfinance batch {i // chunk_size + 1}/{(len(yf_symbols) - 1) // chunk_size + 1} ({len(chunk_yf_symbols)} symbols)...")
        try:
            # Using 10 threads instead of 30 to limit CPU credit exhaustion
            df = yf.download(chunk_yf_symbols, period="10d", interval="15m", group_by="ticker", threads=10, progress=False)
            
            for yf_sym in chunk_yf_symbols:
                try:
                    # Check if symbol has data in df
                    if isinstance(df.columns, pd.MultiIndex):
                        if yf_sym not in df.columns.levels[0]:
                            continue
                        sym_df = df[yf_sym]
                    else:
                        if len(chunk_yf_symbols) == 1:
                            sym_df = df
                        else:
                            if yf_sym not in df.columns:
                                continue
                            sym_df = df[yf_sym]
                            
                    if sym_df.empty or 'Close' not in sym_df.columns:
                        continue
                        
                    # Extract only the Close price series to minimize memory during resample
                    close_series = sym_df['Close'].dropna()
                    if len(close_series) < 26:
                        continue
                        
                    # Resample Close only to 45m
                    resampled_close = close_series.resample('45min', origin='start_day').last().dropna()
                    
                    if len(resampled_close) < 26:
                        continue
                        
                    exp1 = resampled_close.ewm(span=12, adjust=False).mean()
                    exp2 = resampled_close.ewm(span=26, adjust=False).mean()
                    macd = exp1 - exp2
                    sig = macd.ewm(span=9, adjust=False).mean()
                    hist = macd - sig
                    
                    results[yf_to_tv[yf_sym]] = (float(macd.iloc[-1]), float(sig.iloc[-1]), float(hist.iloc[-1]))
                except Exception as e:
                    # Ignore individual stock errors
                    pass
            
            # Explicitly free memory for this chunk
            del df
            gc.collect()
            log_memory_usage()
        except Exception as e:
            logger.error(f"Error in yfinance batch: {e}")
            
    return results

def poll_and_save(watchlist, force=False):
    with DB_WRITE_LOCK:
        return _poll_and_save_impl(watchlist, force)

def _poll_and_save_impl(watchlist, force=False):
    global LAST_EOD_RUN_DATE, LATEST_OI_CACHE, LAST_OI_FETCH_DATE, FETCH_STATUS
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Initialize status
    FETCH_STATUS = {
        "running": True,
        "progress": 0,
        "total": len(watchlist),
        "current_symbol": "Initializing",
        "message": "Starting fetch...",
        "error": None
    }
    
    # Check if EOD Bhavcopy is ready (usually uploaded by 6:00 PM IST)
    now = datetime.now()
    current_date_str = now.strftime("%Y-%m-%d")
    if now.hour >= 18 and now.weekday() < 5 and LAST_OI_FETCH_DATE != current_date_str:
        FETCH_STATUS["message"] = "Refreshing EOD OI Cache from Bhavcopy..."
        refresh_oi_cache()
    
    # Check if we should run today's EOD retrospective (in case it hasn't run yet after 3:30 PM)
    now = datetime.now()
    current_date_str = now.strftime("%Y-%m-%d")
    if now.hour > 15 or (now.hour == 15 and now.minute >= 30):
        if LAST_EOD_RUN_DATE != current_date_str:
            config = load_config()
            if config.get("enable_eod_retrospective", True):
                print(f"  🔍 EOD Market Closed. Running EOD Retrospective for {current_date_str}...")
                FETCH_STATUS["message"] = "Running EOD Retrospective..."
                try:
                    analyzer.run_eod_retrospective(current_date_str)
                    LAST_EOD_RUN_DATE = current_date_str
                    # Re-generate the dashboard so EOD stats show up
                    analyzer.generate_dashboard(watchlist)
                except Exception as e:
                    print(f"  ⚠️ Error running EOD Retrospective: {e}")
            else:
                print("  💤 EOD Market Closed, but EOD Retrospective is disabled in config. Skipping retrospective run.")
        
    if force:
        print(f"\n⚡ [Force Fetch Started] {timestamp_str} - Querying {len(watchlist)} F&O symbols (Bypassing market hours)...")
    else:
        print(f"\n⚡ [Poll Started] {timestamp_str} - Querying {len(watchlist)} F&O symbols...")
    
    batches = list(chunk_list(watchlist, 50))
    all_data = []
    
    for idx, batch in enumerate(batches):
        print(f"  📡 Querying batch {idx+1}/{len(batches)} ({len(batch)} symbols)...")
        FETCH_STATUS["message"] = f"Querying TradingView data (Batch {idx+1}/{len(batches)})..."
        FETCH_STATUS["current_symbol"] = batch[0] if batch else ""
        
        batch_results = query_tradingview_batch(batch)
        all_data.extend(batch_results)
        
        FETCH_STATUS["progress"] = len(all_data)
        time.sleep(0.5)
        
    print(f"  ✅ Retrieved data for {len(all_data)} symbols.")
    
    # Calculate 45m MACD values via yfinance
    FETCH_STATUS["message"] = "Calculating 45-minute MACD from yfinance (takes a moment)..."
    FETCH_STATUS["current_symbol"] = "yfinance download"
    macd_45_data = calculate_45m_macd_batch(watchlist)
    
    records_to_insert = []
    FETCH_STATUS["message"] = "Processing retrieved data..."
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
                
            # Get 45m MACD values
            macd_45, signal_45, hist_45 = macd_45_data.get(symbol, (None, None, None))
                
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
                rsi_day,
                macd_45,
                signal_45,
                hist_45
            ))
            
    if records_to_insert:
        FETCH_STATUS["message"] = "Saving records to SQLite database..."
        db_manager.insert_records(records_to_insert)
        print(f"  💾 Saved {len(records_to_insert)} records to SQLite database.")
        
        # Housekeeping: delete records older than 30 days
        db_manager.cleanup_old_records(days=30)
        
        # Trigger analyzer
        print("  🔍 Running analyzer...")
        FETCH_STATUS["message"] = "Analyzing records and updating dashboard..."
        alerts = analyzer.analyze_all_symbols(watchlist)
        print(f"  🔔 Analyzer completed. {len(alerts)} alerts triggered this poll.")
        
        # Check if we should run EOD retrospective (after 3:30 PM)
        now = datetime.now()
        current_date_str = now.strftime("%Y-%m-%d")
        if now.hour > 15 or (now.hour == 15 and now.minute >= 30):
            if LAST_EOD_RUN_DATE != current_date_str:
                config = load_config()
                if config.get("enable_eod_retrospective", True):
                    print(f"  🔍 EOD Market Closed. Running EOD Retrospective for {current_date_str}...")
                    FETCH_STATUS["message"] = "Running EOD Retrospective..."
                    analyzer.run_eod_retrospective(current_date_str)
                    LAST_EOD_RUN_DATE = current_date_str
                    # Re-generate the dashboard so EOD stats show up
                    analyzer.generate_dashboard(watchlist)
                else:
                    print("  💤 EOD Market Closed, but EOD Retrospective is disabled in config. Skipping retrospective run.")
    else:
        print("  ⚠️ No valid records to save.")
        FETCH_STATUS["message"] = "No valid records retrieved."
        
    FETCH_STATUS["running"] = False
    FETCH_STATUS["progress"] = len(watchlist)
    FETCH_STATUS["message"] = "Completed successfully"

def main():
    print("==========================================================")
    print("🚀 F&O MACD MOMENTUM TRACKER DAEMON")
    print("==========================================================")
    
    db_manager.init_db()
    update_logging_level()
    
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
    config = load_config()
    if config.get("enable_eod_retrospective", True):
        print("  🔍 Checking for missing EOD retrospectives on startup...")
        try:
            analyzer.run_eod_retrospective()  # Scans last 30 days and catches up on missing evaluations
            analyzer.generate_dashboard(watchlist)
        except Exception as e:
            print(f"  ⚠️ Error running startup retrospectives: {e}")
    else:
        print("💤 EOD Retrospective is disabled in config. Skipping startup retrospective checks.")
        analyzer.generate_dashboard(watchlist)
        
    if config.get("tracking_active", True):
        poll_and_save(watchlist)
    else:
        print("💤 Tracking is currently stopped (inactive in config). Skipping startup poll.")
    
    while True:
        try:
            print(f"\nSleeping for {config.get('poll_interval_minutes')} minutes...")
            time.sleep(interval_seconds)
            config = load_config()
            update_logging_level()
            interval_seconds = config.get("poll_interval_minutes", 2.0) * 60
            if config.get("tracking_active", True):
                poll_and_save(watchlist)
            else:
                print("💤 Tracking is currently stopped (inactive in config). Skipping scheduled poll.")
        except KeyboardInterrupt:
            print("\nStopping MACD Momentum Tracker Daemon...")
            sys.exit(0)
        except Exception as e:
            print(f"Error in tracking loop: {e}")
            time.sleep(10)

if __name__ == "__main__":
    main()
