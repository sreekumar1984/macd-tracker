import requests
import zipfile
import io
import pandas as pd
from datetime import datetime, timedelta
import os

def download_latest_fo_bhavcopy():
    """
    Backtracks day-by-day starting from today to find and download
    the latest available F&O UDiFF Bhavcopy from NSE Archives.
    Returns (date_str, pandas DataFrame) or (None, None).
    """
    base_url = "https://nsearchives.nseindia.com/content/fo"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    # Try up to 7 days back
    now = datetime.now()
    for i in range(8):
        check_date = now - timedelta(days=i)
        # 5 = Saturday, 6 = Sunday (skip weekends as Bhavcopies are not generated)
        if check_date.weekday() >= 5:
            continue
            
        date_str = check_date.strftime("%Y%m%dd")[:-1] # Format YYYYMMDD
        file_name = f"BhavCopy_NSE_FO_0_0_0_{date_str}_F_0000.csv.zip"
        url = f"{base_url}/{file_name}"
        
        print(f"  📡 Bhavcopy: Checking availability for {check_date.strftime('%d-%b-%Y')}...")
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                print(f"  ✅ Bhavcopy: Successfully downloaded file for {check_date.strftime('%d-%b-%Y')}.")
                # Unzip in memory
                zip_file = zipfile.ZipFile(io.BytesIO(r.content))
                csv_names = zip_file.namelist()
                if csv_names:
                    csv_data = zip_file.read(csv_names[0])
                    df = pd.read_csv(io.BytesIO(csv_data))
                    return check_date.strftime("%Y-%m-%d"), df
            elif r.status_code == 403 or r.status_code == 404:
                # 404 means file not uploaded yet or not a trading day
                pass
            else:
                print(f"  ⚠️ Bhavcopy: Unexpected response code {r.status_code} for {date_str}.")
        except Exception as e:
            print(f"  ⚠️ Bhavcopy Connection Error for {date_str}: {e}")
            
        # Introduce a small sleep to avoid hammering
        time_sleep = 0.5
        import time
        time.sleep(time_sleep)
        
    print("  ❌ Bhavcopy: Could not find any available Bhavcopy in the last 7 days.")
    return None, None

def extract_oi_metrics(df):
    """
    Processes the raw Bhavcopy DataFrame to extract:
      - Spot Price
      - Futures OI & Futures OI Change %
      - Options CE OI & PE OI
      - PCR (Put-Call Ratio)
    Returns a dictionary of symbol -> metrics.
    """
    if df is None or df.empty:
        return {}
        
    # Standardize column strings
    df.columns = [col.strip() for col in df.columns]
    
    # We aggregate by Ticker Symbol
    # In UDiFF F&O: TckrSymb is the symbol (e.g. TRENT, NIFTY)
    # FinInstrmTp is STF (Stock Futures), STO (Stock Options), IDF (Index Futures), IDO (Index Options)
    # OptnTp is CE (Call Option), PE (Put Option), nan/XX (Futures)
    # OpnIntrst is Open Interest
    # ChngInOpnIntrst is Change in Open Interest
    # UndrlygPric is Underlying Spot Price
    
    results = {}
    
    # Group by symbol
    grouped = df.groupby('TckrSymb')
    
    for symbol, group in grouped:
        # 1. Spot price (usually the same across rows, we take the max/first valid)
        spot_series = group['UndrlygPric'].dropna()
        spot = float(spot_series.iloc[0]) if not spot_series.empty else 0.0
        
        # 2. Futures Open Interest and Change
        fut_rows = group[group['FinInstrmTp'].isin(['STF', 'IDF'])]
        total_fut_oi = int(fut_rows['OpnIntrst'].sum())
        total_fut_oi_chg = int(fut_rows['ChngInOpnIntrst'].sum())
        
        # Calculate Futures OI Change %
        prev_fut_oi = total_fut_oi - total_fut_oi_chg
        fut_oi_chg_pct = (total_fut_oi_chg / prev_fut_oi * 100) if prev_fut_oi > 0 else 0.0
        
        # 3. Options Call (CE) Open Interest
        ce_rows = group[(group['FinInstrmTp'].isin(['STO', 'IDO'])) & (group['OptnTp'] == 'CE')]
        total_ce_oi = int(ce_rows['OpnIntrst'].sum())
        
        # 4. Options Put (PE) Open Interest
        pe_rows = group[(group['FinInstrmTp'].isin(['STO', 'IDO'])) & (group['OptnTp'] == 'PE')]
        total_pe_oi = int(pe_rows['OpnIntrst'].sum())
        
        # Calculate Put-Call Ratio
        pcr = (total_pe_oi / total_ce_oi) if total_ce_oi > 0 else 0.0
        
        results[symbol] = {
            "spot_price": spot,
            "futures_oi": total_fut_oi,
            "futures_oi_change_pct": fut_oi_chg_pct,
            "total_ce_oi": total_ce_oi,
            "total_pe_oi": total_pe_oi,
            "pcr": pcr
        }
        
    return results

def get_latest_oi_data():
    """
    Main function to get the processed OI data for all F&O symbols.
    Returns (date_str, dictionary symbol -> metrics).
    """
    date_str, df = download_latest_fo_bhavcopy()
    if df is not None:
        metrics = extract_oi_metrics(df)
        return date_str, metrics
    return None, {}

if __name__ == "__main__":
    date_str, metrics = get_latest_oi_data()
    if date_str:
        print(f"\nSuccessfully processed Bhavcopy for date: {date_str}")
        print("Total symbols parsed:", len(metrics))
        for test_sym in ["TRENT", "NIFTY", "RELIANCE"]:
            if test_sym in metrics:
                print(f"\n{test_sym} Metrics:")
                for k, v in metrics[test_sym].items():
                    print(f"  {k}: {v}")
