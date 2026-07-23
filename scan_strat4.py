import sqlite3
import pandas as pd
import sys
from datetime import datetime

db_path = "/Users/sree/macd_momentum_tracker/db/macd_history.db"

def scan_strategy_4(days=3):
    conn = sqlite3.connect(db_path)
    
    # Query to fetch bullish signals matching Strategy 4 parameters
    # Criteria: 
    # 1. Bullish MACD alert
    # 2. Cash Volume Ratio >= 150%
    # 3. Futures Open Interest Change >= 1.5%
    query = """
    SELECT 
        a.timestamp,
        a.symbol,
        a.alert_type,
        a.price,
        a.day_change,
        a.rsi,
        (a.volume / a.average_volume) * 100 as vol_ratio_pct,
        a.pcr,
        a.futures_oi_change_pct,
        r.eod_price,
        r.pct_change as intraday_return
    FROM alerts_triggered a
    LEFT JOIN alert_retrospectives r ON a.symbol = r.symbol AND a.timestamp = r.alert_timestamp
    WHERE 
        a.alert_type IN ('BULLISH_CROSSOVER', 'MACD_INCREASE', 'HISTOGRAM_ACCELERATING', 'MOMENTUM_START')
        AND (a.volume / a.average_volume) * 100 >= 150.0
        AND a.futures_oi_change_pct >= 1.5
        AND date(a.timestamp) >= date('now', ?)
    ORDER BY a.timestamp DESC, vol_ratio_pct DESC
    """
    
    # Calculate days offset for SQL
    days_offset = f"-{days} days"
    df = pd.read_sql_query(query, conn, params=(days_offset,))
    conn.close()
    
    if len(df) == 0:
        print(f"\033[93mNo Strategy 4 (Institutional Accumulation) signals found in the last {days} days.\033[0m")
        return
        
    # Deduplicate to find the first signal per symbol per day
    df['date'] = df['timestamp'].str[:10]
    df = df.sort_values(by=['timestamp', 'vol_ratio_pct'], ascending=[True, False])
    df_unique = df.drop_duplicates(subset=['date', 'symbol'], keep='first')
    df_unique = df_unique.sort_values(by='timestamp', ascending=False)
    
    print(f"\n\033[95m==========================================================================")
    print(f"🚀 STRATEGY 4 SCANNER: INSTITUTIONAL ACCUMULATION ({len(df_unique)} Signals Fired)")
    print(f"==========================================================================\033[0m")
    
    header = f"{'Timestamp':<20} | {'Symbol':<12} | {'Signal Price':<12} | {'Vol Ratio':<10} | {'Fut OI Δ%':<10} | {'RSI':<6} | {'PCR':<5} | {'EOD Return':<10}"
    print(header)
    print("-" * len(header))
    
    for idx, r in df_unique.iterrows():
        sym = r['symbol'].replace("NSE:", "")
        time_str = r['timestamp']
        vol_str = f"{r['vol_ratio_pct']:.1f}%"
        oi_str = f"{r['futures_oi_change_pct']:+.2f}%"
        rsi_str = f"{r['rsi']:.1f}"
        pcr_str = f"{r['pcr']:.2f}" if r['pcr'] is not None else "N/A"
        price_str = f"₹{r['price']:.2f}"
        
        # Color code return if available
        ret_val = r['intraday_return']
        if pd.isna(ret_val):
            ret_str = "Pending"
        elif ret_val > 0:
            ret_str = f"\033[92m{ret_val:+.2f}%\033[0m"
        else:
            ret_str = f"\033[91m{ret_val:+.2f}%\033[0m"
            
        row_str = f"{time_str:<20} | \033[1m{sym:<12}\033[0m | {price_str:<12} | \033[94m{vol_str:<10}\033[0m | \033[96m{oi_str:<10}\033[0m | {rsi_str:<6} | {pcr_str:<5} | {ret_str:<10}"
        print(row_str)
        
    print(f"\033[95m--------------------------------------------------------------------------\033[0m")
    print(f"🔍 Parameters used: Volume Ratio >= 150%, Futures OI Change >= 1.5%, Bullish MACD")
    
if __name__ == "__main__":
    days_to_scan = 3
    if len(sys.argv) > 1:
        try:
            days_to_scan = int(sys.argv[1])
        except ValueError:
            print("Usage: python3 scan_strat4.py [days_to_scan]")
            sys.exit(1)
            
    scan_strategy_4(days_to_scan)
