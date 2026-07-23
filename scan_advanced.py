import sqlite3
import pandas as pd
import sys

db_path = "/Users/sree/macd_momentum_tracker/db/macd_history.db"

def scan_advanced_signals(days=3):
    conn = sqlite3.connect(db_path)
    
    # Query to fetch both Golden RSI and Triple MACD setups
    query = """
    SELECT 
        a.timestamp,
        a.symbol,
        a.alert_type,
        a.price,
        a.day_change,
        a.rsi,
        a.rsi_30,
        a.rsi_60,
        a.rsi_day,
        a.macd_hist_day,
        a.macd_hist_45,
        a.histogram_change,
        (a.volume / a.average_volume) * 100 as vol_ratio_pct,
        a.pcr,
        r.pct_change as intraday_return
    FROM alerts_triggered a
    LEFT JOIN alert_retrospectives r ON a.symbol = r.symbol AND a.timestamp = r.alert_timestamp
    WHERE 
        a.alert_type IN ('BULLISH_CROSSOVER', 'MACD_INCREASE', 'HISTOGRAM_ACCELERATING', 'MOMENTUM_START')
        AND date(a.timestamp) >= date('now', ?)
    """
    
    days_offset = f"-{days} days"
    df = pd.read_sql_query(query, conn, params=(days_offset,))
    conn.close()
    
    if len(df) == 0:
        print(f"\033[93mNo bullish alerts found in the last {days} days.\033[0m")
        return
        
    # Classify setups
    # 1. Golden RSI: rsi_day > 50, rsi > 50, rsi_30 > rsi_60
    cond_golden = (df['rsi_day'] > 50.0) & (df['rsi'] > 50.0) & (df['rsi_30'] > df['rsi_60'])
    df_golden = df[cond_golden].copy()
    df_golden['pattern'] = "🌟 Golden RSI"
    
    # 2. Triple MACD: hist_day > 0, hist_45 > 0, hist_change > 0.1
    cond_macd = (df['macd_hist_day'] > 0) & (df['macd_hist_45'] > 0) & (df['histogram_change'] > 0.1)
    df_macd = df[cond_macd].copy()
    df_macd['pattern'] = "💎 Triple MACD"
    
    # Combine
    df_combined = pd.concat([df_golden, df_macd])
    
    if len(df_combined) == 0:
        print(f"\033[93mNo Golden RSI or Triple MACD signals found in the last {days} days.\033[0m")
        return
        
    # Deduplicate by date, symbol, and pattern to keep earliest daily signal
    df_combined['date'] = df_combined['timestamp'].str[:10]
    df_combined = df_combined.sort_values(by='timestamp', ascending=True)
    df_unique = df_combined.drop_duplicates(subset=['date', 'symbol', 'pattern'], keep='first')
    df_unique = df_unique.sort_values(by='timestamp', ascending=False)
    
    print(f"\n\033[95m==========================================================================")
    print(f"🔥 ADVANCED SCANNER: GOLDEN RSI & TRIPLE MACD ({len(df_unique)} Signals Fired)")
    print(f"==========================================================================\033[0m")
    
    header = f"{'Timestamp':<20} | {'Symbol':<12} | {'Pattern Type':<15} | {'Price':<10} | {'15m RSI':<7} | {'Day RSI':<7} | {'Vol Ratio':<10} | {'EOD Return':<10}"
    print(header)
    print("-" * len(header))
    
    for idx, r in df_unique.iterrows():
        sym = r['symbol'].replace("NSE:", "")
        time_str = r['timestamp']
        price_str = f"₹{r['price']:.2f}"
        rsi_15m = f"{r['rsi']:.1f}" if r['rsi'] is not None else "N/A"
        rsi_d = f"{r['rsi_day']:.1f}" if r['rsi_day'] is not None else "N/A"
        vol_str = f"{r['vol_ratio_pct']:.1f}%" if r['vol_ratio_pct'] is not None else "N/A"
        pat = r['pattern']
        
        # Color code return if available
        ret_val = r['intraday_return']
        if pd.isna(ret_val):
            ret_str = "Pending"
        elif ret_val > 0:
            ret_str = f"\033[92m{ret_val:+.2f}%\033[0m"
        else:
            ret_str = f"\033[91m{ret_val:+.2f}%\033[0m"
            
        color_pat = f"\033[93m{pat:<15}\033[0m" if "Golden" in pat else f"\033[96m{pat:<15}\033[0m"
        
        row_str = f"{time_str:<20} | \033[1m{sym:<12}\033[0m | {color_pat} | {price_str:<10} | {rsi_15m:<7} | {rsi_d:<7} | {vol_str:<10} | {ret_str:<10}"
        print(row_str)
        
    print(f"\033[95m--------------------------------------------------------------------------\033[0m")
    print(f"💡 Info: Run 'python3 scan_advanced.py [days]' to scan further back.")
    
if __name__ == "__main__":
    days_to_scan = 3
    if len(sys.argv) > 1:
        try:
            days_to_scan = int(sys.argv[1])
        except ValueError:
            print("Usage: python3 scan_advanced.py [days_to_scan]")
            sys.exit(1)
            
    scan_advanced_signals(days_to_scan)
