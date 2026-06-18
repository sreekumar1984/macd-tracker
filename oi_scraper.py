import time
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from curl_cffi import requests
from playwright.sync_api import sync_playwright

def get_session_cookies():
    """
    Launches Playwright headless Firefox to initialize the Akamai session
    and extract authenticated cookies.
    """
    target_url = "https://www.nseindia.com/option-chain"
    print("  🕷️ Playwright: Initializing browser to fetch authenticated cookies...")
    
    with sync_playwright() as p:
        try:
            browser = p.firefox.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            
            # Use a flag to check if NIFTY option-chain call was captured
            authenticated = [False]
            page.on("response", lambda r: authenticated.append(True) if "/api/option-chain-v3" in r.url and r.status == 200 else None)
            
            page.goto(target_url, wait_until="load", timeout=20000)
            
            # Wait for NIFTY request to succeed
            for _ in range(20):
                if len(authenticated) > 1:
                    break
                page.wait_for_timeout(500)
                
            if len(authenticated) > 1:
                cookies = context.cookies()
                print("  🕷️ Playwright: Cookies successfully generated.")
                cookie_dict = {c['name']: c['value'] for c in cookies}
                browser.close()
                return cookie_dict
            else:
                print("  ⚠️ Playwright: NIFTY request was not captured within timeout.")
                browser.close()
                return {}
        except Exception as e:
            print(f"  ⚠️ Playwright Exception: {e}")
            return {}

def fetch_symbol_oi(session, symbol, cookie_dict, headers):
    """
    Fetches the contract info and option chain data for a single symbol.
    """
    # Clean symbol name from prefix (e.g. "NSE:TRENT" -> "TRENT")
    clean_sym = symbol.split(":")[-1]
    
    # Check if index
    is_index = clean_sym in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]
    mkt_type = "Indices" if is_index else "Equities"
    
    # Step 1: Fetch contract info first to update session state
    contract_url = f"https://www.nseindia.com/api/option-chain-contract-info?symbol={clean_sym}"
    try:
        r1 = session.get(contract_url, headers=headers, cookies=cookie_dict, impersonate="firefox", timeout=10)
        if r1.status_code != 200:
            return symbol, None
            
        contract_data = r1.json()
        expiries = contract_data.get("expiryDates", [])
        if not expiries:
            return symbol, None
            
        nearest_expiry = expiries[0]
        
        # Step 2: Fetch option chain v3
        api_url = f"https://www.nseindia.com/api/option-chain-v3?type={mkt_type}&symbol={clean_sym}&expiry={nearest_expiry}"
        r2 = session.get(api_url, headers=headers, cookies=cookie_dict, impersonate="firefox", timeout=12)
        
        if r2.status_code == 200:
            data = r2.json()
            filtered = data.get("filtered", {})
            total_ce_oi = filtered.get("CE", {}).get("totOI", 0)
            total_pe_oi = filtered.get("PE", {}).get("totOI", 0)
            pcr = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 0.0
            return symbol, {
                "total_ce_oi": total_ce_oi,
                "total_pe_oi": total_pe_oi,
                "pcr": pcr,
                "expiry": nearest_expiry
            }
    except Exception:
        pass
    return symbol, None

def scrape_all_oi(symbols, max_workers=10):
    """
    Fetches Open Interest and PCR for a list of symbols concurrently.
    """
    cookie_dict = get_session_cookies()
    if not cookie_dict:
        print("  ⚠️ Options Scraper: Could not authenticate session. Skipping OI fetch.")
        return {}
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/option-chain"
    }
    
    session = requests.Session()
    
    # Establish connection by visiting options page once
    try:
        session.get("https://www.nseindia.com/option-chain", headers=headers, cookies=cookie_dict, impersonate="firefox", timeout=12)
        time.sleep(1.0)
    except Exception as e:
        print(f"  ⚠️ Options Scraper: Failed to establish session connection: {e}")
        return {}
        
    print(f"  📡 Options Scraper: Fetching live OI for {len(symbols)} symbols concurrently...")
    start_time = time.time()
    
    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(fetch_symbol_oi, session, sym, cookie_dict, headers): sym for sym in symbols}
        for future in as_completed(futures):
            sym, res = future.result()
            if res:
                results[sym] = res
                
    end_time = time.time()
    print(f"  ✅ Options Scraper: Completed in {end_time - start_time:.2f} seconds. Retrieved {len(results)} symbols.")
    return results
