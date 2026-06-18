import json
import os
import sqlite3
from datetime import datetime, timedelta

# Import local db manager
import db_manager

CONFIG_PATH = "/Users/sree/macd_momentum_tracker/config.json"
ALERTS_LOG_PATH = "/Users/sree/macd_momentum_tracker/alerts.log"
DASHBOARD_PATH = "/Users/sree/macd_momentum_tracker/alerts_dashboard.html"

def load_config():
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except:
        return {"momentum_threshold": 5.0, "min_macd_increase_alert": 0.2, "poll_interval_minutes": 2.0}

def has_alert_today(symbol, alert_type):
    today = datetime.now().strftime("%Y-%m-%d")
    db_path = "/Users/sree/macd_momentum_tracker/db/macd_history.db"
    if not os.path.exists(db_path):
        return False
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='alerts_triggered'")
    if not cursor.fetchone():
        conn.close()
        return False
    cursor.execute("""
        SELECT count(*) FROM alerts_triggered
        WHERE symbol = ? AND alert_type = ? AND timestamp LIKE ?
    """, (symbol, alert_type, f"{today}%"))
    count = cursor.fetchone()[0]
    conn.close()
    return count > 0

def get_latest_alerts_from_log(limit=50):
    if not os.path.exists(ALERTS_LOG_PATH):
        return []
    
    alerts = []
    try:
        with open(ALERTS_LOG_PATH, "r") as f:
            lines = f.readlines()
            for line in lines[-limit:]:
                try:
                    alerts.append(json.loads(line.strip()))
                except:
                    pass
    except Exception as e:
        print(f"Error reading alerts log: {e}")
    return list(reversed(alerts))

def fmt_vol(v):
    if v is None: return "—"
    if v >= 1000000: return f"{v/1000000:.2f}M"
    if v >= 1000: return f"{v/1000:.1f}K"
    return f"{v:.0f}"

def analyze_all_symbols(symbols):
    config = load_config()
    db_path = "/Users/sree/macd_momentum_tracker/db/macd_history.db"
    
    if not os.path.exists(db_path):
        return []
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    alerts_triggered = []
    timestamp_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    for symbol in symbols:
        # Fetch the last 2 records
        cursor.execute("""
            SELECT timestamp, price, macd_line, signal_line, histogram, rsi, volume, average_volume, total_ce_oi, total_pe_oi, pcr, futures_oi, futures_oi_change_pct
            FROM macd_records
            WHERE symbol = ?
            ORDER BY timestamp DESC
            LIMIT 2
        """, (symbol,))
        rows = cursor.fetchall()
        
        if len(rows) < 2:
            continue
            
        latest = rows[0]
        previous = rows[1]
        
        lat_time, lat_price, lat_macd, lat_signal, lat_hist, lat_rsi, lat_vol, lat_avg_vol, lat_ce_oi, lat_pe_oi, lat_pcr, lat_fut_oi, lat_fut_oi_chg = latest
        prev_time, prev_price, prev_macd, prev_signal, prev_hist, prev_rsi, prev_vol, prev_avg_vol, prev_ce_oi, prev_pe_oi, prev_pcr, prev_fut_oi, prev_fut_oi_chg = previous
        
        if None in (lat_macd, lat_signal, lat_hist, prev_macd, prev_signal, prev_hist):
            continue
            
        macd_diff = lat_macd - prev_macd
        hist_diff = lat_hist - prev_hist
        
        # Check Volume Dryup
        is_dryup = False
        if lat_vol is not None and lat_avg_vol is not None and lat_avg_vol > 0:
            ratio = (lat_vol / lat_avg_vol) * 100
            if ratio < 50.0:
                is_dryup = True

        alert_type = None
        message = ""
        severity = "INFO"
        
        # 1. Check Bullish Crossover
        if prev_hist <= 0 and lat_hist > 0:
            alert_type = "BULLISH_CROSSOVER"
            message = f"MACD Line crossed above Signal Line (Histogram: {lat_hist:.3f})"
            severity = "HIGH"
            
        # 2. Check Bearish Crossover
        elif prev_hist >= 0 and lat_hist < 0:
            alert_type = "BEARISH_CROSSOVER"
            message = f"MACD Line crossed below Signal Line (Histogram: {lat_hist:.3f})"
            severity = "HIGH"
            
        # 3. Check Crossing Momentum Threshold (MACD Line > 5)
        elif prev_macd <= config["momentum_threshold"] and lat_macd > config["momentum_threshold"]:
            alert_type = "MOMENTUM_START"
            message = f"MACD Line crossed above momentum threshold 5.0 (Current: {lat_macd:.3f})"
            severity = "CRITICAL"
            
        # 4. Check significant increase in MACD line
        elif macd_diff >= config["min_macd_increase_alert"]:
            alert_type = "MACD_INCREASE"
            message = f"MACD Line increased by {macd_diff:.3f} (Prev: {prev_macd:.3f} -> Lat: {lat_macd:.3f})"
            severity = "MEDIUM"
            
        # 5. Check significant acceleration (Histogram increase)
        elif hist_diff >= config["min_macd_increase_alert"]:
            alert_type = "HISTOGRAM_ACCELERATING"
            message = f"Histogram expanded by {hist_diff:.3f} (Prev: {prev_hist:.3f} -> Lat: {lat_hist:.3f})"
            severity = "MEDIUM"
            
        if alert_type:
            alert = {
                "timestamp": timestamp_str,
                "symbol": symbol,
                "price": lat_price,
                "alert_type": alert_type,
                "message": message,
                "severity": severity,
                "macd_line": lat_macd,
                "signal_line": lat_signal,
                "histogram": lat_hist,
                "macd_change": macd_diff,
                "histogram_change": hist_diff,
                "rsi": lat_rsi,
                "volume": lat_vol,
                "average_volume": lat_avg_vol,
                "total_ce_oi": lat_ce_oi,
                "total_pe_oi": lat_pe_oi,
                "pcr": lat_pcr,
                "futures_oi": lat_fut_oi,
                "futures_oi_change_pct": lat_fut_oi_chg
            }
            alerts_triggered.append(alert)
            
            with open(ALERTS_LOG_PATH, "a") as f_log:
                f_log.write(json.dumps(alert) + "\n")
                
            print(f"🔔 [{severity}] {symbol}: {message} (Price: ₹{lat_price})")

        # Check Volume Dryup Alert independently
        if is_dryup:
            if not has_alert_today(symbol, "VOLUME_DRYUP"):
                dry_alert = {
                    "timestamp": timestamp_str,
                    "symbol": symbol,
                    "price": lat_price,
                    "alert_type": "VOLUME_DRYUP",
                    "message": f"Volume Dry-up (Vol: {fmt_vol(lat_vol)} vs 10d Avg: {fmt_vol(lat_avg_vol)}, Ratio: {lat_vol/lat_avg_vol*100:.1f}%)",
                    "severity": "INFO",
                    "macd_line": lat_macd,
                    "signal_line": lat_signal,
                    "histogram": lat_hist,
                    "macd_change": macd_diff,
                    "histogram_change": hist_diff,
                    "rsi": lat_rsi,
                    "volume": lat_vol,
                    "average_volume": lat_avg_vol,
                    "total_ce_oi": lat_ce_oi,
                    "total_pe_oi": lat_pe_oi,
                    "pcr": lat_pcr,
                    "futures_oi": lat_fut_oi,
                    "futures_oi_change_pct": lat_fut_oi_chg
                }
                alerts_triggered.append(dry_alert)
                with open(ALERTS_LOG_PATH, "a") as f_log:
                    f_log.write(json.dumps(dry_alert) + "\n")
                print(f"🔔 [INFO] {symbol}: Volume Dry-up (Ratio: {lat_vol/lat_avg_vol*100:.1f}%)")
            
    conn.close()
    
    # Save alerts to database table alerts_triggered
    if alerts_triggered:
        db_alerts = []
        for a in alerts_triggered:
            db_alerts.append((
                a["timestamp"],
                a["symbol"],
                a["price"],
                a["alert_type"],
                a["message"],
                a["severity"],
                a["macd_line"],
                a["signal_line"],
                a["histogram"],
                a["macd_change"],
                a["histogram_change"],
                a["rsi"],
                a["volume"],
                a["average_volume"],
                a.get("total_ce_oi"),
                a.get("total_pe_oi"),
                a.get("pcr"),
                a.get("futures_oi"),
                a.get("futures_oi_change_pct")
            ))
        db_manager.insert_alerts(db_alerts)

    # Generate HTML Dashboard
    generate_dashboard(symbols)
    return alerts_triggered

def run_eod_retrospective(date_str=None):
    db_path = "/Users/sree/macd_momentum_tracker/db/macd_history.db"
    if not os.path.exists(db_path):
        return
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Check if table alert_retrospectives exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='alert_retrospectives'")
    if not cursor.fetchone():
        conn.close()
        return
        
    # If date_str is provided, run for that specific date. Otherwise scan the last 30 days
    if date_str:
        dates_to_eval = [date_str]
    else:
        threshold = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        cursor.execute("""
            SELECT DISTINCT substr(timestamp, 1, 10) as alert_date 
            FROM alerts_triggered
            WHERE timestamp >= ?
            ORDER BY alert_date ASC
        """, (threshold,))
        dates_to_eval = [row[0] for row in cursor.fetchall()]
        
    # Get current time for market close checks
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    
    for eval_date in dates_to_eval:
        # If it's today's date, only run if the market is closed (after 15:30)
        if eval_date == today_str:
            if now.hour < 15 or (now.hour == 15 and now.minute < 30):
                continue # Skip today's evaluation for now (market still open)
                
        # Get all alerts for eval_date that do not have a retrospective yet
        cursor.execute("""
            SELECT a.id, a.timestamp, a.symbol, a.price, a.alert_type, a.rsi, a.volume, a.average_volume
            FROM alerts_triggered a
            LEFT JOIN alert_retrospectives r ON a.timestamp = r.alert_timestamp AND a.symbol = r.symbol
            WHERE r.id IS NULL AND a.timestamp LIKE ?
        """, (f"{eval_date}%",))
        alerts = cursor.fetchall()
        
        if not alerts:
            continue
            
        # Fetch EOD Nifty price
        cursor.execute("""
            SELECT price FROM macd_records
            WHERE symbol = 'NSE:NIFTY' AND timestamp LIKE ?
            ORDER BY timestamp DESC
            LIMIT 1
        """, (f"{eval_date}%",))
        nifty_eod_row = cursor.fetchone()
        nifty_eod = nifty_eod_row[0] if nifty_eod_row else None
        
        retros_to_insert = []
        
        for alert_id, alert_time, symbol, signal_price, alert_type, rsi, vol, avg_vol in alerts:
            # Find EOD closing price for the symbol
            cursor.execute("""
                SELECT price, volume, average_volume, histogram FROM macd_records
                WHERE symbol = ? AND timestamp LIKE ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (symbol, f"{eval_date}%"))
            eod_row = cursor.fetchone()
            if not eod_row:
                continue
                
            eod_price, eod_vol, eod_avg_vol, eod_hist = eod_row
            
            # Calculate percentage change
            pct_change = ((eod_price - signal_price) / signal_price) * 100
            
            # Calculate Nifty index change after signal
            nifty_change = 0.0
            if nifty_eod:
                # Find Nifty price at the time of the alert
                cursor.execute("""
                    SELECT price FROM macd_records
                    WHERE symbol = 'NSE:NIFTY' AND timestamp <= ?
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (alert_time,))
                nifty_sig_row = cursor.fetchone()
                if nifty_sig_row:
                    nifty_sig = nifty_sig_row[0]
                    nifty_change = ((nifty_eod - nifty_sig) / nifty_sig) * 100
                    
            # Evaluate performance status & reason
            status = "NEUTRAL"
            reason = ""
            
            if alert_type in ("BULLISH_CROSSOVER", "MOMENTUM_START", "MACD_INCREASE", "HISTOGRAM_ACCELERATING"):
                if pct_change >= 0.8:
                    status = "SUCCESS"
                elif pct_change <= -0.5:
                    status = "FAILED"
                    # Determine failure reason
                    if rsi is not None and rsi >= 70:
                        reason = f"🔴 RSI Overbought Exhaustion (RSI: {rsi:.1f} at signal)"
                    elif nifty_change <= -0.3:
                        reason = f"📉 Broader Market Drag (Nifty fell {nifty_change:.2f}% after signal)"
                    elif vol is not None and avg_vol is not None and avg_vol > 0 and (vol / avg_vol) < 0.7:
                        reason = f"💧 Low Vol Follow-through (Vol Ratio: {vol/avg_vol*100:.1f}% at signal)"
                    elif eod_hist is not None and eod_hist < 0:
                        reason = "🔄 MACD Whipsaw (Histogram reversed to negative at EOD)"
                    else:
                        reason = "Consolidation / standard price pullback"
                else:
                    status = "NEUTRAL"
                    reason = "Consolidated within ±0.5% margin"
                    
            elif alert_type == "BEARISH_CROSSOVER":
                if pct_change <= -0.8:
                    status = "SUCCESS"
                elif pct_change >= 0.5:
                    status = "FAILED"
                    # Determine failure reason
                    if rsi is not None and rsi <= 30:
                        reason = f"🟢 RSI Oversold Bounce (RSI: {rsi:.1f} at signal)"
                    elif nifty_change >= 0.3:
                        reason = f"📈 Broader Market Rally (Nifty rose {nifty_change:.2f}% after signal)"
                    elif vol is not None and avg_vol is not None and avg_vol > 0 and (vol / avg_vol) < 0.7:
                        reason = f"💧 Low Vol Follow-through (Vol Ratio: {vol/avg_vol*100:.1f}% at signal)"
                    elif eod_hist is not None and eod_hist > 0:
                        reason = "🔄 MACD Whipsaw (Histogram reversed to positive at EOD)"
                    else:
                        reason = "Consolidation / standard price bounce"
                else:
                    status = "NEUTRAL"
                    reason = "Consolidated within ±0.5% margin"
                    
            elif alert_type == "VOLUME_DRYUP":
                # Breakout signal: we check for price expansion (>1.2% in either direction)
                abs_change = abs(pct_change)
                if abs_change >= 1.2:
                    status = "SUCCESS"
                    direction = "Bullish" if pct_change > 0 else "Bearish"
                    reason = f"⚡ Price breakout achieved ({direction} move of {pct_change:.2f}%)"
                else:
                    status = "NEUTRAL"
                    reason = "Price remained compressed (Breakout pending)"
                    
            eval_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            retros_to_insert.append((
                alert_time,
                symbol,
                alert_type,
                signal_price,
                eod_price,
                pct_change,
                status,
                reason,
                eval_time
            ))
            
        if retros_to_insert:
            db_manager.insert_retrospectives(retros_to_insert)
            print(f"  🔍 EOD Retrospective: Automatically evaluated {len(retros_to_insert)} alerts for {eval_date}.")
            
    conn.close()

def generate_dashboard(symbols):
    config = load_config()
    db_path = "/Users/sree/macd_momentum_tracker/db/macd_history.db"
    
    if not os.path.exists(db_path):
        return
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Fetch latest 2 records for all symbols to evaluate trends
    latest_snapshot = []
    for symbol in symbols:
        cursor.execute("""
            SELECT timestamp, price, macd_line, signal_line, histogram, rsi, volume, average_volume, total_ce_oi, total_pe_oi, pcr, futures_oi, futures_oi_change_pct, day_change
            FROM macd_records
            WHERE symbol = ?
            ORDER BY timestamp DESC
            LIMIT 2
        """, (symbol,))
        rows = cursor.fetchall()
        if rows:
            latest_snapshot.append((symbol, rows))
            
    # Fetch EOD retrospectives from database
    retros_rows = []
    try:
        cursor.execute("""
            SELECT alert_timestamp, symbol, alert_type, signal_price, eod_price, pct_change, status, failure_reason, eval_timestamp
            FROM alert_retrospectives
            ORDER BY alert_timestamp DESC
            LIMIT 300
        """)
        retros_rows = cursor.fetchall()
    except Exception as e:
        print(f"Error loading retrospectives: {e}")
             
    conn.close()
    
    # Process retrospectives by date
    retros_by_date = {}
    for r in retros_rows:
        alert_time, symbol, alert_type, signal_price, eod_price, pct_change, status, reason, eval_time = r
        date_part = alert_time.split()[0]
        if date_part not in retros_by_date:
            retros_by_date[date_part] = {
                "success": 0,
                "failed": 0,
                "neutral": 0,
                "total": 0,
                "items": []
            }
        
        retros_by_date[date_part]["total"] += 1
        if status == "SUCCESS":
            retros_by_date[date_part]["success"] += 1
        elif status == "FAILED":
            retros_by_date[date_part]["failed"] += 1
        else:
            retros_by_date[date_part]["neutral"] += 1
            
        retros_by_date[date_part]["items"].append(r)
        
    retro_html = ""
    if not retros_by_date:
        retro_html = """
        <div style="text-align: center; padding: 40px; color: var(--text-muted);">
            <h3>🔍 No EOD Retrospective evaluations run yet.</h3>
            <p style="margin-top: 8px; font-size: 13px;">EOD Retrospectives run automatically daily after 3:30 PM (15:30) market close, evaluating all intraday signals against closing prices.</p>
        </div>
        """
    else:
        for date_str, data in sorted(retros_by_date.items(), reverse=True):
            total = data["total"]
            success = data["success"]
            failed = data["failed"]
            neutral = data["neutral"]
            
            evaluated_total = success + failed
            win_rate = (success / evaluated_total * 100) if evaluated_total > 0 else 0.0
            win_rate_str = f"{win_rate:.1f}%" if evaluated_total > 0 else "N/A"
            
            status_color = "#10b981" if win_rate >= 60 else "#eab308" if win_rate >= 40 else "#ef4444"
            if evaluated_total == 0:
                status_color = "var(--text-muted)"
                
            item_rows = ""
            for item in data["items"]:
                alert_time, symbol, alert_type, sig_price, eod_price, pct_change, status, reason, eval_time = item
                
                status_badge_color = "#10b981" if status == "SUCCESS" else "#ef4444" if status == "FAILED" else "#9ca3af"
                change_style = "color: #10b981;" if pct_change > 0 else "color: #ef4444;" if pct_change < 0 else "color: var(--text-muted);"
                alert_type_display = alert_type.replace("_", " ")
                
                item_rows += f"""
                <tr>
                    <td>{alert_time.split()[1]}</td>
                    <td style="font-weight: bold; color: #fff;">{symbol}</td>
                    <td style="font-weight: 600;">{alert_type_display}</td>
                    <td>₹{sig_price:.2f}</td>
                    <td>₹{eod_price:.2f}</td>
                    <td style="{change_style} font-weight: bold;">{pct_change:+.2f}%</td>
                    <td><span style="background: {status_badge_color}20; color: {status_badge_color}; font-weight: bold; padding: 2px 8px; border-radius: 4px; font-size: 11px;">{status}</span></td>
                    <td style="color: #cbd5e1; font-size: 12px;">{reason or 'N/A'}</td>
                </tr>
                """
                
            retro_html += f"""
            <div class="card" style="margin-bottom: 16px;">
                <div style="display: flex; justify-content: space-between; align-items: center; cursor: pointer;" onclick="toggleCollapse('{date_str}')">
                    <div>
                        <h3 style="font-family: 'Outfit', sans-serif; font-size: 16px; color: #fff;">📅 Market Date: {date_str}</h3>
                        <div style="display: flex; gap: 12px; margin-top: 4px; font-size: 12px; color: var(--text-muted);">
                            <span>Total Signals: <strong>{total}</strong></span> |
                            <span style="color: #4ade80;">Success: <strong>{success}</strong></span> |
                            <span style="color: #f87171;">Failed: <strong>{failed}</strong></span> |
                            <span style="color: #9ca3af;">Neutral: <strong>{neutral}</strong></span>
                        </div>
                    </div>
                    <div style="text-align: right; display: flex; align-items: center; gap: 16px;">
                        <div>
                            <span style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; display: block;">EOD Win Rate</span>
                            <span style="color: {status_color}; font-size: 20px; font-weight: 800; font-family: 'Outfit', sans-serif;">{win_rate_str}</span>
                        </div>
                        <span id="arrow-{date_str}" style="font-size: 18px; color: var(--text-muted); transition: transform 0.2s;">▼</span>
                    </div>
                </div>
                
                <div id="content-{date_str}" style="display: none; margin-top: 16px; border-top: 1px solid var(--border); padding-top: 16px;">
                    <div class="table-wrap" style="max-height: 350px;">
                        <table>
                            <thead>
                                <tr>
                                    <th>Signal Time</th>
                                    <th>Symbol</th>
                                    <th>Signal Type</th>
                                    <th>Signal Price</th>
                                    <th>EOD Close</th>
                                    <th>Change %</th>
                                    <th>Outcome</th>
                                    <th>Post-Mortem Analysis / Reason</th>
                                </tr>
                            </thead>
                            <tbody>
                                {item_rows}
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
            """
            
    # Sort snapshot by latest MACD Line descending
    latest_snapshot.sort(key=lambda x: x[1][0][2] if x[1] and x[1][0][2] is not None else -999999, reverse=True)
    
    # Load recent alerts
    recent_alerts = get_latest_alerts_from_log(50)
    
    # Get DB size on disk
    size_mb = db_manager.get_db_size_mb()
    if size_mb < 1.0:
        size_str = f"{size_mb * 1024:.1f} KB"
    else:
        size_str = f"{size_mb:.2f} MB"
    
    # Build HTML rows for recent alerts
    alert_rows = ""
    for a in recent_alerts:
        sev_color = "#ef4444" if a["severity"] == "CRITICAL" else "#f97316" if a["severity"] == "HIGH" else "#eab308" if a["severity"] == "MEDIUM" else "#3b82f6"
        rsi_val = a.get("rsi")
        rsi_str = f"{rsi_val:.1f}" if rsi_val is not None else "—"
        alert_rows += f"""
        <tr>
            <td>{a["timestamp"]}</td>
            <td style="font-weight: bold; color: #fff;">{a["symbol"]}</td>
            <td>₹{a["price"]:.2f}</td>
            <td><span style="color: {sev_color}; font-weight: bold; background: {sev_color}18; padding: 2px 8px; border-radius: 12px; font-size: 11px;">{a["severity"]}</span></td>
            <td>{a["alert_type"]}</td>
            <td style="color: #cbd5e1;">{a["message"]}</td>
            <td>{a["macd_line"]:.3f}</td>
            <td>{rsi_str}</td>
        </tr>
        """
        
    # Build HTML rows for all symbols snapshot
    snapshot_rows = ""
    dryup_list = []
    for s_info in latest_snapshot:
        sym, rows = s_info
        if not rows:
            continue
            
        latest = rows[0]
        t_stamp, s_price, s_macd, s_sig, s_hist, s_rsi, s_vol, s_avg_vol, s_ce_oi, s_pe_oi, s_pcr, s_fut_oi, s_fut_oi_chg, s_day_chg = latest
        
        # Format daily price change
        day_chg_str = "—"
        day_chg_style = "color: #cbd5e1;"
        if s_day_chg is not None:
            day_chg_str = f"{s_day_chg:+.2f}%"
            if s_day_chg > 0:
                day_chg_style = "color: #10b981; font-weight: bold;"
            elif s_day_chg < 0:
                day_chg_style = "color: #ef4444; font-weight: bold;"
        
        if s_macd is None:
            continue
            
        # Calculate MACD Trend (15m change)
        trend_str = "—"
        trend_style = "color: var(--text-muted);"
        macd_change = 0.0
        has_prev = False
        if len(rows) >= 2:
            previous = rows[1]
            prev_macd = previous[2]
            prev_hist = previous[4]
            if prev_macd is not None:
                has_prev = True
                macd_change = s_macd - prev_macd
                if macd_change > 0.001:
                    trend_str = f"▲ +{macd_change:.3f}"
                    trend_style = "color: #10b981; font-weight: 600;"
                elif macd_change < -0.001:
                    trend_str = f"▼ {macd_change:.3f}"
                    trend_style = "color: #ef4444; font-weight: 600;"
                else:
                    trend_str = "▬ 0.000"
                    trend_style = "color: var(--text-muted);"
                    
        # Format RSI highlights
        rsi_str = "—"
        rsi_style = "color: #cbd5e1;"
        if s_rsi is not None:
            rsi_str = f"{s_rsi:.2f}"
            if s_rsi >= 70.0:
                rsi_style = "color: #ef4444; font-weight: bold; background: rgba(239, 68, 68, 0.15); padding: 2px 6px; border-radius: 4px;"
            elif s_rsi <= 30.0:
                rsi_style = "color: #10b981; font-weight: bold; background: rgba(16, 185, 129, 0.15); padding: 2px 6px; border-radius: 4px;"
                
        # Calculate Volume Ratio & Dry-up
        vol_ratio_str = "—"
        vol_ratio_style = "color: #cbd5e1;"
        is_dryup = False
        if s_vol is not None and s_avg_vol is not None and s_avg_vol > 0:
            ratio = (s_vol / s_avg_vol) * 100
            vol_ratio_str = f"{ratio:.1f}%"
            if ratio < 50.0:
                is_dryup = True
                vol_ratio_style = "color: #60a5fa; font-weight: bold; background: rgba(96, 165, 250, 0.15); padding: 2px 6px; border-radius: 4px;"
            elif ratio > 150.0:
                vol_ratio_style = "color: #fbbf24; font-weight: bold; background: rgba(251, 191, 36, 0.15); padding: 2px 6px; border-radius: 4px;"

        # Determine trend based on price change or MACD change fallback
        price_change = 0.0
        if len(rows) >= 2:
            prev_price = rows[1][1]
            if prev_price is not None:
                price_change = s_price - prev_price
        
        trend_up = price_change > 0 if price_change != 0 else (macd_change > 0 if has_prev else False)
        trend_down = price_change < 0 if price_change != 0 else (macd_change < 0 if has_prev else False)
        
        # Options / OI Interpretation Setup
        oi_setup = None
        if s_fut_oi_chg is not None:
            if s_fut_oi_chg > 1.5:
                if trend_up:
                    oi_setup = f"🐂 Long Buildup (OI +{s_fut_oi_chg:.1f}%)"
                elif trend_down:
                    oi_setup = f"🐻 Short Buildup (OI +{s_fut_oi_chg:.1f}%)"
            elif s_fut_oi_chg < -1.5:
                if trend_up:
                    oi_setup = f"🚀 Short Covering (OI {s_fut_oi_chg:.1f}%)"
                elif trend_down:
                    oi_setup = f"📉 Long Unwinding (OI {s_fut_oi_chg:.1f}%)"

        # Generate Smart Interpretation
        interp = "⚪ Neutral"
        interp_style = "color: var(--text-muted);"
        
        if oi_setup:
            interp = oi_setup
            if "Long Buildup" in oi_setup:
                interp_style = "color: #10b981; font-weight: bold; background: rgba(16, 185, 129, 0.1); padding: 2px 8px; border-radius: 6px;"
            elif "Short Buildup" in oi_setup:
                interp_style = "color: #ef4444; font-weight: bold; background: rgba(239, 68, 68, 0.1); padding: 2px 8px; border-radius: 6px;"
            elif "Short Covering" in oi_setup:
                interp_style = "color: #34d399; font-weight: bold; background: rgba(52, 211, 153, 0.1); padding: 2px 8px; border-radius: 6px;"
            elif "Long Unwinding" in oi_setup:
                interp_style = "color: #fbbf24; font-weight: bold; background: rgba(251, 191, 36, 0.1); padding: 2px 8px; border-radius: 6px;"
        else:
            if s_rsi is not None and s_rsi >= 70.0:
                interp = "🔴 Overbought (Exhaustion Risk)"
                interp_style = "color: #f87171; font-weight: 600;"
            elif s_rsi is not None and s_rsi <= 30.0:
                interp = "🟢 Oversold (Bounce Candidate)"
                interp_style = "color: #4ade80; font-weight: 600;"
            elif has_prev and prev_hist is not None and prev_hist <= 0 and s_hist > 0:
                interp = "🟢 Bullish Crossover (BUY)"
                interp_style = "color: #34d399; font-weight: bold; background: rgba(52, 211, 153, 0.1); padding: 2px 8px; border-radius: 6px;"
            elif has_prev and prev_hist is not None and prev_hist >= 0 and s_hist < 0:
                interp = "🔴 Bearish Crossover (EXIT)"
                interp_style = "color: #f87171; font-weight: bold; background: rgba(248, 113, 113, 0.1); padding: 2px 8px; border-radius: 6px;"
            elif s_macd > config["momentum_threshold"]:
                interp = "🔥 Strong Momentum"
                interp_style = "color: #fbbf24; font-weight: bold; text-shadow: 0 0 8px rgba(251, 191, 36, 0.2);"
            elif is_dryup:
                interp = "💧 Vol Dry-up (Watch Breakout)"
                interp_style = "color: #60a5fa; font-weight: bold; background: rgba(96, 165, 250, 0.1); padding: 2px 8px; border-radius: 6px;"
            elif has_prev and macd_change > config["min_macd_increase_alert"]:
                interp = "📈 Momentum Rising"
                interp_style = "color: #60a5fa; font-weight: 600;"
            elif s_hist > 0:
                if has_prev and prev_hist is not None and s_hist < prev_hist:
                    interp = "🟡 Bullish Weakening"
                    interp_style = "color: #fbbf24;"
                else:
                    interp = "🟢 Bullish Trend"
                    interp_style = "color: #34d399;"
            elif s_hist < 0:
                if has_prev and prev_hist is not None and s_hist > prev_hist:
                    interp = "🔵 Bearish Weakening (Covering)"
                    interp_style = "color: #60a5fa;"
                else:
                    interp = "🔴 Bearish Trend"
                    interp_style = "color: #f87171;"
        
        # Add volume dry-up suffix if combined with other signals
        if is_dryup and "Vol Dry-up" not in interp and interp != "⚪ Neutral":
            interp = f"{interp} + 💧 Dry-up"
            
        if is_dryup:
            # We store the required elements for the Dry-up Tab row
            dryup_list.append((
                sym, s_price, s_macd, s_sig, s_hist, trend_str, trend_style, rsi_str, rsi_style, s_vol, s_avg_vol, (s_vol / s_avg_vol) * 100, vol_ratio_style, interp, interp_style
            ))
            
        macd_color = "#22c55e" if s_macd > config["momentum_threshold"] else "#cbd5e1"
        hist_color = "#22c55e" if s_hist > 0 else "#ef4444"
        
        pcr_str = f"{s_pcr:.2f}" if s_pcr is not None else "—"
        pcr_style = "color: #cbd5e1;"
        if s_pcr is not None:
            if s_pcr >= 1.2:
                pcr_style = "color: #ef4444; font-weight: bold;"
            elif s_pcr <= 0.7:
                pcr_style = "color: #10b981; font-weight: bold;"
                
        oi_chg_str = "—"
        oi_chg_style = "color: #cbd5e1;"
        if s_fut_oi_chg is not None:
            oi_chg_str = f"{s_fut_oi_chg:+.2f}%"
            if s_fut_oi_chg > 1.5:
                oi_chg_style = "color: #10b981; font-weight: bold;"
            elif s_fut_oi_chg < -1.5:
                oi_chg_style = "color: #ef4444; font-weight: bold;"
                
        fut_oi_str = fmt_vol(s_fut_oi)

        snapshot_rows += f"""
        <tr>
            <td style="font-weight: bold; color: #fff;">{sym}</td>
            <td>₹{s_price:.2f}</td>
            <td style="{day_chg_style}">{day_chg_str}</td>
            <td style="color: {macd_color}; font-weight: bold;">{s_macd:.3f}</td>
            <td>{s_sig:.3f}</td>
            <td style="color: {hist_color}; font-weight: bold;">{s_hist:.3f}</td>
            <td style="{trend_style}">{trend_str}</td>
            <td style="{rsi_style}">{rsi_str}</td>
            <td>{fmt_vol(s_vol)}</td>
            <td>{fmt_vol(s_avg_vol)}</td>
            <td style="{vol_ratio_style}">{vol_ratio_str}</td>
            <td style="{pcr_style}">{pcr_str}</td>
            <td>{fut_oi_str}</td>
            <td style="{oi_chg_style}">{oi_chg_str}</td>
            <td style="{interp_style}">{interp}</td>
        </tr>
        """
        
    # Process dryup list: sort by ratio ascending (most compressed first)
    dryup_list.sort(key=lambda x: x[11] if x[11] is not None else 999999)
    
    dryup_rows = ""
    dryup_count = len(dryup_list)
    most_compressed_str = "—"
    avg_ratio_str = "—"
    
    if dryup_count > 0:
        ratios = [x[11] for x in dryup_list if x[11] is not None]
        avg_ratio = sum(ratios) / len(ratios) if ratios else 0
        avg_ratio_str = f"{avg_ratio:.1f}%"
        
        best = dryup_list[0]
        most_compressed_str = f"{best[0]} ({best[11]:.1f}%)"
        
        for item in dryup_list:
            sym, price, macd_val, sig_val, hist_val, tr_str, tr_style, r_str, r_style, vol_val, avg_vol_val, ratio_val, ratio_style, interp_val, interp_style = item
            
            dryup_rows += f"""
            <tr>
                <td style="font-weight: bold; color: #fff;">{sym}</td>
                <td>₹{price:.2f}</td>
                <td style="{ratio_style} font-weight: bold;">{ratio_val:.1f}%</td>
                <td>{fmt_vol(vol_val)}</td>
                <td>{fmt_vol(avg_vol_val)}</td>
                <td style="color: #cbd5e1; font-weight: bold;">{macd_val:.3f}</td>
                <td style="color: #cbd5e1; font-weight: bold;">{hist_val:.3f}</td>
                <td style="{tr_style}">{tr_str}</td>
                <td style="{r_style}">{r_str}</td>
                <td style="{interp_style}">{interp_val}</td>
            </tr>
            """
            
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MACD Momentum Tracker Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@400;600;800&family=Plus+Jakarta+Sans:wght@400;500;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #090d16;
            --surface: #111827;
            --surface-hover: #1f2937;
            --border: #374151;
            --text-main: #f3f4f6;
            --text-muted: #9ca3af;
            --primary: #3b82f6;
            --primary-hover: #2563eb;
            --accent: #10b981;
        }}
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        body {{
            background: var(--bg);
            color: var(--text-main);
            font-family: 'Plus Jakarta Sans', sans-serif;
            padding: 24px;
        }}
        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 20px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 16px;
        }}
        h1 {{ font-family: 'Outfit', sans-serif; font-weight: 800; font-size: 28px; background: linear-gradient(to right, #3b82f6, #10b981); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        .meta {{ font-size: 13px; color: var(--text-muted); }}
        
        .tabs-header {{
            display: flex;
            gap: 8px;
            margin-bottom: 20px;
            border-bottom: 1px solid var(--border);
            padding-bottom: 8px;
        }}
        .tab-btn {{
            background: transparent;
            border: 1px solid transparent;
            color: var(--text-muted);
            padding: 8px 16px;
            border-radius: 8px;
            cursor: pointer;
            font-weight: 600;
            font-size: 14px;
            font-family: 'Plus Jakarta Sans', sans-serif;
            transition: all 0.2s ease;
        }}
        .tab-btn:hover {{
            background: var(--surface-hover);
            color: #fff;
        }}
        .tab-btn.active {{
            background: var(--primary);
            color: #fff;
            border-color: var(--primary);
        }}
        .tab-content {{
            display: none;
        }}
        .tab-content.active-content {{
            display: block;
        }}

        .container {{ display: grid; grid-template-columns: 1fr; gap: 24px; }}
        .card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 20px;
            overflow: hidden;
            box-shadow: 0 4px 20px rgba(0,0,0,0.4);
            margin-bottom: 24px;
        }}
        h2 {{ font-family: 'Outfit', sans-serif; font-size: 18px; margin-bottom: 16px; color: #fff; display: flex; align-items: center; gap: 8px; }}
        
        /* Interactive Multi-column Filters */
        .filter-row input {{
            width: 100%;
            background: #0f172a;
            border: 1px solid var(--border);
            color: #fff;
            padding: 6px 10px;
            border-radius: 6px;
            font-size: 11px;
            outline: none;
            font-family: inherit;
            transition: all 0.15s ease;
        }}
        .filter-row input:focus {{
            border-color: var(--primary);
            box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.2);
        }}
        .btn-reset-filters {{
            background: #475569;
            color: white;
            border: none;
            padding: 6px 12px;
            border-radius: 6px;
            font-size: 11px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
        }}
        .btn-reset-filters:hover {{
            background: #334155;
        }}
        
        .table-wrap {{ max-height: 550px; overflow-y: auto; border-radius: 8px; border: 1px solid var(--border); }}
        table {{ width: 100%; border-collapse: collapse; text-align: left; font-size: 13px; }}
        th {{ background: #1e293b; color: var(--text-muted); font-weight: 600; padding: 10px 12px; position: sticky; top: 0; z-index: 10; border-bottom: 1px solid var(--border); text-transform: uppercase; font-size: 10px; letter-spacing: 0.05em; }}
        td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
        tr:hover {{ background: var(--surface-hover); }}
        .badge {{ display: inline-block; padding: 2px 6px; border-radius: 4px; font-weight: bold; font-size: 10px; }}
        
        .pulse {{
            width: 8px; height: 8px; background: var(--accent); border-radius: 50%; display: inline-block;
            box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); animation: pulsing 1.5s infinite;
        }}
        .db-info {{
            font-size: 11px; color: #3b82f6; background: rgba(59, 130, 246, 0.1);
            padding: 4px 10px; border-radius: 12px; border: 1px solid rgba(59, 130, 246, 0.3);
            display: inline-block; margin-top: 4px; font-weight: 600;
        }}
        
        .form-group {{
            margin-bottom: 20px;
        }}
        .form-group label {{
            display: block;
            margin-bottom: 6px;
            font-size: 13px;
            color: var(--text-muted);
            font-weight: 600;
        }}
        .form-group input {{
            width: 100%;
            max-width: 400px;
            background: #1e293b;
            border: 1px solid var(--border);
            color: #fff;
            padding: 10px 14px;
            border-radius: 8px;
            font-size: 14px;
            font-family: inherit;
            outline: none;
            transition: all 0.2s ease;
        }}
        .form-group input:focus {{
            border-color: var(--primary);
            box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.2);
        }}
        .btn-submit {{
            background: var(--primary);
            color: #fff;
            border: none;
            padding: 10px 20px;
            border-radius: 8px;
            font-size: 14px;
            font-weight: bold;
            cursor: pointer;
            transition: background 0.2s ease;
        }}
        .btn-submit:hover {{
            background: var(--primary-hover);
        }}
        
        .btn-fetch {{
            background: linear-gradient(135deg, #3b82f6, #1d4ed8);
            color: #fff;
            border: none;
            padding: 6px 14px;
            border-radius: 8px;
            font-size: 12px;
            font-weight: 600;
            font-family: 'Plus Jakarta Sans', sans-serif;
            cursor: pointer;
            transition: all 0.2s ease;
            box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
            display: inline-flex;
            align-items: center;
            gap: 6px;
            margin-top: 4px;
        }}
        .btn-fetch:hover {{
            background: linear-gradient(135deg, #2563eb, #1e40af);
            transform: translateY(-1px);
            box-shadow: 0 6px 16px rgba(59, 130, 246, 0.4);
        }}
        .btn-fetch:active {{
            transform: translateY(0);
        }}
        .btn-fetch:disabled {{
            background: #4b5563;
            cursor: not-allowed;
            box-shadow: none;
            transform: none;
            opacity: 0.7;
        }}
        
        .toast {{
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: #10b981;
            color: white;
            padding: 12px 24px;
            border-radius: 8px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
            font-weight: bold;
            display: none;
            z-index: 9999;
        }}

        @keyframes pulsing {{
            0% {{ transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }}
            70% {{ transform: scale(1); box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }}
            100% {{ transform: scale(0.95); box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }}
        }}
    </style>
</head>
<body>
    <header>
        <div>
            <h1>📊 MACD Momentum & Crossover Tracker</h1>
            <div style="display: flex; gap: 12px; align-items: center;">
                <span class="meta">Monitoring all F&O stocks every 2 minutes</span>
                <span class="db-info">🗄️ Database Disk Size: {size_str} (Capped at 30 Days)</span>
            </div>
        </div>
        <div style="text-align: right; display: flex; flex-direction: column; align-items: flex-end; gap: 4px;">
            <div class="meta" style="display: flex; align-items: center; gap: 8px; justify-content: flex-end;">
                <span class="pulse"></span> LIVE MONITORING
            </div>
            <div class="meta">Last Updated: <strong>{now_str}</strong></div>
            <button id="btn-force-fetch" onclick="triggerForceFetch()" class="btn-fetch">⚡ Force Fetch TV Data</button>
        </div>
    </header>
    
    <div class="tabs-header">
        <button id="btn-tab-dashboard" class="tab-btn active" onclick="switchTab('dashboard')">📊 Live Dashboard</button>
        <button id="btn-tab-dryup" class="tab-btn" onclick="switchTab('dryup')">💧 Volume Dry-up</button>
        <button id="btn-tab-retro" class="tab-btn" onclick="switchTab('retro')">🔍 EOD Retrospection</button>
        <button id="btn-tab-config" class="tab-btn" onclick="switchTab('config')">⚙️ Configuration</button>
    </div>
    
    <!-- Tab 1: Live Dashboard -->
    <div id="tab-dashboard" class="tab-content active-content">
        <div class="container">
            <!-- Alerts Log Card -->
            <div class="card">
                <h2>🔔 Recent Alerts Log (Latest 50)</h2>
                <div class="table-wrap" style="max-height: 200px; margin-bottom: 24px;">
                    <table>
                        <thead>
                            <tr>
                                <th>Time</th>
                                <th>Symbol</th>
                                <th>Price</th>
                                <th>Severity</th>
                                <th>Trigger</th>
                                <th>Message</th>
                                <th>MACD</th>
                                <th>RSI</th>
                            </tr>
                        </thead>
                        <tbody>
                            {alert_rows or '<tr><td colspan="8" style="text-align:center; padding: 30px; color: var(--text-muted);">No alerts logged yet. Awaiting next poll...</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
            
            <!-- F&O Snapshot Card -->
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                    <h2 style="margin-bottom: 0;">📈 Latest F&O Stock MACD, RSI & Volume Rankings</h2>
                    <button onclick="resetAllFilters()" class="btn-reset-filters">🧹 Clear Filters</button>
                </div>
                
                <div class="table-wrap" style="max-height: 500px;">
                    <table id="snapshot-table">
                        <thead>
                            <tr>
                                <th>Symbol</th>
                                <th>Price</th>
                                <th>Day Chg %</th>
                                <th>MACD (15m)</th>
                                <th>Signal</th>
                                <th>Hist</th>
                                <th>MACD Trend</th>
                                <th>RSI (15m)</th>
                                <th>Today's Vol</th>
                                <th>Avg Vol (10d)</th>
                                <th>Vol Ratio</th>
                                <th>Option PCR</th>
                                <th>Futures OI</th>
                                <th>OI Chg %</th>
                                <th>Interpretation</th>
                            </tr>
                            <tr class="filter-row">
                                <td><input type="text" id="flt-symbol" oninput="applyAllFilters()" placeholder="Filter symbol..."></td>
                                <td><input type="text" id="flt-price" oninput="applyAllFilters()" placeholder="e.g. >1000"></td>
                                <td><input type="text" id="flt-day-change" oninput="applyAllFilters()" placeholder="e.g. >1"></td>
                                <td><input type="text" id="flt-macd" oninput="applyAllFilters()" placeholder="e.g. >5"></td>
                                <td><input type="text" id="flt-signal" oninput="applyAllFilters()" placeholder="e.g. >5"></td>
                                <td><input type="text" id="flt-hist" oninput="applyAllFilters()" placeholder="e.g. >0"></td>
                                <td><input type="text" id="flt-trend" oninput="applyAllFilters()" placeholder="e.g. >0.1"></td>
                                <td><input type="text" id="flt-rsi" oninput="applyAllFilters()" placeholder="e.g. >70"></td>
                                <td><input type="text" id="flt-vol" oninput="applyAllFilters()" placeholder="e.g. >1M"></td>
                                <td><input type="text" id="flt-avg-vol" oninput="applyAllFilters()" placeholder="e.g. >1M"></td>
                                <td><input type="text" id="flt-ratio" oninput="applyAllFilters()" placeholder="e.g. <50"></td>
                                <td><input type="text" id="flt-pcr" oninput="applyAllFilters()" placeholder="e.g. >0.9"></td>
                                <td><input type="text" id="flt-fut-oi" oninput="applyAllFilters()" placeholder="e.g. >10M"></td>
                                <td><input type="text" id="flt-oi-chg" oninput="applyAllFilters()" placeholder="e.g. >2%"></td>
                                <td><input type="text" id="flt-interp" oninput="applyAllFilters()" placeholder="Filter signal..."></td>
                            </tr>
                        </thead>
                        <tbody id="snapshot-table-body">
                            {snapshot_rows or '<tr><td colspan="15" style="text-align:center; padding: 30px; color: var(--text-muted);">No snapshot data in database.</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Tab 4: Volume Dry-up Watchlist -->
    <div id="tab-dryup" class="tab-content">
        <div class="container">
            <!-- Stats cards -->
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px; margin-bottom: 24px;">
                <div class="card" style="margin-bottom: 0; padding: 16px; display: flex; align-items: center; gap: 16px;">
                    <div style="font-size: 32px;">💧</div>
                    <div>
                        <span style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; display: block;">Total Dry-up Stocks</span>
                        <span style="font-size: 24px; font-weight: 800; color: #60a5fa; font-family: 'Outfit', sans-serif;">{dryup_count}</span>
                    </div>
                </div>
                <div class="card" style="margin-bottom: 0; padding: 16px; display: flex; align-items: center; gap: 16px;">
                    <div style="font-size: 32px;">🌀</div>
                    <div>
                        <span style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; display: block;">Most Compressed (Lowest Ratio)</span>
                        <span style="font-size: 16px; font-weight: 800; color: #fbbf24; font-family: 'Outfit', sans-serif;">{most_compressed_str}</span>
                    </div>
                </div>
                <div class="card" style="margin-bottom: 0; padding: 16px; display: flex; align-items: center; gap: 16px;">
                    <div style="font-size: 32px;">📊</div>
                    <div>
                        <span style="font-size: 11px; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.05em; display: block;">Average Dry-up Ratio</span>
                        <span style="font-size: 24px; font-weight: 800; color: #34d399; font-family: 'Outfit', sans-serif;">{avg_ratio_str}</span>
                    </div>
                </div>
            </div>

            <!-- F&O Volume Dry-up List Card -->
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                    <h2 style="margin-bottom: 0;">💧 Active Volume Dry-up Watchlist (Sorted by Compression Ratio)</h2>
                    <button onclick="resetAllFilters()" class="btn-reset-filters">🧹 Clear Filters</button>
                </div>
                
                <div class="table-wrap" style="max-height: 500px;">
                    <table id="dryup-table">
                        <thead>
                            <tr>
                                <th>Symbol</th>
                                <th>Price</th>
                                <th>Vol Ratio</th>
                                <th>Today's Vol</th>
                                <th>Avg Vol (10d)</th>
                                <th>MACD (15m)</th>
                                <th>Hist</th>
                                <th>MACD Trend</th>
                                <th>RSI (15m)</th>
                                <th>Interpretation</th>
                            </tr>
                            <tr class="filter-row">
                                <td><input type="text" id="flt-dry-symbol" oninput="applyAllDryupFilters()" placeholder="Filter symbol..."></td>
                                <td><input type="text" id="flt-dry-price" oninput="applyAllDryupFilters()" placeholder="e.g. >1000"></td>
                                <td><input type="text" id="flt-dry-ratio" oninput="applyAllDryupFilters()" placeholder="e.g. <30"></td>
                                <td><input type="text" id="flt-dry-vol" oninput="applyAllDryupFilters()" placeholder="e.g. >100K"></td>
                                <td><input type="text" id="flt-dry-avg-vol" oninput="applyAllDryupFilters()" placeholder="e.g. >100K"></td>
                                <td><input type="text" id="flt-dry-macd" oninput="applyAllDryupFilters()" placeholder="e.g. >0"></td>
                                <td><input type="text" id="flt-dry-hist" oninput="applyAllDryupFilters()" placeholder="e.g. >0"></td>
                                <td><input type="text" id="flt-dry-trend" oninput="applyAllDryupFilters()" placeholder="e.g. >0"></td>
                                <td><input type="text" id="flt-dry-rsi" oninput="applyAllDryupFilters()" placeholder="e.g. >50"></td>
                                <td><input type="text" id="flt-dry-interp" oninput="applyAllDryupFilters()" placeholder="Filter signal..."></td>
                            </tr>
                        </thead>
                        <tbody id="dryup-table-body">
                            {dryup_rows or '<tr><td colspan="10" style="text-align:center; padding: 30px; color: var(--text-muted);">No active volume dry-ups detected.</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Tab 3: EOD Retrospection -->
    <div id="tab-retro" class="tab-content">
        <div class="container" style="max-width: 1100px; margin: 0 auto;">
            <div style="margin-bottom: 20px;">
                <h2 style="font-family: 'Outfit', sans-serif; font-size: 22px; color: #fff; margin-bottom: 4px;">🔍 End-Of-Day Prediction Retrospection</h2>
                <p style="font-size: 13px; color: var(--text-muted);">
                    Evaluates accuracy of alerts generated throughout the day against 3:30 PM closing prices, performing automated diagnostic analyses on failed signals.
                </p>
            </div>
            {retro_html}
        </div>
    </div>
    
    <!-- Tab 2: Configurations Panel -->
    <div id="tab-config" class="tab-content">
        <div class="card" style="max-width: 600px; margin: 0 auto;">
            <h2>⚙️ System Configurations</h2>
            <div style="margin-bottom: 20px; font-size: 13px; color: var(--text-muted);">
                Modify the operational parameters of the tracking daemon. Changes are applied dynamically on the next poll.
            </div>
            
            <div class="form-group">
                <label for="inp-interval">🕒 Poll Interval (Minutes)</label>
                <input type="number" step="0.5" min="0.5" id="inp-interval">
            </div>
            
            <div class="form-group">
                <label for="inp-momentum">🔥 MACD Momentum Threshold (e.g. 5.0)</label>
                <input type="number" step="0.1" id="inp-momentum">
            </div>
            
            <div class="form-group">
                <label for="inp-increase">📈 Alert Trigger MACD Increase (Minimum Change)</label>
                <input type="number" step="0.05" id="inp-increase">
            </div>
            
            <button class="btn-submit" onclick="saveConfig()">💾 Save Configuration</button>
        </div>
    </div>
    
    <div id="toast" class="toast">Settings saved successfully!</div>
    
    <script>
        function switchTab(tabName) {{
            document.querySelectorAll('.tab-btn').forEach(btn => btn.classList.remove('active'));
            document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active-content'));
            
            if (tabName === 'dashboard') {{
                document.getElementById('btn-tab-dashboard').classList.add('active');
                document.getElementById('tab-dashboard').classList.add('active-content');
                localStorage.setItem('activeTab', 'dashboard');
            }} else if (tabName === 'dryup') {{
                document.getElementById('btn-tab-dryup').classList.add('active');
                document.getElementById('tab-dryup').classList.add('active-content');
                localStorage.setItem('activeTab', 'dryup');
            }} else if (tabName === 'retro') {{
                document.getElementById('btn-tab-retro').classList.add('active');
                document.getElementById('tab-retro').classList.add('active-content');
                localStorage.setItem('activeTab', 'retro');
            }} else {{
                document.getElementById('btn-tab-config').classList.add('active');
                document.getElementById('tab-config').classList.add('active-content');
                localStorage.setItem('activeTab', 'config');
            }}
        }}
        
        function toggleCollapse(dateId) {{
            const content = document.getElementById('content-' + dateId);
            const arrow = document.getElementById('arrow-' + dateId);
            if (content.style.display === 'none') {{
                content.style.display = 'block';
                arrow.style.transform = 'rotate(180deg)';
            }} else {{
                content.style.display = 'none';
                arrow.style.transform = 'rotate(0deg)';
            }}
        }}
        
        const savedTab = localStorage.getItem('activeTab') || 'dashboard';
        switchTab(savedTab);
        
        setInterval(() => {{
            const currentTab = localStorage.getItem('activeTab') || 'dashboard';
            if (currentTab === 'dashboard' || currentTab === 'dryup') {{
                location.reload();
            }}
        }}, 30000);
        
        // Convert abbreviations like 1.5M to raw numbers for JS comparisons
        function parseAbbreviatedValue(valStr) {{
            const str = valStr.trim().toUpperCase();
            if (str === "") return NaN;
            
            let factor = 1;
            let numStr = str;
            
            if (str.endsWith('M')) {{
                factor = 1000000;
                numStr = str.slice(0, -1);
            }} else if (str.endsWith('K')) {{
                factor = 1000;
                numStr = str.slice(0, -1);
            }} else if (str.endsWith('L')) {{
                factor = 100000;
                numStr = str.slice(0, -1);
            }} else if (str.endsWith('CR')) {{
                factor = 10000000;
                numStr = str.slice(0, -2);
            }} else if (str.endsWith('%')) {{
                numStr = str.slice(0, -1);
            }}
            
            return parseFloat(numStr) * factor;
        }}
        
        // Multi-column filter evaluations
        function evaluateFilter(cellText, filterExpression) {{
            if (!filterExpression) return true;
            
            const expr = filterExpression.trim();
            if (expr === "") return true;
            
            // Strip formatting characters from cell text (like ₹, ▲, ▼, %, spaces)
            const valText = cellText.replace(/[₹▼▲ %]/g, '').trim();
            const cellVal = parseAbbreviatedValue(valText);
            
            if (isNaN(cellVal)) return false;
            
            let op = '=';
            let numStr = expr;
            
            if (expr.startsWith('>=')) {{
                op = '>=';
                numStr = expr.substring(2);
            }} else if (expr.startsWith('<=')) {{
                op = '<=';
                numStr = expr.substring(2);
            }} else if (expr.startsWith('>')) {{
                op = '>';
                numStr = expr.substring(1);
            }} else if (expr.startsWith('<')) {{
                op = '<';
                numStr = expr.substring(1);
            }} else if (expr.startsWith('=')) {{
                op = '=';
                numStr = expr.substring(1);
            }}
            
            const filterVal = parseAbbreviatedValue(numStr);
            if (isNaN(filterVal)) {{
                return cellText.toLowerCase().includes(expr.toLowerCase());
            }}
            
            if (op === '>') return cellVal > filterVal;
            if (op === '<') return cellVal < filterVal;
            if (op === '>=') return cellVal >= filterVal;
            if (op === '<=') return cellVal <= filterVal;
            if (op === '=') return Math.abs(cellVal - filterVal) < 0.001;
            
            return true;
        }}
        
        function applyAllFilters() {{
            const filters = {{
                symbol: document.getElementById('flt-symbol').value,
                price: document.getElementById('flt-price').value,
                day_change: document.getElementById('flt-day-change').value,
                macd: document.getElementById('flt-macd').value,
                signal: document.getElementById('flt-signal').value,
                hist: document.getElementById('flt-hist').value,
                trend: document.getElementById('flt-trend').value,
                rsi: document.getElementById('flt-rsi').value,
                vol: document.getElementById('flt-vol').value,
                avg_vol: document.getElementById('flt-avg-vol').value,
                ratio: document.getElementById('flt-ratio').value,
                pcr: document.getElementById('flt-pcr').value,
                fut_oi: document.getElementById('flt-fut-oi').value,
                oi_chg: document.getElementById('flt-oi-chg').value,
                interp: document.getElementById('flt-interp').value
            }};
            
            localStorage.setItem('macd_multi_filters_vol', JSON.stringify(filters));
            
            const rows = document.querySelectorAll('#snapshot-table-body tr');
            rows.forEach(row => {{
                const cells = row.getElementsByTagName('td');
                if (cells.length >= 15) {{
                    const matchSymbol = cells[0].textContent.toLowerCase().includes(filters.symbol.toLowerCase().trim());
                    const matchPrice = evaluateFilter(cells[1].textContent, filters.price);
                    const matchDayChange = evaluateFilter(cells[2].textContent, filters.day_change);
                    const matchMacd = evaluateFilter(cells[3].textContent, filters.macd);
                    const matchSignal = evaluateFilter(cells[4].textContent, filters.signal);
                    const matchHist = evaluateFilter(cells[5].textContent, filters.hist);
                    const matchTrend = evaluateFilter(cells[6].textContent, filters.trend);
                    const matchRsi = evaluateFilter(cells[7].textContent, filters.rsi);
                    const matchVol = evaluateFilter(cells[8].textContent, filters.vol);
                    const matchAvgVol = evaluateFilter(cells[9].textContent, filters.avg_vol);
                    const matchRatio = evaluateFilter(cells[10].textContent, filters.ratio);
                    const matchPcr = evaluateFilter(cells[11].textContent, filters.pcr);
                    const matchFutOi = evaluateFilter(cells[12].textContent, filters.fut_oi);
                    const matchOiChg = evaluateFilter(cells[13].textContent, filters.oi_chg);
                    const matchInterp = cells[14].textContent.toLowerCase().includes(filters.interp.toLowerCase().trim());
                    
                    const matchesAll = matchSymbol && matchPrice && matchDayChange && matchMacd && matchSignal && 
                                       matchHist && matchTrend && matchRsi && matchVol && 
                                       matchAvgVol && matchRatio && matchPcr && matchFutOi && matchOiChg && matchInterp;
                    row.style.display = matchesAll ? '' : 'none';
                }}
            }});
        }}
        
        function applyAllDryupFilters() {{
            const filters = {{
                symbol: document.getElementById('flt-dry-symbol').value,
                price: document.getElementById('flt-dry-price').value,
                ratio: document.getElementById('flt-dry-ratio').value,
                vol: document.getElementById('flt-dry-vol').value,
                avg_vol: document.getElementById('flt-dry-avg-vol').value,
                macd: document.getElementById('flt-dry-macd').value,
                hist: document.getElementById('flt-dry-hist').value,
                trend: document.getElementById('flt-dry-trend').value,
                rsi: document.getElementById('flt-dry-rsi').value,
                interp: document.getElementById('flt-dry-interp').value
            }};
            
            localStorage.setItem('macd_multi_filters_dryup', JSON.stringify(filters));
            
            const rows = document.querySelectorAll('#dryup-table-body tr');
            rows.forEach(row => {{
                const cells = row.getElementsByTagName('td');
                if (cells.length >= 10) {{
                    const matchSymbol = cells[0].textContent.toLowerCase().includes(filters.symbol.toLowerCase().trim());
                    const matchPrice = evaluateFilter(cells[1].textContent, filters.price);
                    const matchRatio = evaluateFilter(cells[2].textContent, filters.ratio);
                    const matchVol = evaluateFilter(cells[3].textContent, filters.vol);
                    const matchAvgVol = evaluateFilter(cells[4].textContent, filters.avg_vol);
                    const matchMacd = evaluateFilter(cells[5].textContent, filters.macd);
                    const matchHist = evaluateFilter(cells[6].textContent, filters.hist);
                    const matchTrend = evaluateFilter(cells[7].textContent, filters.trend);
                    const matchRsi = evaluateFilter(cells[8].textContent, filters.rsi);
                    const matchInterp = cells[9].textContent.toLowerCase().includes(filters.interp.toLowerCase().trim());
                    
                    const matchesAll = matchSymbol && matchPrice && matchRatio && matchVol && 
                                       matchAvgVol && matchMacd && matchHist && matchTrend && 
                                       matchRsi && matchInterp;
                    row.style.display = matchesAll ? '' : 'none';
                }}
            }});
        }}
        
        function resetAllFilters() {{
            document.querySelectorAll('.filter-row input').forEach(input => input.value = '');
            localStorage.removeItem('macd_multi_filters_vol');
            localStorage.removeItem('macd_multi_filters_dryup');
            const rows1 = document.querySelectorAll('#snapshot-table-body tr');
            rows1.forEach(row => row.style.display = '');
            const rows2 = document.querySelectorAll('#dryup-table-body tr');
            rows2.forEach(row => row.style.display = '');
        }}
        
        function restoreFilters() {{
            const saved = localStorage.getItem('macd_multi_filters_vol');
            if (saved) {{
                try {{
                    const filters = JSON.parse(saved);
                    document.getElementById('flt-symbol').value = filters.symbol || '';
                    document.getElementById('flt-price').value = filters.price || '';
                    document.getElementById('flt-day-change').value = filters.day_change || '';
                    document.getElementById('flt-macd').value = filters.macd || '';
                    document.getElementById('flt-signal').value = filters.signal || '';
                    document.getElementById('flt-hist').value = filters.hist || '';
                    document.getElementById('flt-trend').value = filters.trend || '';
                    document.getElementById('flt-rsi').value = filters.rsi || '';
                    document.getElementById('flt-vol').value = filters.vol || '';
                    document.getElementById('flt-avg-vol').value = filters.avg_vol || '';
                    document.getElementById('flt-ratio').value = filters.ratio || '';
                    document.getElementById('flt-pcr').value = filters.pcr || '';
                    document.getElementById('flt-fut-oi').value = filters.fut_oi || '';
                    document.getElementById('flt-oi-chg').value = filters.oi_chg || '';
                    document.getElementById('flt-interp').value = filters.interp || '';
                    applyAllFilters();
                }} catch(e) {{
                    console.error("Error restoring filters:", e);
                }}
            }}
            
            const savedDry = localStorage.getItem('macd_multi_filters_dryup');
            if (savedDry) {{
                try {{
                    const filters = JSON.parse(savedDry);
                    document.getElementById('flt-dry-symbol').value = filters.symbol || '';
                    document.getElementById('flt-dry-price').value = filters.price || '';
                    document.getElementById('flt-dry-ratio').value = filters.ratio || '';
                    document.getElementById('flt-dry-vol').value = filters.vol || '';
                    document.getElementById('flt-dry-avg-vol').value = filters.avg_vol || '';
                    document.getElementById('flt-dry-macd').value = filters.macd || '';
                    document.getElementById('flt-dry-hist').value = filters.hist || '';
                    document.getElementById('flt-dry-trend').value = filters.trend || '';
                    document.getElementById('flt-dry-rsi').value = filters.rsi || '';
                    document.getElementById('flt-dry-interp').value = filters.interp || '';
                    applyAllDryupFilters();
                }} catch(e) {{
                    console.error("Error restoring dryup filters:", e);
                }}
            }}
        }}
        
        async function loadConfig() {{
            try {{
                const r = await fetch('/config');
                if (r.ok) {{
                    const cfg = await r.json();
                    document.getElementById('inp-interval').value = cfg.poll_interval_minutes;
                    document.getElementById('inp-momentum').value = cfg.momentum_threshold;
                    document.getElementById('inp-increase').value = cfg.min_macd_increase_alert;
                }}
            }} catch (e) {{
                console.error("Error loading config:", e);
            }}
        }}
        
        async function saveConfig() {{
            const payload = {{
                poll_interval_minutes: parseFloat(document.getElementById('inp-interval').value),
                momentum_threshold: parseFloat(document.getElementById('inp-momentum').value),
                min_macd_increase_alert: parseFloat(document.getElementById('inp-increase').value)
            }};
            
            try {{
                const r = await fetch('/config', {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(payload)
                }});
                if (r.ok) {{
                    showToast("Settings saved successfully! Interval will update on next check.", false);
                }} else {{
                    showToast("Error saving settings.", true);
                }}
            }} catch (e) {{
                showToast("Connection failed.", true);
            }}
        }}
        
        async function triggerForceFetch() {{
            const btn = document.getElementById('btn-force-fetch');
            const originalText = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = '⏳ Fetching TV Data...';
            
            try {{
                const r = await fetch('/force_fetch', {{
                    method: 'POST'
                }});
                
                if (r.ok) {{
                    showToast("⚡ TradingView data force fetched successfully!", false);
                    setTimeout(() => {{
                        location.reload();
                    }}, 1000);
                }} else {{
                    let errMsg = "Error triggering force fetch.";
                    try {{
                        const errData = await r.json();
                        if (errData && errData.error) errMsg = errData.error;
                    }} catch (e) {{}}
                    showToast(errMsg, true);
                    btn.disabled = false;
                    btn.innerHTML = originalText;
                }}
            }} catch (e) {{
                showToast("Connection failed.", true);
                btn.disabled = false;
                btn.innerHTML = originalText;
            }}
        }}
        
        function showToast(msg, isError) {{
            const toast = document.getElementById('toast');
            toast.textContent = msg;
            toast.style.background = isError ? '#ef4444' : '#10b981';
            toast.style.display = 'block';
            setTimeout(() => {{
                toast.style.display = 'none';
            }}, 4000);
        }}
        
        loadConfig();
        setTimeout(restoreFilters, 100);
    </script>
</body>
</html>
"""
    with open(DASHBOARD_PATH, "w") as f_out:
        f_out.write(html)
    print(f"📊 Live alerts dashboard updated at {DASHBOARD_PATH} (DB Size: {size_str})")

if __name__ == "__main__":
    with open("/Users/sree/macd_momentum_tracker/watchlist.json", "r") as f:
        syms = json.load(f)
    analyze_all_symbols(syms)
