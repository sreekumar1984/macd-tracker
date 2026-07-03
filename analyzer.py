import json
import os
import sqlite3
from datetime import datetime, timedelta
import logging

logger = logging.getLogger("tracker")

# Import local db manager
import db_manager

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
ALERTS_LOG_PATH = os.path.join(BASE_DIR, "alerts.log")
DASHBOARD_PATH = os.path.join(BASE_DIR, "alerts_dashboard.html")

TRACKER_LOG_PATH = os.path.join(BASE_DIR, "tracker.log")

def tail_file(filepath, lines_count=200):
    """
    Reads the last `lines_count` lines of a file efficiently without loading the whole file into memory.
    """
    if not os.path.exists(filepath):
        return []
    
    block_size = 4096
    try:
        with open(filepath, 'rb') as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            
            data = []
            lines_found = 0
            
            while file_size > 0 and lines_found < lines_count + 1:
                if file_size - block_size > 0:
                    f.seek(file_size - block_size)
                    chunk = f.read(block_size)
                    file_size -= block_size
                else:
                    f.seek(0)
                    chunk = f.read(file_size)
                    file_size = 0
                    
                data.insert(0, chunk)
                lines_found += chunk.count(b'\n')
                
            combined = b''.join(data)
            lines = combined.splitlines()
            last_lines = lines[-lines_count:]
            return [line.decode('utf-8', errors='ignore') for line in last_lines]
    except Exception as e:
        print(f"Error tailing file {filepath}: {e}")
        # Fallback to readlines
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
                return lines[-lines_count:]
        except:
            return []

def get_latest_tracker_logs(limit=200):
    if not os.path.exists(TRACKER_LOG_PATH):
        return "No system logs found yet. Ensure the daemon has started."
    try:
        lines = tail_file(TRACKER_LOG_PATH, limit)
        return "\n".join(lines) + ("\n" if lines else "")
    except Exception as e:
        return f"Error reading logs: {e}"

def load_config():
    default_profiles = {
        "BULLISH_CROSSOVER": {
            "enabled": True,
            "sound_type": "chirp",
            "custom_frequencies": "523.25, 659.25, 783.99",
            "custom_durations": "0.08, 0.08, 0.18",
            "custom_wave": "sine"
        },
        "BEARISH_CROSSOVER": {
            "enabled": True,
            "sound_type": "warning",
            "custom_frequencies": "392.00, 329.63, 261.63",
            "custom_durations": "0.1, 0.1, 0.22",
            "custom_wave": "triangle"
        },
        "MOMENTUM_START": {
            "enabled": True,
            "sound_type": "siren",
            "custom_frequencies": "880.00, 660.00, 880.00, 660.00",
            "custom_durations": "0.12, 0.12, 0.12, 0.22",
            "custom_wave": "sawtooth"
        },
        "VOLUME_DRYUP": {
            "enabled": True,
            "sound_type": "double-chirp",
            "custom_frequencies": "659.25, 783.99, 0, 659.25, 783.99",
            "custom_durations": "0.06, 0.06, 0.04, 0.06, 0.12",
            "custom_wave": "sine"
        },
        "HIGH_VOLUME": {
            "enabled": True,
            "sound_type": "tada",
            "custom_frequencies": "440.00, 440.00, 554.37, 659.25",
            "custom_durations": "0.08, 0.08, 0.1, 0.25",
            "custom_wave": "sine"
        },
        "MACD_INCREASE": {
            "enabled": False,
            "sound_type": "beep",
            "custom_frequencies": "523.25",
            "custom_durations": "0.15",
            "custom_wave": "sine"
        },
        "HISTOGRAM_ACCELERATING": {
            "enabled": False,
            "sound_type": "beep",
            "custom_frequencies": "523.25",
            "custom_durations": "0.15",
            "custom_wave": "sine"
        }
    }

    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                cfg = json.load(f)
                # Ensure defaults for configuration keys
                cfg.setdefault("min_volume_ratio_alert", 2.0)
                cfg.setdefault("audio_alerts_enabled", True)
                cfg.setdefault("audio_play_on_startup", True)
                
                # Merge profile defaults
                profiles = cfg.setdefault("audio_alert_profiles", {})
                for k, v in default_profiles.items():
                    if k not in profiles:
                        profiles[k] = v
                    else:
                        for sub_k, sub_v in v.items():
                            profiles[k].setdefault(sub_k, sub_v)
                return cfg
        except Exception as e:
            print(f"Error loading config.json: {e}")
            
    return {
        "poll_interval_minutes": 2.0,
        "database_path": "db/macd_history.db",
        "momentum_threshold": 5.0,
        "min_macd_increase_alert": 0.2,
        "min_volume_ratio_alert": 2.0,
        "audio_alerts_enabled": True,
        "audio_play_on_startup": True,
        "audio_alert_profiles": default_profiles
    }

def has_alert_today(symbol, alert_type):
    today = datetime.now().strftime("%Y-%m-%d")
    db_path = os.path.join(BASE_DIR, "db/macd_history.db")
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
        lines = tail_file(ALERTS_LOG_PATH, limit)
        for line in lines:
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

def check_condition(condition, alert):
    try:
        vol = alert.get("volume")
        avg_vol = alert.get("average_volume")
        ratio = (vol / avg_vol) if (vol is not None and avg_vol is not None and avg_vol > 0) else None
        
        rsi = alert.get("rsi")
        pcr = alert.get("pcr")
        oi_chg = alert.get("futures_oi_change_pct")
        hist_day = alert.get("macd_hist_day")
        
        cond_lower = condition.lower()
        
        # Parse compound expert rules
        if condition == "Volume Ratio >= 1.0 and RSI < 65":
            if ratio is None or ratio < 1.0 or rsi is None or rsi >= 65:
                return False
            return True
        elif condition == "RSI > 35 and PCR <= 1.1":
            if rsi is None or rsi <= 35 or pcr is None or pcr > 1.1:
                return False
            return True
        elif condition == "Volume Ratio < 0.45 and RSI between 40 and 60":
            if ratio is None or ratio >= 0.45 or rsi is None or not (40 <= rsi <= 60):
                return False
            return True
        elif condition == "Volume Ratio >= 1.2 and RSI < 65":
            if ratio is None or ratio < 1.2 or rsi is None or rsi >= 65:
                return False
            return True
        elif condition == "macd_hist_day > 0 and RSI < 65":
            if hist_day is None or hist_day <= 0 or rsi is None or rsi >= 65:
                return False
            return True
        elif condition == "Volume Ratio >= 1.5":
            if ratio is None or ratio < 1.5:
                return False
            return True
            
        # Parse single conditions dynamically
        if "volume ratio >= " in cond_lower:
            parts = cond_lower.split("volume ratio >= ")
            val = float(parts[1].split()[0])
            if ratio is None or ratio < val:
                return False
        elif "volume ratio < " in cond_lower:
            parts = cond_lower.split("volume ratio < ")
            val = float(parts[1].split()[0])
            if ratio is None or ratio >= val:
                return False
                
        if "rsi < " in cond_lower:
            parts = cond_lower.split("rsi < ")
            val = float(parts[1].split()[0])
            if rsi is None or rsi >= val:
                return False
        elif "rsi > " in cond_lower:
            parts = cond_lower.split("rsi > ")
            val = float(parts[1].split()[0])
            if rsi is None or rsi <= val:
                return False
                
        if "option pcr >= " in cond_lower:
            parts = cond_lower.split("option pcr >= ")
            val = float(parts[1].split()[0])
            if pcr is None or pcr < val:
                return False
        elif "option pcr <= " in cond_lower:
            parts = cond_lower.split("option pcr <= ")
            val = float(parts[1].split()[0])
            if pcr is None or pcr > val:
                return False
                
        if "futures oi change > " in cond_lower or "futures oi change >= " in cond_lower:
            if oi_chg is None or oi_chg <= 0:
                return False
                
        if "rsi between 40 and 60" in cond_lower:
            if rsi is None or not (40 <= rsi <= 60):
                return False
                
        if "macd_hist_day > 0" in cond_lower:
            if hist_day is None or hist_day <= 0:
                return False
                
        return True
    except Exception as e:
        print(f"Error evaluating condition '{condition}': {e}")
        return True

def optimize_dataset(dataset, alert_type):
    # Include Neutral in the evaluation
    total_eval = [r for r in dataset if r['status'] in ('SUCCESS', 'FAILED', 'NEUTRAL')]
    total_count = len(total_eval)
    if total_count < 3: # Min 3 samples to optimize
        return None
        
    successes = len([r for r in total_eval if r['status'] == 'SUCCESS'])
    
    baseline_win_rate = (successes / total_count * 100) if total_count > 0 else 0.0
    
    candidates = []
    is_bullish = alert_type in ("BULLISH_CROSSOVER", "MOMENTUM_START", "MACD_INCREASE", "HISTOGRAM_ACCELERATING")
    is_bearish = alert_type in ("BEARISH_CROSSOVER")
    
    # 1. RSI Candidates
    if is_bullish:
        for rsi_val in [55, 60, 65, 70]:
            subset = [r for r in total_eval if r['rsi'] is not None and r['rsi'] < rsi_val]
            sub_success = len([r for r in subset if r['status'] == 'SUCCESS'])
            sub_total = len(subset)
            if sub_total >= 2 and sub_total >= total_count * 0.15:
                wr = (sub_success / sub_total * 100)
                candidates.append({
                    "condition": f"RSI < {rsi_val}",
                    "win_rate": wr,
                    "filtered": total_count - sub_total,
                    "success_kept": sub_success,
                    "desc": f"Prevents entering at potential overbought exhaustion levels above {rsi_val}."
                })
    elif is_bearish:
        for rsi_val in [30, 35, 40, 45]:
            subset = [r for r in total_eval if r['rsi'] is not None and r['rsi'] > rsi_val]
            sub_success = len([r for r in subset if r['status'] == 'SUCCESS'])
            sub_total = len(subset)
            if sub_total >= 2 and sub_total >= total_count * 0.15:
                wr = (sub_success / sub_total * 100)
                candidates.append({
                    "condition": f"RSI > {rsi_val}",
                    "win_rate": wr,
                    "filtered": total_count - sub_total,
                    "success_kept": sub_success,
                    "desc": f"Prevents shorting near potential oversold support levels below {rsi_val}."
                })
                
    # 2. Volume Ratio Candidates
    for vol_ratio in [0.8, 1.0, 1.2, 1.5]:
        subset = []
        for r in total_eval:
            vol = r['volume']
            avg_vol = r['average_volume']
            if vol is not None and avg_vol and avg_vol > 0:
                ratio = vol / avg_vol
                if ratio >= vol_ratio:
                    subset.append(r)
        sub_success = len([r for r in subset if r['status'] == 'SUCCESS'])
        sub_total = len(subset)
        if sub_total >= 2 and sub_total >= total_count * 0.15:
            wr = (sub_success / sub_total * 100)
            candidates.append({
                "condition": f"Volume Ratio >= {vol_ratio:.1f}",
                "win_rate": wr,
                "filtered": total_count - sub_total,
                "success_kept": sub_success,
                "desc": f"Filters out weak volume moves by requiring traded volume to be >= {vol_ratio*100:.0f}% of average."
            })
            
    # 3. PCR Candidates
    if is_bullish:
        for pcr_val in [0.8, 0.9, 1.0]:
            subset = [r for r in total_eval if r['pcr'] is not None and r['pcr'] >= pcr_val]
            sub_success = len([r for r in subset if r['status'] == 'SUCCESS'])
            sub_total = len(subset)
            if sub_total >= 2 and sub_total >= total_count * 0.15:
                wr = (sub_success / sub_total * 100)
                candidates.append({
                    "condition": f"Option PCR >= {pcr_val:.1f}",
                    "win_rate": wr,
                    "filtered": total_count - sub_total,
                    "success_kept": sub_success,
                    "desc": "Ensures bullish options positioning prior to entry."
                })
    elif is_bearish:
        for pcr_val in [1.2, 1.1, 1.0]:
            subset = [r for r in total_eval if r['pcr'] is not None and r['pcr'] <= pcr_val]
            sub_success = len([r for r in subset if r['status'] == 'SUCCESS'])
            sub_total = len(subset)
            if sub_total >= 2 and sub_total >= total_count * 0.15:
                wr = (sub_success / sub_total * 100)
                candidates.append({
                    "condition": f"Option PCR <= {pcr_val:.1f}",
                    "win_rate": wr,
                    "filtered": total_count - sub_total,
                    "success_kept": sub_success,
                    "desc": "Ensures bearish options positioning prior to entry."
                })
                
    # 4. Futures OI Candidates
    subset = [r for r in total_eval if r['futures_oi_change_pct'] is not None and r['futures_oi_change_pct'] > 0.0]
    sub_success = len([r for r in subset if r['status'] == 'SUCCESS'])
    sub_total = len(subset)
    if sub_total >= 2 and sub_total >= total_count * 0.15:
        wr = (sub_success / sub_total * 100)
        candidates.append({
            "condition": "Futures OI Change > 0%",
            "win_rate": wr,
            "filtered": total_count - sub_total,
            "success_kept": sub_success,
            "desc": "Verifies that open interest is actively rising (buildup) to support the move."
        })
        
    # Filter candidates that improve win rate
    candidates = [c for c in candidates if c['win_rate'] > baseline_win_rate + 0.5]
    candidates.sort(key=lambda c: (c['win_rate'], -c['filtered']), reverse=True)
    
    if candidates:
        return {
            "best": candidates[0],
            "baseline_win_rate": baseline_win_rate
        }
    return None

def run_optimization_analysis():
    db_path = "/Users/sree/macd_momentum_tracker/db/macd_history.db"
    if not os.path.exists(db_path):
        return {}
        
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT 
                r.alert_type, r.status, r.pct_change, r.symbol,
                a.rsi, a.volume, a.average_volume, a.pcr, a.futures_oi_change_pct,
                a.macd_line, a.signal_line, a.histogram, a.macd_45, a.macd_signal_45, a.macd_hist_45,
                a.macd_day, a.macd_signal_day, a.macd_hist_day, a.rsi_day
            FROM alert_retrospectives r
            JOIN alerts_triggered a ON a.timestamp = r.alert_timestamp AND a.symbol = r.symbol
        """)
        rows = cursor.fetchall()
    except Exception as e:
        print(f"Error loading optimization data: {e}")
        conn.close()
        return {}
        
    conn.close()
    
    expert_rules = {
        "BULLISH_CROSSOVER": {
            "rule_name": "Volume & RSI Confirmation",
            "condition": "Volume Ratio >= 1.0 and RSI < 65",
            "desc": "Ensures strong volume support and avoids buying at extreme overbought levels.",
            "impact": "+14.5% Win Rate (Expert Estimate)",
            "is_dynamic": False,
            "metrics": "Filters out ~30% of high-risk signals"
        },
        "BEARISH_CROSSOVER": {
            "rule_name": "RSI & PCR Confirmation",
            "condition": "RSI > 35 and PCR <= 1.1",
            "desc": "Avoids shorting at oversold zones and ensures option interest supports bearish movement.",
            "impact": "+12.0% Win Rate (Expert Estimate)",
            "is_dynamic": False,
            "metrics": "Filters out ~25% of false breakdowns"
        },
        "VOLUME_DRYUP": {
            "rule_name": "Compression Squeeze Validation",
            "condition": "Volume Ratio < 0.45 and RSI between 40 and 60",
            "desc": "Validates that volume is extremely low and price is in equilibrium before a breakout.",
            "impact": "+18.0% Win Rate (Expert Estimate)",
            "is_dynamic": False,
            "metrics": "Improves breakout conviction"
        },
        "MACD_INCREASE": {
            "rule_name": "MACD Acceleration Filter",
            "condition": "MACD Hist Change > 0.05",
            "desc": "Confirms that the momentum is accelerating before logging an increase trigger.",
            "impact": "+10.5% Win Rate (Expert Estimate)",
            "is_dynamic": False,
            "metrics": "Filters standard choppy markets"
        },
        "MOMENTUM_START": {
            "rule_name": "Trend Momentum Confirmation",
            "condition": "Volume Ratio >= 1.1 and RSI > 45",
            "desc": "Ensures momentum is backed by volume and does not trigger in a flat range.",
            "impact": "+13.0% Win Rate (Expert Estimate)",
            "is_dynamic": False,
            "metrics": "Avoids weak breakout traps"
        },
        "HISTOGRAM_ACCELERATING": {
            "rule_name": "Histogram Thrust Confirmation",
            "condition": "Volume Ratio >= 1.2 and Histogram > 0.1",
            "desc": "Confirms histogram momentum is supported by real traded volume.",
            "impact": "+15.0% Win Rate (Expert Estimate)",
            "is_dynamic": False,
            "metrics": "Filters out false breakouts"
        }
    }
    
    if not rows or len(rows) < 3:
        return {
            "is_dynamic": False,
            "sample_size": len(rows) if rows else 0,
            "rules": expert_rules,
            "symbols": {}
        }
        
    # Group by alert type for global rules
    by_type = {}
    for row in rows:
        alert_type = row['alert_type']
        if alert_type not in by_type:
            by_type[alert_type] = []
        by_type[alert_type].append(row)
        
    global_rules = {}
    for alert_type in expert_rules.keys():
        dataset = by_type.get(alert_type, [])
        res = optimize_dataset(dataset, alert_type)
        if res:
            best = res["best"]
            base_wr = res["baseline_win_rate"]
            global_rules[alert_type] = {
                "rule_name": f"Optimized {best['condition']}",
                "condition": best['condition'],
                "desc": best['desc'],
                "impact": f"{base_wr:.1f}% → {best['win_rate']:.1f}% Win Rate (+{best['win_rate'] - base_wr:.1f}%)",
                "is_dynamic": True,
                "metrics": f"Prevents {best['filtered']} low-conviction signals"
            }
        else:
            global_rules[alert_type] = expert_rules[alert_type]
            
    # Group by symbol and alert_type for symbol-specific rules
    by_symbol_and_type = {}
    for row in rows:
        symbol = row['symbol']
        alert_type = row['alert_type']
        if symbol not in by_symbol_and_type:
            by_symbol_and_type[symbol] = {}
        if alert_type not in by_symbol_and_type[symbol]:
            by_symbol_and_type[symbol][alert_type] = []
        by_symbol_and_type[symbol][alert_type].append(row)
        
    symbol_rules = {}
    for symbol, type_datasets in by_symbol_and_type.items():
        for alert_type, dataset in type_datasets.items():
            res = optimize_dataset(dataset, alert_type)
            if res:
                best = res["best"]
                base_wr = res["baseline_win_rate"]
                if symbol not in symbol_rules:
                    symbol_rules[symbol] = {}
                symbol_rules[symbol][alert_type] = {
                    "rule_name": f"Custom {best['condition']}",
                    "condition": best['condition'],
                    "desc": best['desc'],
                    "impact": f"{base_wr:.1f}% → {best['win_rate']:.1f}% Win Rate (+{best['win_rate'] - base_wr:.1f}%)",
                    "is_dynamic": True,
                    "metrics": f"Prevents {best['filtered']} low-conviction signals",
                    "sample_size": len(dataset)
                }
                
    return {
        "is_dynamic": True,
        "sample_size": len(rows),
        "rules": global_rules,
        "symbols": symbol_rules
    }

def apply_adaptive_filter(alert, config):
    if not config.get("enable_adaptive_ai_filters", False):
        return alert
        
    rules_path = "/Users/sree/macd_momentum_tracker/db/optimized_rules.json"
    rules_data = {}
    if os.path.exists(rules_path):
        try:
            with open(rules_path, "r") as f:
                rules_data = json.load(f)
        except Exception as e:
            print(f"Error loading optimized rules: {e}")
            
    if not rules_data:
        rules_data = run_optimization_analysis()
        if rules_data:
            try:
                with open(rules_path, "w") as f:
                    json.dump(rules_data, f, indent=2)
            except Exception as e:
                print(f"Error saving optimized rules: {e}")
                
    symbol = alert.get("symbol")
    alert_type = alert.get("alert_type")
    
    # Check symbol-specific custom rules first
    symbol_rules = rules_data.get("symbols", {}).get(symbol, {}) if rules_data else {}
    rule = symbol_rules.get(alert_type)
    rule_source = "Symbol Custom"
    
    if not rule and rules_data:
        # Fall back to global rule
        rules = rules_data.get("rules", {})
        rule = rules.get(alert_type)
        rule_source = "Global AI"
        
    if rule:
        passed = check_condition(rule["condition"], alert)
        if not passed:
            alert["severity"] = "LOW_CONVICTION"
            alert["message"] = alert["message"] + f" [Low Conviction - AI Suppressed ({rule_source})]"
    return alert

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
            SELECT timestamp, price, day_change, macd_line, signal_line, histogram, rsi, volume, average_volume, total_ce_oi, total_pe_oi, pcr, futures_oi, futures_oi_change_pct, rsi_30, rsi_60, macd_day, macd_signal_day, macd_hist_day, rsi_day, macd_45, macd_signal_45, macd_hist_45
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
        
        lat_time, lat_price, lat_day_change, lat_macd, lat_signal, lat_hist, lat_rsi, lat_vol, lat_avg_vol, lat_ce_oi, lat_pe_oi, lat_pcr, lat_fut_oi, lat_fut_oi_chg, lat_rsi_30, lat_rsi_60, lat_macd_day, lat_macd_signal_day, lat_macd_hist_day, lat_rsi_day, lat_macd_45, lat_macd_signal_45, lat_macd_hist_45 = latest
        prev_time, prev_price, prev_day_change, prev_macd, prev_signal, prev_hist, prev_rsi, prev_vol, prev_avg_vol, prev_ce_oi, prev_pe_oi, prev_pcr, prev_fut_oi, prev_fut_oi_chg, prev_rsi_30, prev_rsi_60, prev_macd_day, prev_macd_signal_day, prev_macd_hist_day, prev_rsi_day, prev_macd_45, prev_macd_signal_45, prev_macd_hist_45 = previous
        
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
            message = f"MACD Line crossed above momentum threshold {config['momentum_threshold']:.1f} (Current: {lat_macd:.3f})"
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
                "day_change": lat_day_change,
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
                "futures_oi_change_pct": lat_fut_oi_chg,
                "rsi_30": lat_rsi_30,
                "rsi_60": lat_rsi_60,
                "macd_day": lat_macd_day,
                "macd_signal_day": lat_macd_signal_day,
                "macd_hist_day": lat_macd_hist_day,
                "rsi_day": lat_rsi_day,
                "macd_45": lat_macd_45,
                "macd_signal_45": lat_macd_signal_45,
                "macd_hist_45": lat_macd_hist_45
            }
            alert = apply_adaptive_filter(alert, config)
            alerts_triggered.append(alert)
            
            with open(ALERTS_LOG_PATH, "a") as f_log:
                f_log.write(json.dumps(alert) + "\n")
                
            print(f"🔔 [{alert['severity']}] {symbol}: {alert['message']} (Price: ₹{lat_price})")

        # Check Volume Dryup Alert independently
        if is_dryup:
            if not has_alert_today(symbol, "VOLUME_DRYUP"):
                dry_alert = {
                    "timestamp": timestamp_str,
                    "symbol": symbol,
                    "price": lat_price,
                    "day_change": lat_day_change,
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
                    "futures_oi_change_pct": lat_fut_oi_chg,
                    "rsi_30": lat_rsi_30,
                    "rsi_60": lat_rsi_60,
                    "macd_day": lat_macd_day,
                    "macd_signal_day": lat_macd_signal_day,
                    "macd_hist_day": lat_macd_hist_day,
                    "rsi_day": lat_rsi_day,
                    "macd_45": lat_macd_45,
                    "macd_signal_45": lat_macd_signal_45,
                    "macd_hist_45": lat_macd_hist_45
                }
                dry_alert = apply_adaptive_filter(dry_alert, config)
                alerts_triggered.append(dry_alert)
                with open(ALERTS_LOG_PATH, "a") as f_log:
                    f_log.write(json.dumps(dry_alert) + "\n")
                print(f"🔔 [{dry_alert['severity']}] {symbol}: {dry_alert['message']}")

        # Check High Volume Ratio Alert independently
        if lat_vol is not None and lat_avg_vol is not None and lat_avg_vol > 0:
            vol_ratio = lat_vol / lat_avg_vol
            min_ratio = config.get("min_volume_ratio_alert", 2.0)
            if vol_ratio >= min_ratio:
                if not has_alert_today(symbol, "HIGH_VOLUME"):
                    high_vol_alert = {
                        "timestamp": timestamp_str,
                        "symbol": symbol,
                        "price": lat_price,
                        "day_change": lat_day_change,
                        "alert_type": "HIGH_VOLUME",
                        "message": f"High Volume Alert (Vol: {fmt_vol(lat_vol)} vs 10d Avg: {fmt_vol(lat_avg_vol)}, Ratio: {vol_ratio:.2f}x)",
                        "severity": "HIGH",
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
                        "futures_oi_change_pct": lat_fut_oi_chg,
                        "rsi_30": lat_rsi_30,
                        "rsi_60": lat_rsi_60,
                        "macd_day": lat_macd_day,
                        "macd_signal_day": lat_macd_signal_day,
                        "macd_hist_day": lat_macd_hist_day,
                        "rsi_day": lat_rsi_day,
                        "macd_45": lat_macd_45,
                        "macd_signal_45": lat_macd_signal_45,
                        "macd_hist_45": lat_macd_hist_45
                    }
                    high_vol_alert = apply_adaptive_filter(high_vol_alert, config)
                    alerts_triggered.append(high_vol_alert)
                    with open(ALERTS_LOG_PATH, "a") as f_log:
                        f_log.write(json.dumps(high_vol_alert) + "\n")
                    print(f"🔔 [{high_vol_alert['severity']}] {symbol}: {high_vol_alert['message']}")
            
    conn.close()
    
    # Save alerts to database table alerts_triggered
    if alerts_triggered:
        db_alerts = []
        for a in alerts_triggered:
            db_alerts.append((
                a["timestamp"],
                a["symbol"],
                a["price"],
                a.get("day_change"),
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
                a.get("futures_oi_change_pct"),
                a.get("rsi_30"),
                a.get("rsi_60"),
                a.get("macd_day"),
                a.get("macd_signal_day"),
                a.get("macd_hist_day"),
                a.get("rsi_day"),
                a.get("macd_45"),
                a.get("macd_signal_45"),
                a.get("macd_hist_45")
            ))
        db_manager.insert_alerts(db_alerts)

    # Generate HTML Dashboard
    generate_dashboard(symbols)
    return alerts_triggered

def run_eod_retrospective(date_str=None, force=False):
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
        
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    logger.info(f"🔍 [Retrospective] Starting EOD retrospective evaluation. Force evaluate: {force}")
    
    for eval_date in dates_to_eval:
        # If it's today's date, only run if the market is closed (after 15:30) or if forced manually
        if eval_date == today_str and not force:
            if now.hour < 15 or (now.hour == 15 and now.minute < 30):
                continue # Skip today's evaluation for now (market still open)
                
        if force:
            # Delete existing retrospective entries for this date to allow clean re-evaluation and detailed logging
            cursor.execute("DELETE FROM alert_retrospectives WHERE alert_timestamp LIKE ?", (f"{eval_date}%",))
            conn.commit()
            logger.info(f"🔄 [Retrospective] Cleared existing EOD records for {eval_date} to force re-evaluation.")
                
        # Get all alerts for eval_date that do not have a retrospective yet
        cursor.execute("""
            SELECT a.id, a.timestamp, a.symbol, a.price, a.alert_type, a.rsi, a.volume, a.average_volume, a.pcr, a.histogram
            FROM alerts_triggered a
            LEFT JOIN alert_retrospectives r ON a.timestamp = r.alert_timestamp AND a.symbol = r.symbol
            WHERE r.id IS NULL AND a.timestamp LIKE ?
        """, (f"{eval_date}%",))
        alerts = cursor.fetchall()
        
        if not alerts:
            logger.info(f"🔍 [Retrospective] No new alerts found to evaluate for date: {eval_date}")
            continue
            
        logger.info(f"🔍 [Retrospective] Evaluating {len(alerts)} alerts for date: {eval_date}")
            
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
        
        for alert_id, alert_time, symbol, signal_price, alert_type, rsi, vol, avg_vol, pcr, sig_hist in alerts:
            # Find EOD closing price and indicators for the symbol
            cursor.execute("""
                SELECT price, volume, average_volume, histogram, rsi, pcr FROM macd_records
                WHERE symbol = ? AND timestamp LIKE ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (symbol, f"{eval_date}%"))
            eod_row = cursor.fetchone()
            if not eod_row:
                continue
                
            eod_price, eod_vol, eod_avg_vol, eod_hist, eod_rsi, eod_pcr = eod_row
            
            # Calculate percentage change
            pct_change = ((eod_price - signal_price) / signal_price) * 100
            
            # Calculate volume ratios
            sig_vol_ratio = (vol / avg_vol * 100) if (vol is not None and avg_vol and avg_vol > 0) else None
            eod_vol_ratio = (eod_vol / eod_avg_vol * 100) if (eod_vol is not None and eod_avg_vol and eod_avg_vol > 0) else None
            
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
                    
            elif alert_type == "HIGH_VOLUME":
                # High volume breakout: check for positive close change
                if pct_change >= 0.8:
                    status = "SUCCESS"
                    reason = f"⚡ High volume breakout succeeded (Price change {pct_change:.2f}%)"
                elif pct_change <= -0.5:
                    status = "FAILED"
                    reason = f"🔴 Fake breakout / reversal (Price fell {pct_change:.2f}%)"
                else:
                    status = "NEUTRAL"
                    reason = f"Consolidated within standard range (Price change {pct_change:.2f}%)"
                    
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
                eval_time,
                rsi,              # signal_rsi
                eod_rsi,          # eod_rsi
                sig_vol_ratio,    # signal_vol_ratio
                eod_vol_ratio,    # eod_vol_ratio
                pcr,              # signal_pcr
                eod_pcr,          # eod_pcr
                nifty_change,     # nifty_change
                sig_hist,         # signal_hist
                eod_hist          # eod_hist
            ))
            
            log_msg = f"🔍 [Retrospective] Evaluated {symbol} ({alert_type}) | Signal Price: ₹{signal_price:.2f} | EOD Price: ₹{eod_price:.2f} ({pct_change:+.2f}%) | Status: {status}"
            if reason:
                log_msg += f" (Reason: {reason})"
            logger.info(log_msg)
            
        if retros_to_insert:
            db_manager.insert_retrospectives(retros_to_insert)
            logger.info(f"🔍 [Retrospective] Saved {len(retros_to_insert)} evaluated retrospective records to database.")
            try:
                logger.info("🤖 [Retrospective] Triggering AI Optimizer parameter tuning based on new retrospective data...")
                opt_data = run_optimization_analysis()
                if opt_data:
                    rules_path = "/Users/sree/macd_momentum_tracker/db/optimized_rules.json"
                    with open(rules_path, "w") as f:
                        json.dump(opt_data, f, indent=2)
                    logger.info("🤖 [Retrospective] AI Optimizer parameter rules recalculated and saved.")
            except Exception as opt_err:
                logger.error(f"⚠️ [Retrospective] Error running optimization rules update: {opt_err}")
            
    conn.close()

def generate_dashboard(symbols):
    config = load_config()
    alert_types_meta = [
        ("BULLISH_CROSSOVER", "🐂 Bullish Crossover"),
        ("BEARISH_CROSSOVER", "🐻 Bearish Crossover"),
        ("MOMENTUM_START", "🔥 Momentum Start (Critical)"),
        ("VOLUME_DRYUP", "💧 Volume Dry-up"),
        ("HIGH_VOLUME", "📊 High Volume Alert"),
        ("MACD_INCREASE", "📈 MACD Line Increase"),
        ("HISTOGRAM_ACCELERATING", "🚀 Histogram Acceleration")
    ]
    
    sound_cards_html = ""
    for atype, display in alert_types_meta:
        sound_cards_html += f"""
        <div style="background: rgba(15, 23, 42, 0.4); border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 12px;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                <label style="font-weight: bold; color: #fff; display: flex; align-items: center; gap: 8px; cursor: pointer; font-size: 13px;">
                    <input type="checkbox" id="cfg-sound-enabled-{atype}" style="width: 16px; height: 16px; cursor: pointer; accent-color: var(--primary);"> {display}
                </label>
                <button onclick="testTone('{atype}')" class="btn-reset-filters" style="padding: 4px 10px; font-size: 11px;">⚡ Test Tone</button>
            </div>
            <div style="display: grid; grid-template-columns: 1fr; gap: 8px;">
                <div class="form-group" style="margin-bottom: 4px;">
                    <label style="font-size: 11px; color: var(--text-muted); display: block; margin-bottom: 4px;">Sound Preset / Alert Tone</label>
                    <select id="sound-type-{atype}" onchange="toggleCustomSoundInputs('{atype}')" style="width: 100%; max-width: 100%; background:#1e293b; color:#fff; border:1px solid var(--border); border-radius:6px; padding:6px; font-size:12px; outline:none;">
                        <option value="chirp">Chirp (Ascending)</option>
                        <option value="warning">Warning Buzz (Descending)</option>
                        <option value="siren">Siren (Alert)</option>
                        <option value="double-chirp">Double Chirp</option>
                        <option value="tada">Tada Fanfare</option>
                        <option value="bell">Bell Chime</option>
                        <option value="beep">Simple Beep</option>
                        <option value="beep-low">Low Beep</option>
                        <option value="double-beep">Double Beep</option>
                        <option value="buzz">Low Buzz</option>
                        <option value="custom">🛠️ Custom Notes</option>
                        <option value="none">Disabled</option>
                    </select>
                </div>
                <div id="custom-fields-{atype}" style="display: none; background: rgba(0,0,0,0.25); padding: 10px; border-radius: 8px; border: 1px dashed var(--border);">
                    <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px;">
                        <div class="form-group" style="margin-bottom: 0;">
                            <label style="font-size: 10px; color: var(--text-muted); display: block; margin-bottom: 2px;">Frequencies (Hz, csv)</label>
                            <input type="text" id="sound-freq-{atype}" placeholder="523.25, 659.25" style="width: 100%; font-size:11px; padding:4px 6px; background:#0f172a; border:1px solid var(--border); color:#fff; border-radius:4px;">
                        </div>
                        <div class="form-group" style="margin-bottom: 0;">
                            <label style="font-size: 10px; color: var(--text-muted); display: block; margin-bottom: 2px;">Durations (sec, csv)</label>
                            <input type="text" id="sound-dur-{atype}" placeholder="0.1, 0.15" style="width: 100%; font-size:11px; padding:4px 6px; background:#0f172a; border:1px solid var(--border); color:#fff; border-radius:4px;">
                        </div>
                        <div class="form-group" style="margin-bottom: 0;">
                            <label style="font-size: 10px; color: var(--text-muted); display: block; margin-bottom: 2px;">Waveform</label>
                            <select id="sound-wave-{atype}" style="width: 100%; background:#0f172a; color:#fff; border:1px solid var(--border); border-radius:4px; padding:4px; font-size:11px; outline:none;">
                                <option value="sine">sine (pure)</option>
                                <option value="triangle">triangle (soft)</option>
                                <option value="sawtooth">sawtooth (buzz)</option>
                                <option value="square">square (retro)</option>
                            </select>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        """
    db_path = os.path.join(BASE_DIR, "db/macd_history.db")
    
    if not os.path.exists(db_path):
        return
        
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Fetch latest 2 records for all symbols to evaluate trends
    latest_snapshot = []
    for symbol in symbols:
        cursor.execute("""
            SELECT timestamp, price, macd_line, signal_line, histogram, rsi, volume, average_volume, total_ce_oi, total_pe_oi, pcr, futures_oi, futures_oi_change_pct, day_change, rsi_30, rsi_60, macd_day, macd_signal_day, macd_hist_day, rsi_day, macd_45, macd_signal_45, macd_hist_45
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
            SELECT alert_timestamp, symbol, alert_type, signal_price, eod_price, pct_change, status, failure_reason, eval_timestamp,
                   signal_rsi, eod_rsi, signal_vol_ratio, eod_vol_ratio, signal_pcr, eod_pcr, nifty_change, signal_hist, eod_hist, id
            FROM alert_retrospectives
            ORDER BY alert_timestamp DESC
            LIMIT 300
        """)
        retros_rows = cursor.fetchall()
    except Exception as e:
        print(f"Error loading retrospectives: {e}")
             
    conn.close()
    
    # Run AI Optimizer analysis
    opt_data = run_optimization_analysis()
    if opt_data:
        try:
            rules_path = "/Users/sree/macd_momentum_tracker/db/optimized_rules.json"
            with open(rules_path, "w") as f:
                json.dump(opt_data, f, indent=2)
        except Exception as opt_err:
            print(f"  ⚠️ Error saving AI Optimizer rules JSON: {opt_err}")
    symbol_rules_html = ""
    symbols_dict = opt_data.get("symbols", {})
    if not symbols_dict:
        symbol_rules_html = """
        <div style="text-align: center; padding: 24px; color: var(--text-muted); font-size: 13px; background: rgba(15, 23, 42, 0.4); border: 1px solid var(--border); border-radius: 8px;">
            No custom symbol-specific patterns discovered yet. Insufficient history per symbol (needs at least 3 trials per stock).
        </div>
        """
    else:
        symbol_rules_html = """
        <div class="table-wrap" style="max-height: 250px; overflow-y: auto;">
            <table>
                <thead>
                    <tr>
                        <th>Symbol</th>
                        <th>Alert Type</th>
                        <th>Custom Rule Condition</th>
                        <th>Success Rate Impact</th>
                        <th>Trials</th>
                    </tr>
                </thead>
                <tbody>
        """
        for symbol, rules in sorted(symbols_dict.items()):
            for alert_type, rule in sorted(rules.items()):
                type_disp = alert_type.replace("_", " ")
                symbol_rules_html += f"""
                <tr>
                    <td style="font-weight: bold; color: #fff;">{symbol}</td>
                    <td style="font-size: 12px; font-weight: 600;">{type_disp}</td>
                    <td><code style="color: #60a5fa; font-family: monospace; font-size: 12px;">{rule.get("condition")}</code></td>
                    <td><span style="color: #10b981; font-weight: bold; font-size: 11px;">{rule.get("impact")}</span></td>
                    <td style="color: var(--text-muted); font-size: 11px;">{rule.get("sample_size")}</td>
                </tr>
                """
        symbol_rules_html += """
                </tbody>
            </table>
        </div>
        """

    rules_html = ""
    rules_dict = opt_data.get("rules", {})
    for alert_type, rule in rules_dict.items():
        type_display = alert_type.replace("_", " ")
        impact_color = "#3b82f6"
        if "→" in rule.get("impact", ""):
            impact_color = "#10b981"
            
        badge_style = f"background: {impact_color}18; color: {impact_color}; border: 1px solid {impact_color}30;"
        
        rules_html += f"""
        <div class="card" style="margin-bottom: 16px; border-left: 4px solid {impact_color};">
            <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 12px;">
                <div>
                    <span style="font-size: 10px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); font-weight: bold;">Alert Type</span>
                    <h3 style="font-family: 'Outfit', sans-serif; font-size: 17px; color: #fff; margin-top: 2px;">{type_display}</h3>
                </div>
                <span style="{badge_style} font-weight: bold; padding: 3px 10px; border-radius: 6px; font-size: 12px; font-family: 'Outfit', sans-serif;">
                    {rule.get("impact")}
                </span>
            </div>
            
            <div style="margin-bottom: 12px; font-size: 13px; color: #cbd5e1;">
                <strong>Filter Name:</strong> {rule.get("rule_name")}<br>
                <span style="color: var(--text-muted); font-size: 12px;">{rule.get("desc")}</span>
            </div>
            
            <div style="display: flex; justify-content: space-between; align-items: center; background: #0f172a; padding: 8px 12px; border-radius: 6px; border: 1px solid var(--border);">
                <div>
                    <span style="font-size: 9px; text-transform: uppercase; color: var(--text-muted); display: block;">Active Check</span>
                    <code style="color: #60a5fa; font-family: monospace; font-size: 12px; font-weight: bold;">{rule.get("condition")}</code>
                </div>
                <div style="text-align: right;">
                    <span style="font-size: 9px; text-transform: uppercase; color: var(--text-muted); display: block;">EOD Target Metric</span>
                    <span style="color: #fbbf24; font-size: 11px; font-weight: 600;">{rule.get("metrics")}</span>
                </div>
            </div>
        </div>
        """
        
    ai_status_banner = ""
    sample_size = opt_data.get("sample_size", 0)
    is_dynamic = opt_data.get("is_dynamic", False) and sample_size >= 5
    
    if not is_dynamic:
        ai_status_banner = f"""
        <div style="background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.3); border-radius: 8px; padding: 16px; margin-bottom: 24px; color: #cbd5e1; font-size: 13px; display: flex; align-items: center; gap: 16px;">
            <div style="font-size: 24px;">📚</div>
            <div>
                <strong>Awaiting More Local Backtest Data:</strong> Showing default expert-prescribed rules. 
                The system requires at least <strong>5</strong> non-neutral EOD retrospectives to activate dynamic learning (current trials: <strong>{sample_size}</strong>). 
                Once the threshold is met, the AI will automatically test RSI, Volume, PCR, and Futures OI parameters to find optimal filters.
            </div>
        </div>
        """
    else:
        ai_status_banner = f"""
        <div style="background: rgba(16, 185, 129, 0.1); border: 1px solid rgba(16, 185, 129, 0.3); border-radius: 8px; padding: 16px; margin-bottom: 24px; color: #cbd5e1; font-size: 13px; display: flex; align-items: center; gap: 16px;">
            <div style="font-size: 24px;">🤖</div>
            <div>
                <strong>Inbuilt Intelligence Optimizer Active:</strong> Dynamically analyzing and optimizing parameters based on <strong>{sample_size}</strong> EOD retrospective trials.
                Recommendations are updated daily on market close to filter out historical whipsaws and increase the alert success rate.
            </div>
        </div>
        """
        
    ai_status_badge = '<span style="background: rgba(16, 185, 129, 0.2); color: #10b981; padding: 4px 10px; border-radius: 20px; font-weight: bold; font-size: 12px;">ACTIVE</span>' if config.get("enable_adaptive_ai_filters", False) else '<span style="background: rgba(156, 163, 175, 0.2); color: #9ca3af; padding: 4px 10px; border-radius: 20px; font-weight: bold; font-size: 12px;">DISABLED (MONITORING ONLY)</span>'
    is_ai_active = config.get("enable_adaptive_ai_filters", False)
    is_ai_active_js = "true" if is_ai_active else "false"
    ai_btn_bg = "#ef4444" if is_ai_active else "#10b981"
    ai_btn_text = "🔴 Stop AI Optimization" if is_ai_active else "🟢 Start AI Optimization"

    ai_html = f"""
    <div class="card" style="margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 20px;">
        <div>
            <h2 style="font-family: 'Outfit', sans-serif; font-size: 20px; color: #fff; margin-bottom: 4px; display: flex; align-items: center; gap: 8px;">
                🤖 Inbuilt AI Optimizer & Parameter Tuning {ai_status_badge}
            </h2>
            <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 0;">
                Learns from local trade retrospectives to formulate filters that suppress false signals (low-conviction whipsaws).
            </p>
        </div>
        <button id="btn-toggle-ai-opt" onclick="toggleAISuppression({is_ai_active_js})"
                style="background: {ai_btn_bg}; color: white; border: none; padding: 8px 16px; border-radius: 8px; font-weight: bold; cursor: pointer; transition: all 0.2s; font-family: inherit;">
            {ai_btn_text}
        </button>
    </div>
    
    {ai_status_banner}
    
    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 24px;">
        <div>
            <h2 style="font-size: 15px; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text-muted); margin-bottom: 12px;">⚡ Active Filter Rules & Recommendations</h2>
            {rules_html}
        </div>
        
        <div class="card" style="height: fit-content;">
            <h3 style="font-family: 'Outfit', sans-serif; font-size: 18px; color: #fff; margin-bottom: 12px;">❓ How it works</h3>
            <div style="font-size: 13px; color: #cbd5e1; line-height: 1.6; display: flex; flex-direction: column; gap: 12px;">
                <p>
                    1. <strong>Data Collection:</strong> Every day after 3:30 PM market close, the EOD Retrospective checks how signals performed and saves the outcome (SUCCESS/FAILED/NEUTRAL) in the database.
                </p>
                <p>
                    2. <strong>Optimization Engine:</strong> The optimizer joins these outcomes with the indicator values (RSI, PCR, Volume, Futures OI) captured at the exact moment of the trigger.
                </p>
                <p>
                    3. <strong>Parameter Tuning:</strong> It tests multiple logical filters (e.g., volume ratio floor, RSI ceilings, PCR ranges) to see if applying them would have filtered out historical losses while keeping winning trades.
                </p>
                <p>
                    4. <strong>Conviction Downgrading:</strong> If <em>"Enable Adaptive AI Filtering"</em> is toggled in the configurations, future signals that fail these rules are flagged as <code>LOW CONVICTION</code>.
                </p>
                <div style="border-top: 1px solid var(--border); padding-top: 12px; margin-top: 8px;">
                    <strong style="color: #fbbf24;">💡 Direct Benefit:</strong> This allows you to completely filter out low-liquidity spikes or overbought momentum exhaustion traps dynamically, optimizing your win rate without manually tweaking code configurations.
                </div>
            </div>
        </div>
    </div>
    
    <div class="card" style="margin-top: 24px;">
        <h3 style="font-family: 'Outfit', sans-serif; font-size: 18px; color: #fff; margin-bottom: 4px; display: flex; align-items: center; gap: 8px;">
            🎯 Symbol-Specific Performance Profiles
        </h3>
        <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 16px;">
            Custom parameter thresholds learned by the AI for individual stocks based on their unique volatility and liquidity behaviors.
        </p>
        {symbol_rules_html}
    </div>
    """

    # Process retrospectives by date
    retros_by_date = {}
    for r in retros_rows:
        alert_time, symbol, alert_type, signal_price, eod_price, pct_change, status, reason, eval_time = r[:9]
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
        
    is_retro_active = config.get("enable_eod_retrospective", True)
    is_retro_active_js = "true" if is_retro_active else "false"
    retro_status_badge = '<span style="background: rgba(16, 185, 129, 0.2); color: #10b981; padding: 4px 10px; border-radius: 20px; font-weight: bold; font-size: 12px;">ACTIVE</span>' if is_retro_active else '<span style="background: rgba(156, 163, 175, 0.2); color: #9ca3af; padding: 4px 10px; border-radius: 20px; font-weight: bold; font-size: 12px;">DISABLED</span>'
    retro_btn_bg = "#ef4444" if is_retro_active else "#10b981"
    retro_btn_text = "🔴 Stop EOD Retrospection" if is_retro_active else "🟢 Start EOD Retrospection"
    
    retro_control_html = f"""
    <div class="card" style="margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; background: var(--surface); border: 1px solid var(--border); border-radius: 16px; padding: 20px;">
        <div>
            <h3 style="font-family: 'Outfit', sans-serif; font-size: 16px; color: #fff; margin-bottom: 4px; display: flex; align-items: center; gap: 8px;">
                🔄 EOD Retrospective Runner {retro_status_badge}
            </h3>
            <p style="font-size: 12px; color: var(--text-muted); margin-bottom: 0;">
                If enabled, the tracker will automatically grade and backtest signals against closing prices every day after 3:30 PM.
            </p>
        </div>
        <div style="display: flex; gap: 12px;">
            <button id="btn-force-retro" onclick="triggerForceRetrospective()"
                    style="background: #3b82f6; color: white; border: none; padding: 8px 16px; border-radius: 8px; font-weight: bold; cursor: pointer; transition: all 0.2s; font-family: inherit;">
                ⚡ Run Retrospective Now
            </button>
            <button id="btn-toggle-retro" onclick="toggleEODRetrospective({is_retro_active_js})"
                    style="background: {retro_btn_bg}; color: white; border: none; padding: 8px 16px; border-radius: 8px; font-weight: bold; cursor: pointer; transition: all 0.2s; font-family: inherit;">
                {retro_btn_text}
            </button>
        </div>
    </div>
    """

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
                alert_time, symbol, alert_type, sig_price, eod_price, pct_change, status, reason, eval_time, \
                sig_rsi, eod_rsi, sig_vol_ratio, eod_vol_ratio, sig_pcr, eod_pcr, nifty_change, sig_hist, eod_hist, item_id = item
                
                status_badge_color = "#10b981" if status == "SUCCESS" else "#ef4444" if status == "FAILED" else "#9ca3af"
                change_style = "color: #10b981;" if pct_change > 0 else "color: #ef4444;" if pct_change < 0 else "color: var(--text-muted);"
                alert_type_display = alert_type.replace("_", " ")
                
                # Format EOD values for display
                disp_sig_rsi = f"{sig_rsi:.1f}" if sig_rsi is not None else "—"
                disp_eod_rsi = f"{eod_rsi:.1f}" if eod_rsi is not None else "—"
                disp_sig_vol = f"{sig_vol_ratio:.1f}%" if sig_vol_ratio is not None else "—"
                disp_eod_vol = f"{eod_vol_ratio:.1f}%" if eod_vol_ratio is not None else "—"
                disp_sig_pcr = f"{sig_pcr:.2f}" if sig_pcr is not None else "—"
                disp_eod_pcr = f"{eod_pcr:.2f}" if eod_pcr is not None else "—"
                disp_sig_hist = f"{sig_hist:.3f}" if sig_hist is not None else "—"
                disp_eod_hist = f"{eod_hist:.3f}" if eod_hist is not None else "—"
                disp_nifty_change = f"{nifty_change:+.2f}%" if nifty_change is not None else "—"
                
                item_rows += f"""
                <tr onclick="toggleItemDetails('{item_id}')" style="cursor: pointer;" class="retro-row">
                    <td>{alert_time.split()[1]}</td>
                    <td style="font-weight: bold; color: #fff;">{symbol}</td>
                    <td style="font-size: 12px; font-weight: 600;">{alert_type_display}</td>
                    <td>₹{sig_price:.2f}</td>
                    <td>₹{eod_price:.2f}</td>
                    <td style="{change_style} font-weight: bold;">{pct_change:+.2f}%</td>
                    <td><span style="background: {status_badge_color}20; color: {status_badge_color}; font-weight: bold; padding: 2px 8px; border-radius: 4px; font-size: 11px;">{status}</span></td>
                    <td style="color: #cbd5e1; font-size: 12px; display: flex; align-items: center; gap: 6px;">
                        <span>{reason or 'N/A'}</span>
                        <span style="color: #60a5fa; font-size: 10px; text-decoration: underline;">Inspect ➔</span>
                    </td>
                </tr>
                <tr id="details-{item_id}" style="display: none; background: rgba(30, 41, 59, 0.25);">
                    <td colspan="8" style="padding: 16px; border: 1px dashed rgba(255,255,255,0.05); border-radius: 8px;">
                        <div style="display: grid; grid-template-columns: 2fr 3fr; gap: 20px;">
                            <div class="card" style="background: rgba(15, 23, 42, 0.4); border: 1px solid var(--border); padding: 14px; margin: 0; display: flex; flex-direction: column; justify-content: space-between;">
                                <div>
                                    <h4 style="margin: 0 0 8px 0; color: #fff; font-size: 13px; font-family: 'Outfit', sans-serif;">🔍 Diagnostic Assessment</h4>
                                    <p style="font-size: 12px; color: var(--text-muted); margin: 0 0 12px 0; line-height: 1.5;">
                                        Generated at <strong>{alert_time.split()[1]}</strong>. Graded against EOD close to determine signal strength.
                                    </p>
                                </div>
                                <div style="background: {status_badge_color}10; border-left: 4px solid {status_badge_color}; padding: 10px; border-radius: 4px;">
                                    <strong style="color: {status_badge_color}; font-size: 12px; display: block; margin-bottom: 2px;">Result: {status}</strong>
                                    <span style="color: #cbd5e1; font-size: 11px;">{reason or 'Signal behaved within expected parameters.'}</span>
                                </div>
                            </div>
                            
                            <div class="card" style="background: rgba(15, 23, 42, 0.4); border: 1px solid var(--border); padding: 14px; margin: 0;">
                                <h4 style="margin: 0 0 10px 0; color: #fff; font-size: 13px; font-family: 'Outfit', sans-serif;">📊 Signal vs. EOD Metrics</h4>
                                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; font-size: 11px; text-align: center; border-bottom: 1px solid var(--border); padding-bottom: 4px; margin-bottom: 4px; font-weight: bold; color: var(--text-muted);">
                                    <div style="text-align: left;">Metric</div>
                                    <div>Signal Time</div>
                                    <div>EOD Close</div>
                                </div>
                                
                                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; font-size: 11px; padding: 3px 0; align-items: center;">
                                    <div style="text-align: left; font-weight: bold; color: #fff;">Price</div>
                                    <div style="color: #cbd5e1;">₹{sig_price:.2f}</div>
                                    <div style="font-weight: bold; {change_style}">₹{eod_price:.2f} ({pct_change:+.2f}%)</div>
                                </div>
                                
                                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; font-size: 11px; padding: 3px 0; align-items: center;">
                                    <div style="text-align: left; font-weight: bold; color: #fff;">RSI</div>
                                    <div style="color: #cbd5e1;">{disp_sig_rsi}</div>
                                    <div style="color: #cbd5e1;">{disp_eod_rsi}</div>
                                </div>
                                
                                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; font-size: 11px; padding: 3px 0; align-items: center;">
                                    <div style="text-align: left; font-weight: bold; color: #fff;">Vol Ratio</div>
                                    <div style="color: #cbd5e1;">{disp_sig_vol}</div>
                                    <div style="color: #cbd5e1;">{disp_eod_vol}</div>
                                </div>
                                
                                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; font-size: 11px; padding: 3px 0; align-items: center;">
                                    <div style="text-align: left; font-weight: bold; color: #fff;">Option PCR</div>
                                    <div style="color: #cbd5e1;">{disp_sig_pcr}</div>
                                    <div style="color: #cbd5e1;">{disp_eod_pcr}</div>
                                </div>
                                
                                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; font-size: 11px; padding: 3px 0; align-items: center;">
                                    <div style="text-align: left; font-weight: bold; color: #fff;">MACD Hist</div>
                                    <div style="color: #cbd5e1;">{disp_sig_hist}</div>
                                    <div style="color: #cbd5e1;">{disp_eod_hist}</div>
                                </div>
                                
                                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 8px; font-size: 11px; padding: 3px 0; align-items: center; border-top: 1px dashed var(--border); margin-top: 2px; padding-top: 4px;">
                                    <div style="text-align: left; font-weight: bold; color: #fff;">Nifty Index</div>
                                    <div style="color: var(--text-muted);">Signal Time</div>
                                    <div style="font-weight: bold; color: { '#10b981' if (nifty_change is not None and nifty_change > 0) else '#ef4444' if (nifty_change is not None and nifty_change < 0) else 'var(--text-muted)' };">{disp_nifty_change}</div>
                                </div>
                            </div>
                        </div>
                    </td>
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
    recent_alerts_large = get_latest_alerts_from_log(500)
    alerts_json_str = json.dumps(recent_alerts_large)
    tracker_logs_text = get_latest_tracker_logs(300)
    
    # Get DB size on disk
    size_mb = db_manager.get_db_size_mb()
    if size_mb < 1.0:
        size_str = f"{size_mb * 1024:.1f} KB"
    else:
        size_str = f"{size_mb:.2f} MB"
    
    # Build HTML rows for recent alerts
    alert_rows = ""
    for a in recent_alerts:
        sev_color = "#ef4444" if a["severity"] == "CRITICAL" else "#f97316" if a["severity"] == "HIGH" else "#eab308" if a["severity"] == "MEDIUM" else "#9ca3af" if a["severity"] == "LOW_CONVICTION" else "#3b82f6"
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
        t_stamp, s_price, s_macd, s_sig, s_hist, s_rsi, s_vol, s_avg_vol, s_ce_oi, s_pe_oi, s_pcr, s_fut_oi, s_fut_oi_chg, s_day_chg, s_rsi_30, s_rsi_60, s_macd_day, s_macd_sig_day, s_macd_hist_day, s_rsi_day, s_macd_45, s_sig_45, s_hist_45 = latest
        
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

        # Determine trend based on daily price change if available, fallback to 15m price change or MACD change
        trend_up = False
        trend_down = False
        if s_day_chg is not None and s_day_chg != 0:
            trend_up = s_day_chg > 0
            trend_down = s_day_chg < 0
        else:
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
                sym, s_price, s_macd, s_sig, s_hist, trend_str, trend_style, rsi_str, rsi_style, s_vol, s_avg_vol, (s_vol / s_avg_vol) * 100, vol_ratio_style, interp, interp_style, s_rsi_30, s_rsi_60, s_macd_day, s_macd_sig_day, s_macd_hist_day, s_rsi_day, s_macd_45, s_sig_45, s_hist_45
            ))
            
        # Format individual MACD columns
        macd_color = "#22c55e" if s_macd is not None and s_macd > config.get("momentum_threshold", 5.0) else "#cbd5e1"
        hist_color = "#22c55e" if s_hist is not None and s_hist > 0 else "#ef4444" if s_hist is not None else "#cbd5e1"
        
        macd_45_color = "#22c55e" if s_macd_45 is not None and s_macd_45 > config.get("momentum_threshold", 5.0) else "#cbd5e1"
        hist_45_color = "#22c55e" if s_hist_45 is not None and s_hist_45 > 0 else "#ef4444" if s_hist_45 is not None else "#cbd5e1"
        
        macd_day_color = "#22c55e" if s_macd_day is not None and s_macd_day > config.get("momentum_threshold", 5.0) else "#cbd5e1"
        hist_day_color = "#22c55e" if s_macd_hist_day is not None and s_macd_hist_day > 0 else "#ef4444" if s_macd_hist_day is not None else "#cbd5e1"
        
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
            <td class="col-symbol" style="font-weight: bold; color: #fff;">{sym}</td>
            <td class="col-price">₹{s_price:.2f}</td>
            <td class="col-day_change" style="{day_chg_style}">{day_chg_str}</td>
            <td class="col-macd_15" style="color: {macd_color}; font-weight: bold;">{f"{s_macd:.3f}" if s_macd is not None else "—"}</td>
            <td class="col-signal_15">{f"{s_sig:.3f}" if s_sig is not None else "—"}</td>
            <td class="col-hist_15" style="color: {hist_color}; font-weight: bold;">{f"{s_hist:+.3f}" if s_hist is not None else "—"}</td>
            <td class="col-macd_45" style="color: {macd_45_color}; font-weight: bold;">{f"{s_macd_45:.3f}" if s_macd_45 is not None else "—"}</td>
            <td class="col-signal_45">{f"{s_sig_45:.3f}" if s_sig_45 is not None else "—"}</td>
            <td class="col-hist_45" style="color: {hist_45_color}; font-weight: bold;">{f"{s_hist_45:+.3f}" if s_hist_45 is not None else "—"}</td>
            <td class="col-trend" style="{trend_style}">{trend_str}</td>
            <td class="col-rsi_15" style="{rsi_style}">{rsi_str}</td>
            <td class="col-rsi_30">{f"{s_rsi_30:.2f}" if s_rsi_30 is not None else "—"}</td>
            <td class="col-rsi_60">{f"{s_rsi_60:.2f}" if s_rsi_60 is not None else "—"}</td>
            <td class="col-vol">{fmt_vol(s_vol)}</td>
            <td class="col-avg_vol">{fmt_vol(s_avg_vol)}</td>
            <td class="col-ratio" style="{vol_ratio_style}">{vol_ratio_str}</td>
            <td class="col-pcr" style="{pcr_style}">{pcr_str}</td>
            <td class="col-fut_oi">{fut_oi_str}</td>
            <td class="col-oi_chg" style="{oi_chg_style}">{oi_chg_str}</td>
            <td class="col-macd_day" style="color: {macd_day_color}; font-weight: bold;">{f"{s_macd_day:.3f}" if s_macd_day is not None else "—"}</td>
            <td class="col-signal_day">{f"{s_macd_sig_day:.3f}" if s_macd_sig_day is not None else "—"}</td>
            <td class="col-hist_day" style="color: {hist_day_color}; font-weight: bold;">{f"{s_macd_hist_day:+.3f}" if s_macd_hist_day is not None else "—"}</td>
            <td class="col-rsi_day">{f"{s_rsi_day:.2f}" if s_rsi_day is not None else "—"}</td>
            <td class="col-interp" style="{interp_style}">{interp}</td>
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
            sym, price, macd_val, sig_val, hist_val, tr_str, tr_style, r_str, r_style, vol_val, avg_vol_val, ratio_val, ratio_style, interp_val, interp_style, r_30, r_60, m_day, m_sig_day, m_hist_day, r_day, m_45, m_sig_45, m_hist_45 = item
            
            # Format individual MACD columns
            macd_color = "#22c55e" if macd_val is not None and macd_val > config.get("momentum_threshold", 5.0) else "#cbd5e1"
            hist_color = "#22c55e" if hist_val is not None and hist_val > 0 else "#ef4444" if hist_val is not None else "#cbd5e1"
            
            macd_45_color = "#22c55e" if m_45 is not None and m_45 > config.get("momentum_threshold", 5.0) else "#cbd5e1"
            hist_45_color = "#22c55e" if m_hist_45 is not None and m_hist_45 > 0 else "#ef4444" if m_hist_45 is not None else "#cbd5e1"
            
            macd_day_color = "#22c55e" if m_day is not None and m_day > config.get("momentum_threshold", 5.0) else "#cbd5e1"
            hist_day_color = "#22c55e" if m_hist_day is not None and m_hist_day > 0 else "#ef4444" if m_hist_day is not None else "#cbd5e1"

            dryup_rows += f"""
            <tr>
                <td class="col-symbol" style="font-weight: bold; color: #fff;">{sym}</td>
                <td class="col-price">₹{price:.2f}</td>
                <td class="col-ratio" style="{ratio_style} font-weight: bold;">{ratio_val:.1f}%</td>
                <td class="col-vol">{fmt_vol(vol_val)}</td>
                <td class="col-avg_vol">{fmt_vol(avg_vol_val)}</td>
                <td class="col-macd_15" style="color: {macd_color}; font-weight: bold;">{f"{macd_val:.3f}" if macd_val is not None else "—"}</td>
                <td class="col-signal_15">{f"{sig_val:.3f}" if sig_val is not None else "—"}</td>
                <td class="col-hist_15" style="color: {hist_color}; font-weight: bold;">{f"{hist_val:+.3f}" if hist_val is not None else "—"}</td>
                <td class="col-macd_45" style="color: {macd_45_color}; font-weight: bold;">{f"{m_45:.3f}" if m_45 is not None else "—"}</td>
                <td class="col-signal_45">{f"{m_sig_45:.3f}" if m_sig_45 is not None else "—"}</td>
                <td class="col-hist_45" style="color: {hist_45_color}; font-weight: bold;">{f"{m_hist_45:+.3f}" if m_hist_45 is not None else "—"}</td>
                <td class="col-trend" style="{tr_style}">{tr_str}</td>
                <td class="col-rsi_15" style="{r_style}">{r_str}</td>
                <td class="col-rsi_30">{f"{r_30:.2f}" if r_30 is not None else "—"}</td>
                <td class="col-rsi_60">{f"{r_60:.2f}" if r_60 is not None else "—"}</td>
                <td class="col-macd_day" style="color: {macd_day_color}; font-weight: bold;">{f"{m_day:.3f}" if m_day is not None else "—"}</td>
                <td class="col-signal_day">{f"{m_sig_day:.3f}" if m_sig_day is not None else "—"}</td>
                <td class="col-hist_day" style="color: {hist_day_color}; font-weight: bold;">{f"{m_hist_day:+.3f}" if m_hist_day is not None else "—"}</td>
                <td class="col-rsi_day">{f"{r_day:.2f}" if r_day is not None else "—"}</td>
                <td class="col-interp" style="{interp_style}">{interp_val}</td>
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
        th {{ background: #1e293b; color: var(--text-muted); font-weight: 600; padding: 10px 12px; position: sticky; top: 0; z-index: 10; border-bottom: 1px solid var(--border); text-transform: uppercase; font-size: 10px; letter-spacing: 0.05em; cursor: pointer; user-select: none; transition: background 0.15s; }}
        th:hover {{ background: #334155 !important; }}
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
        .checkbox-group {{
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
            gap: 12px;
            margin-top: 12px;
            padding: 16px;
            background: #0f172a;
            border: 1px solid var(--border);
            border-radius: 8px;
        }}
        .checkbox-group label {{
            display: flex;
            align-items: center;
            gap: 8px;
            font-size: 13px;
            color: var(--text-main);
            cursor: pointer;
            user-select: none;
        }}
        .checkbox-group input[type="checkbox"] {{
            width: 16px;
            height: 16px;
            accent-color: var(--primary);
            cursor: pointer;
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
                <span class="db-info" id="db-size-info">🗄️ Database Disk Size: {size_str} (Capped at 30 Days)</span>
            </div>
        </div>
        <div style="text-align: right; display: flex; flex-direction: column; align-items: flex-end; gap: 4px;">
            <div class="meta" style="display: flex; align-items: center; gap: 8px; justify-content: flex-end;" id="monitoring-status-container">
                <span class="pulse" id="status-pulse"></span> <span id="status-text">LIVE MONITORING</span>
            </div>
            <div class="meta" id="last-updated-meta">Last Updated: <strong>{now_str}</strong></div>
            <div style="display: flex; align-items: center; gap: 12px;">
                <div id="fetch-progress-container" style="display: none; font-size: 11px; text-align: right; background: rgba(59, 130, 246, 0.1); border: 1px solid rgba(59, 130, 246, 0.3); padding: 6px 10px; border-radius: 8px; color: #60a5fa; min-width: 180px;">
                    <div id="fetch-progress-text" style="font-weight: 600; margin-bottom: 2px;">Initializing...</div>
                    <div style="width: 100%; height: 4px; background: #1e293b; border-radius: 2px; overflow: hidden; display: block;">
                        <div id="fetch-progress-bar" style="width: 0%; height: 100%; background: #3b82f6; transition: width 0.2s;"></div>
                    </div>
                </div>
                <!-- Start/Stop Buttons -->
                <div style="display: flex; gap: 6px;">
                    <button id="btn-start" onclick="setTrackingActive(true)" class="btn-fetch" style="background: #10b981; border: none; font-weight: bold; box-shadow: 0 4px 12px rgba(16, 185, 129, 0.2);">▶ Start</button>
                    <button id="btn-stop" onclick="setTrackingActive(false)" class="btn-fetch" style="background: #ef4444; border: none; font-weight: bold; box-shadow: 0 4px 12px rgba(239, 68, 68, 0.2);">⏸ Stop</button>
                </div>
                <button id="btn-audio-toggle" onclick="toggleAudioMuteState()" class="btn-fetch" style="background: #3b82f6; border: none; font-weight: bold; box-shadow: 0 4px 12px rgba(59, 130, 246, 0.2);">🔊 Sound Enabled</button>
                <button id="btn-force-fetch" onclick="triggerForceFetch()" class="btn-fetch">⚡ Force Fetch TV Data</button>
            </div>
        </div>
    </header>
    
    <div class="tabs-header">
        <button id="btn-tab-dashboard" class="tab-btn active" onclick="switchTab('dashboard')">📊 Live Dashboard</button>
        <button id="btn-tab-dryup" class="tab-btn" onclick="switchTab('dryup')">💧 Volume Dry-up</button>
        <button id="btn-tab-focus" class="tab-btn" onclick="switchTab('focus')">⭐ Focus Panel</button>
        <button id="btn-tab-retro" class="tab-btn" onclick="switchTab('retro')">🔍 EOD Retrospection</button>
        <button id="btn-tab-ai" class="tab-btn" onclick="switchTab('ai')">🤖 AI Optimizer</button>
        <button id="btn-tab-logs" class="tab-btn" onclick="switchTab('logs')">📝 System Logs</button>
        <button id="btn-tab-config" class="tab-btn" onclick="switchTab('config')">⚙️ Configuration</button>
    </div>
    
    <!-- Tab 1: Live Dashboard -->
    <div id="tab-dashboard" class="tab-content active-content">
        <div class="container">
            <!-- Alerts Log Card -->
            <div class="card">
                <h2>🔔 Recent Alerts Log (Latest 50)</h2>
                <div class="table-wrap" style="max-height: 200px; margin-bottom: 24px;">
                    <table id="alerts-log-table">
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
                        <tbody id="alerts-log-table-body">
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
                                <th class="col-symbol">Symbol</th>
                                <th class="col-price">Price</th>
                                <th class="col-day_change">Day Chg %</th>
                                <th class="col-macd_15">MACD (15m)</th>
                                <th class="col-signal_15">Signal (15m)</th>
                                <th class="col-hist_15">Hist (15m)</th>
                                <th class="col-macd_45">MACD (45m)</th>
                                <th class="col-signal_45">Signal (45m)</th>
                                <th class="col-hist_45">Hist (45m)</th>
                                <th class="col-trend">MACD Trend</th>
                                <th class="col-rsi_15">RSI (15m)</th>
                                <th class="col-rsi_30">RSI (30m)</th>
                                <th class="col-rsi_60">RSI (60m)</th>
                                <th class="col-vol">Today's Vol</th>
                                <th class="col-avg_vol">Avg Vol (10d)</th>
                                <th class="col-ratio">Vol Ratio</th>
                                <th class="col-pcr">Option PCR</th>
                                <th class="col-fut_oi">Futures OI</th>
                                <th class="col-oi_chg">OI Chg %</th>
                                <th class="col-macd_day">MACD (Day)</th>
                                <th class="col-signal_day">Signal (Day)</th>
                                <th class="col-hist_day">Hist (Day)</th>
                                <th class="col-rsi_day">RSI (Day)</th>
                                <th class="col-interp">Interpretation</th>
                            </tr>
                            <tr class="filter-row">
                                <td class="col-symbol"><input type="text" id="flt-symbol" oninput="applyAllFilters()" placeholder="Filter symbol..."></td>
                                <td class="col-price"><input type="text" id="flt-price" oninput="applyAllFilters()" placeholder="e.g. >1000"></td>
                                <td class="col-day_change"><input type="text" id="flt-day-change" oninput="applyAllFilters()" placeholder="e.g. >1"></td>
                                <td class="col-macd_15"><input type="text" id="flt-macd-15" oninput="applyAllFilters()" placeholder="e.g. >0"></td>
                                <td class="col-signal_15"><input type="text" id="flt-signal-15" oninput="applyAllFilters()" placeholder="e.g. >0"></td>
                                <td class="col-hist_15"><input type="text" id="flt-hist-15" oninput="applyAllFilters()" placeholder="e.g. >0"></td>
                                <td class="col-macd_45"><input type="text" id="flt-macd-45" oninput="applyAllFilters()" placeholder="e.g. >0"></td>
                                <td class="col-signal_45"><input type="text" id="flt-signal-45" oninput="applyAllFilters()" placeholder="e.g. >0"></td>
                                <td class="col-hist_45"><input type="text" id="flt-hist-45" oninput="applyAllFilters()" placeholder="e.g. >0"></td>
                                <td class="col-trend"><input type="text" id="flt-trend" oninput="applyAllFilters()" placeholder="e.g. >0.1"></td>
                                <td class="col-rsi_15"><input type="text" id="flt-rsi" oninput="applyAllFilters()" placeholder="e.g. >70"></td>
                                <td class="col-rsi_30"><input type="text" id="flt-rsi-30" oninput="applyAllFilters()" placeholder="e.g. >50"></td>
                                <td class="col-rsi_60"><input type="text" id="flt-rsi-60" oninput="applyAllFilters()" placeholder="e.g. >50"></td>
                                <td class="col-vol"><input type="text" id="flt-vol" oninput="applyAllFilters()" placeholder="e.g. >1M"></td>
                                <td class="col-avg_vol"><input type="text" id="flt-avg-vol" oninput="applyAllFilters()" placeholder="e.g. >1M"></td>
                                <td class="col-ratio"><input type="text" id="flt-ratio" oninput="applyAllFilters()" placeholder="e.g. <50"></td>
                                <td class="col-pcr"><input type="text" id="flt-pcr" oninput="applyAllFilters()" placeholder="e.g. >0.9"></td>
                                <td class="col-fut_oi"><input type="text" id="flt-fut-oi" oninput="applyAllFilters()" placeholder="e.g. >10M"></td>
                                <td class="col-oi_chg"><input type="text" id="flt-oi-chg" oninput="applyAllFilters()" placeholder="e.g. >2%"></td>
                                <td class="col-macd_day"><input type="text" id="flt-macd-day" oninput="applyAllFilters()" placeholder="e.g. >0"></td>
                                <td class="col-signal_day"><input type="text" id="flt-signal-day" oninput="applyAllFilters()" placeholder="e.g. >0"></td>
                                <td class="col-hist_day"><input type="text" id="flt-hist-day" oninput="applyAllFilters()" placeholder="e.g. >0"></td>
                                <td class="col-rsi_day"><input type="text" id="flt-rsi-day" oninput="applyAllFilters()" placeholder="e.g. >50"></td>
                                <td class="col-interp"><input type="text" id="flt-interp" oninput="applyAllFilters()" placeholder="Filter signal..."></td>
                            </tr>
                        </thead>
                        <tbody id="snapshot-table-body">
                            {snapshot_rows or '<tr><td colspan="24" style="text-align:center; padding: 30px; color: var(--text-muted);">No snapshot data in database.</td></tr>'}
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
                                <th class="col-symbol">Symbol</th>
                                <th class="col-price">Price</th>
                                <th class="col-ratio">Vol Ratio</th>
                                <th class="col-vol">Today's Vol</th>
                                <th class="col-avg_vol">Avg Vol (10d)</th>
                                <th class="col-macd_15">MACD (15m)</th>
                                <th class="col-signal_15">Signal (15m)</th>
                                <th class="col-hist_15">Hist (15m)</th>
                                <th class="col-macd_45">MACD (45m)</th>
                                <th class="col-signal_45">Signal (45m)</th>
                                <th class="col-hist_45">Hist (45m)</th>
                                <th class="col-trend">MACD Trend</th>
                                <th class="col-rsi_15">RSI (15m)</th>
                                <th class="col-rsi_30">RSI (30m)</th>
                                <th class="col-rsi_60">RSI (60m)</th>
                                <th class="col-macd_day">MACD (Day)</th>
                                <th class="col-signal_day">Signal (Day)</th>
                                <th class="col-hist_day">Hist (Day)</th>
                                <th class="col-rsi_day">RSI (Day)</th>
                                <th class="col-interp">Interpretation</th>
                            </tr>
                            <tr class="filter-row">
                                <td class="col-symbol"><input type="text" id="flt-dry-symbol" oninput="applyAllDryupFilters()" placeholder="Filter symbol..."></td>
                                <td class="col-price"><input type="text" id="flt-dry-price" oninput="applyAllDryupFilters()" placeholder="e.g. >1000"></td>
                                <td class="col-ratio"><input type="text" id="flt-dry-ratio" oninput="applyAllDryupFilters()" placeholder="e.g. <30"></td>
                                <td class="col-vol"><input type="text" id="flt-dry-vol" oninput="applyAllDryupFilters()" placeholder="e.g. >100K"></td>
                                <td class="col-avg_vol"><input type="text" id="flt-dry-avg-vol" oninput="applyAllDryupFilters()" placeholder="e.g. >100K"></td>
                                <td class="col-macd_15"><input type="text" id="flt-dry-macd-15" oninput="applyAllDryupFilters()" placeholder="e.g. >0"></td>
                                <td class="col-signal_15"><input type="text" id="flt-dry-signal-15" oninput="applyAllDryupFilters()" placeholder="e.g. >0"></td>
                                <td class="col-hist_15"><input type="text" id="flt-dry-hist-15" oninput="applyAllDryupFilters()" placeholder="e.g. >0"></td>
                                <td class="col-macd_45"><input type="text" id="flt-dry-macd-45" oninput="applyAllDryupFilters()" placeholder="e.g. >0"></td>
                                <td class="col-signal_45"><input type="text" id="flt-dry-signal-45" oninput="applyAllDryupFilters()" placeholder="e.g. >0"></td>
                                <td class="col-hist_45"><input type="text" id="flt-dry-hist-45" oninput="applyAllDryupFilters()" placeholder="e.g. >0"></td>
                                <td class="col-trend"><input type="text" id="flt-dry-trend" oninput="applyAllDryupFilters()" placeholder="e.g. >0"></td>
                                <td class="col-rsi_15"><input type="text" id="flt-dry-rsi" oninput="applyAllDryupFilters()" placeholder="e.g. >50"></td>
                                <td class="col-rsi_30"><input type="text" id="flt-dry-rsi-30" oninput="applyAllDryupFilters()" placeholder="e.g. >50"></td>
                                <td class="col-rsi_60"><input type="text" id="flt-dry-rsi-60" oninput="applyAllDryupFilters()" placeholder="e.g. >50"></td>
                                <td class="col-macd_day"><input type="text" id="flt-dry-macd-day" oninput="applyAllDryupFilters()" placeholder="e.g. >0"></td>
                                <td class="col-signal_day"><input type="text" id="flt-dry-signal-day" oninput="applyAllDryupFilters()" placeholder="e.g. >0"></td>
                                <td class="col-hist_day"><input type="text" id="flt-dry-hist-day" oninput="applyAllDryupFilters()" placeholder="e.g. >0"></td>
                                <td class="col-rsi_day"><input type="text" id="flt-dry-rsi-day" oninput="applyAllDryupFilters()" placeholder="e.g. >50"></td>
                                <td class="col-interp"><input type="text" id="flt-dry-interp" oninput="applyAllDryupFilters()" placeholder="Filter signal..."></td>
                            </tr>
                        </thead>
                        <tbody id="dryup-table-body">
                            {dryup_rows or '<tr><td colspan="20" style="text-align:center; padding: 30px; color: var(--text-muted);">No active volume dry-ups detected.</td></tr>'}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
    
    <!-- Tab: Focus Panel -->
    <div id="tab-focus" class="tab-content">
        <div class="container">
            <!-- Focus config card -->
            <div class="card" style="max-width: 1000px; margin: 0 auto 24px auto;">
                <h2>⭐ Focus Filter Configuration</h2>
                <div style="margin-bottom: 20px; font-size: 13px; color: var(--text-muted);">
                    Customize focus alerts parameters. This panel screens triggered alerts based on minimum Volume Ratio, Severity, and type.
                </div>
                
                <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px;">
                    <div class="form-group" style="margin-bottom: 0;">
                        <label for="inp-focus-vol-ratio">💧 Min Vol Ratio %</label>
                        <input type="number" id="inp-focus-vol-ratio" value="200" oninput="renderFocusAlerts()" style="width: 100%; padding: 8px 12px; background: #0f172a; border: 1px solid var(--border); border-radius: 6px; color: white;">
                    </div>
                    <div class="form-group" style="margin-bottom: 0;">
                        <label for="inp-focus-severity">⚠️ Min Severity</label>
                        <select id="inp-focus-severity" onchange="renderFocusAlerts()" style="width: 100%; padding: 8px 12px; background: #0f172a; border: 1px solid var(--border); border-radius: 6px; color: white; cursor: pointer;">
                            <option value="CRITICAL" selected>CRITICAL</option>
                            <option value="HIGH">HIGH and above</option>
                            <option value="MEDIUM">MEDIUM and above</option>
                            <option value="INFO">INFO and above</option>
                        </select>
                    </div>
                    <div class="form-group" style="margin-bottom: 0;">
                        <label for="inp-focus-type">🔔 Trigger Type</label>
                        <select id="inp-focus-type" onchange="renderFocusAlerts()" style="width: 100%; padding: 8px 12px; background: #0f172a; border: 1px solid var(--border); border-radius: 6px; color: white; cursor: pointer;">
                            <option value="ALL" selected>ALL TRIGGERS</option>
                            <option value="BULLISH_CROSSOVER">BULLISH CROSSOVER</option>
                            <option value="BEARISH_CROSSOVER">BEARISH CROSSOVER</option>
                            <option value="MOMENTUM_START">MOMENTUM START</option>
                            <option value="VOLUME_DRYUP">VOLUME DRYUP</option>
                        </select>
                    </div>
                    <div class="form-group" style="margin-bottom: 0;">
                        <label for="inp-focus-sort-col">📊 Sort By</label>
                        <select id="inp-focus-sort-col" onchange="renderFocusAlerts()" style="width: 100%; padding: 8px 12px; background: #0f172a; border: 1px solid var(--border); border-radius: 6px; color: white; cursor: pointer;">
                            <option value="vol_ratio" selected>Volume Ratio</option>
                            <option value="timestamp">Alert Time</option>
                            <option value="severity">Severity</option>
                            <option value="symbol">Symbol</option>
                            <option value="price">Price</option>
                        </select>
                    </div>
                    <div class="form-group" style="margin-bottom: 0;">
                        <label for="inp-focus-sort-order">↕️ Sort Order</label>
                        <select id="inp-focus-sort-order" onchange="renderFocusAlerts()" style="width: 100%; padding: 8px 12px; background: #0f172a; border: 1px solid var(--border); border-radius: 6px; color: white; cursor: pointer;">
                            <option value="desc" selected>Descending</option>
                            <option value="asc">Ascending</option>
                        </select>
                    </div>
                </div>
            </div>
            
            <!-- Focus table card -->
            <div class="card" style="max-width: 1000px; margin: 0 auto;">
                <h2>⭐ Focus Alerts Screener</h2>
                <div class="table-wrap" style="max-height: 500px;">
                    <table id="focus-table">
                        <thead>
                            <tr>
                                <th>Time</th>
                                <th>Symbol</th>
                                <th>Price</th>
                                <th>Severity</th>
                                <th>Trigger</th>
                                <th>Message</th>
                                <th>Volume Ratio %</th>
                                <th>MACD (15m)</th>
                                <th>RSI (15m)</th>
                            </tr>
                        </thead>
                        <tbody id="focus-table-body">
                            <!-- Populated dynamically via JS -->
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
            {retro_control_html}{retro_html}
        </div>
    </div>
    
    <!-- Tab 5: AI Optimizer -->
    <div id="tab-ai" class="tab-content">
        <div class="container" style="max-width: 1100px; margin: 0 auto;">
            {ai_html}
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

            <div class="form-group">
                <label for="inp-vol-ratio">📊 Volume Ratio Alert Threshold (e.g. 2.0x average)</label>
                <input type="number" step="0.1" min="0.1" id="inp-vol-ratio">
            </div>
            
            <div class="form-group" style="display: flex; align-items: center; gap: 10px; margin-top: 16px; margin-bottom: 12px;">
                <input type="checkbox" id="cfg-enable-ai" style="width: 20px; height: 20px; cursor: pointer; accent-color: var(--primary);">
                <label for="cfg-enable-ai" style="margin-bottom: 0; cursor: pointer; font-weight: bold; color: #fff;">🤖 Enable Adaptive AI Filtering (Low Conviction Suppression)</label>
            </div>
            
            <div class="form-group" style="display: flex; align-items: center; gap: 10px; margin-top: 12px; margin-bottom: 24px;">
                <input type="checkbox" id="cfg-enable-retro" style="width: 20px; height: 20px; cursor: pointer; accent-color: var(--primary);">
                <label for="cfg-enable-retro" style="margin-bottom: 0; cursor: pointer; font-weight: bold; color: #fff;">🔍 Enable EOD Retrospective Analysis</label>
            </div>
            
            <button class="btn-submit" onclick="saveConfig()">💾 Save Configuration</button>
        </div>

        <div class="card" style="max-width: 600px; margin: 24px auto 0 auto;">
            <h2>🔊 Audible Alerts Settings</h2>
            <div style="margin-bottom: 20px; font-size: 13px; color: var(--text-muted);">
                Enable sound alerts and customize how they beep for different indicators.
            </div>
            
            <div class="form-group" style="display: flex; align-items: center; gap: 10px; margin-bottom: 16px;">
                <input type="checkbox" id="cfg-audio-enabled" style="width: 20px; height: 20px; cursor: pointer; accent-color: var(--primary);">
                <label for="cfg-audio-enabled" style="margin-bottom: 0; cursor: pointer; font-weight: bold; color: #fff;">🔊 Enable Sound Alerts in Dashboard</label>
            </div>
            
            <div class="form-group" style="display: flex; align-items: center; gap: 10px; margin-bottom: 20px;">
                <input type="checkbox" id="cfg-audio-startup" style="width: 20px; height: 20px; cursor: pointer; accent-color: var(--primary);">
                <label for="cfg-audio-startup" style="margin-bottom: 0; cursor: pointer; color: var(--text-main);">🎵 Play Startup Chime on Dashboard Load</label>
            </div>

            <div style="border-top: 1px solid var(--border); padding-top: 16px;">
                <h3 style="font-size: 14px; color: #fff; margin-bottom: 12px; font-family: 'Outfit', sans-serif;">Customize Signal Tones</h3>
                <div style="display: flex; flex-direction: column; gap: 12px;">
                    {sound_cards_html}
                </div>
            </div>
        </div>
        
        <div class="card" style="max-width: 800px; margin: 24px auto 0 auto;">
            <h2>📋 Dashboard Column Visibility</h2>
            <div style="margin-bottom: 20px; font-size: 13px; color: var(--text-muted);">
                Toggle the columns you want to display on the live snapshot and volume dry-up dashboards.
            </div>
            <div class="checkbox-group">
                <label><input type="checkbox" id="cfg-col-day_change" onchange="toggleColumn('day_change')"> Day Chg %</label>
                <label><input type="checkbox" id="cfg-col-macd_15" onchange="toggleColumn('macd_15')"> MACD (15m)</label>
                <label><input type="checkbox" id="cfg-col-signal_15" onchange="toggleColumn('signal_15')"> Signal (15m)</label>
                <label><input type="checkbox" id="cfg-col-hist_15" onchange="toggleColumn('hist_15')"> Hist (15m)</label>
                <label><input type="checkbox" id="cfg-col-macd_45" onchange="toggleColumn('macd_45')"> MACD (45m)</label>
                <label><input type="checkbox" id="cfg-col-signal_45" onchange="toggleColumn('signal_45')"> Signal (45m)</label>
                <label><input type="checkbox" id="cfg-col-hist_45" onchange="toggleColumn('hist_45')"> Hist (45m)</label>
                <label><input type="checkbox" id="cfg-col-trend" onchange="toggleColumn('trend')"> MACD Trend</label>
                <label><input type="checkbox" id="cfg-col-rsi_15" onchange="toggleColumn('rsi_15')"> RSI (15m)</label>
                <label><input type="checkbox" id="cfg-col-rsi_30" onchange="toggleColumn('rsi_30')"> RSI (30m)</label>
                <label><input type="checkbox" id="cfg-col-rsi_60" onchange="toggleColumn('rsi_60')"> RSI (60m)</label>
                <label><input type="checkbox" id="cfg-col-vol" onchange="toggleColumn('vol')"> Today's Vol</label>
                <label><input type="checkbox" id="cfg-col-avg_vol" onchange="toggleColumn('avg_vol')"> Avg Vol (10d)</label>
                <label><input type="checkbox" id="cfg-col-ratio" onchange="toggleColumn('ratio')"> Vol Ratio</label>
                <label><input type="checkbox" id="cfg-col-pcr" onchange="toggleColumn('pcr')"> Option PCR</label>
                <label><input type="checkbox" id="cfg-col-fut_oi" onchange="toggleColumn('fut_oi')"> Futures OI</label>
                <label><input type="checkbox" id="cfg-col-oi_chg" onchange="toggleColumn('oi_chg')"> OI Chg %</label>
                <label><input type="checkbox" id="cfg-col-macd_day" onchange="toggleColumn('macd_day')"> MACD (Day)</label>
                <label><input type="checkbox" id="cfg-col-signal_day" onchange="toggleColumn('signal_day')"> Signal (Day)</label>
                <label><input type="checkbox" id="cfg-col-hist_day" onchange="toggleColumn('hist_day')"> Hist (Day)</label>
                <label><input type="checkbox" id="cfg-col-rsi_day" onchange="toggleColumn('rsi_day')"> RSI (Day)</label>
                <label><input type="checkbox" id="cfg-col-interp" onchange="toggleColumn('interp')"> Interpretation</label>
            </div>
        </div>
    </div>

    <!-- Tab: System Logs -->
    <div id="tab-logs" class="tab-content">
        <div class="container" style="max-width: 1000px; margin: 0 auto;">
            <div class="card">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                    <h2 style="margin-bottom: 0;">📝 System Log Viewer (Latest 300 lines)</h2>
                    <div style="display: flex; gap: 12px; align-items: center;">
                        <label style="display: flex; align-items: center; gap: 8px; cursor: pointer; color: white; font-weight: bold; font-size: 13px;">
                            <input type="checkbox" id="cfg-enable-logging" onchange="toggleEnableLogging(this)" style="width: 18px; height: 18px; cursor: pointer; accent-color: var(--primary);"> 
                            Enable System Logging
                        </label>
                        <button onclick="clearSystemLogs()" class="btn-reset-filters" style="background: #ef4444; border: none; box-shadow: 0 4px 12px rgba(239, 68, 68, 0.15);">🗑️ Clear Logs</button>
                        <button onclick="updateDashboardSeamlessly()" class="btn-reset-filters">🔄 Refresh Logs</button>
                    </div>
                </div>
                <div style="margin-bottom: 20px; font-size: 13px; color: var(--text-muted);">
                    Live logs from the daemon process tracking API requests, calculations, database writes, and memory metrics.
                </div>
                <pre id="system-logs-content" style="background: #0f172a; padding: 16px; border-radius: 8px; border: 1px solid var(--border); overflow-x: auto; max-height: 500px; font-family: 'Courier New', Courier, monospace; font-size: 12px; line-height: 1.5; color: #34d399; white-space: pre-wrap; word-wrap: break-word;">{tracker_logs_text}</pre>
                <div id="system-logs-disabled-message" style="display: none; padding: 40px; text-align: center; color: var(--text-muted); border: 1px dashed var(--border); border-radius: 8px; background: #0f172a;">
                    <span style="font-size: 24px; display: block; margin-bottom: 8px;">⏸️</span>
                    System logging is disabled. Check the box above to enable logging and see live updates.
                </div>
            </div>
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
            }} else if (tabName === 'focus') {{
                document.getElementById('btn-tab-focus').classList.add('active');
                document.getElementById('tab-focus').classList.add('active-content');
                localStorage.setItem('activeTab', 'focus');
            }} else if (tabName === 'retro') {{
                document.getElementById('btn-tab-retro').classList.add('active');
                document.getElementById('tab-retro').classList.add('active-content');
                localStorage.setItem('activeTab', 'retro');
            }} else if (tabName === 'ai') {{
                document.getElementById('btn-tab-ai').classList.add('active');
                document.getElementById('tab-ai').classList.add('active-content');
                localStorage.setItem('activeTab', 'ai');
            }} else if (tabName === 'logs') {{
                document.getElementById('btn-tab-logs').classList.add('active');
                document.getElementById('tab-logs').classList.add('active-content');
                localStorage.setItem('activeTab', 'logs');
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
        
        async function updateDashboardSeamlessly() {{
            try {{
                const baseUrl = getApiUrl('/alerts_dashboard.html');
                const url = baseUrl + (baseUrl.includes('?') ? '&' : '?') + '_t=' + new Date().getTime();
                const response = await fetch(url);
                if (!response.ok) return;
                const htmlText = await response.text();
                
                const parser = new DOMParser();
                const doc = parser.parseFromString(htmlText, 'text/html');
                
                const activeEl = document.activeElement;
                let activeId = null;
                let selectionStart = 0;
                let selectionEnd = 0;
                if (activeEl && activeEl.tagName === 'INPUT') {{
                    activeId = activeEl.id;
                    selectionStart = activeEl.selectionStart;
                    selectionEnd = activeEl.selectionEnd;
                }}
                
                const tableWrappers = document.querySelectorAll('.table-wrap');
                const scrollPositions = Array.from(tableWrappers).map(el => el.scrollTop);
                
                const selectors = [
                    '#alerts-log-table-body',
                    '#snapshot-table-body',
                    '#dryup-table-body',
                    '#tab-retro',
                    '#tab-ai',
                    '#db-size-info',
                    '#last-updated-meta',
                    '#raw-alerts-json',
                    '#system-logs-content'
                ];
                
                selectors.forEach(selector => {{
                    const oldEl = document.querySelector(selector);
                    const newEl = doc.querySelector(selector);
                    if (oldEl && newEl) {{
                        oldEl.innerHTML = newEl.innerHTML;
                    }}
                }});
                
                const newTableWrappers = document.querySelectorAll('.table-wrap');
                newTableWrappers.forEach((el, idx) => {{
                    if (scrollPositions[idx] !== undefined) {{
                        el.scrollTop = scrollPositions[idx];
                    }}
                }});
                
                if (typeof restoreFilters === 'function') {{
                    restoreFilters();
                }}
                if (typeof reapplySorting === 'function') {{
                    reapplySorting();
                }}
                if (typeof renderFocusAlerts === 'function') {{
                    renderFocusAlerts();
                }}
                
                if (activeId) {{
                    const newActiveEl = document.getElementById(activeId);
                    if (newActiveEl) {{
                        newActiveEl.focus();
                        try {{
                            newActiveEl.setSelectionRange(selectionStart, selectionEnd);
                        }} catch (e) {{}}
                    }}
                }}
                
                console.log("⚡ Dashboard seamlessly updated!");
                if (typeof checkForNewAlerts === 'function') {{
                    checkForNewAlerts();
                }}
            }} catch (err) {{
                console.error("Error doing seamless update:", err);
            }}
        }}

        setInterval(() => {{
            const currentTab = localStorage.getItem('activeTab') || 'dashboard';
            if (currentTab === 'dashboard' || currentTab === 'dryup') {{
                updateDashboardSeamlessly();
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
                macd_15: document.getElementById('flt-macd-15').value,
                signal_15: document.getElementById('flt-signal-15').value,
                hist_15: document.getElementById('flt-hist-15').value,
                macd_45: document.getElementById('flt-macd-45').value,
                signal_45: document.getElementById('flt-signal-45').value,
                hist_45: document.getElementById('flt-hist-45').value,
                trend: document.getElementById('flt-trend').value,
                rsi: document.getElementById('flt-rsi').value,
                rsi_30: document.getElementById('flt-rsi-30').value,
                rsi_60: document.getElementById('flt-rsi-60').value,
                vol: document.getElementById('flt-vol').value,
                avg_vol: document.getElementById('flt-avg-vol').value,
                ratio: document.getElementById('flt-ratio').value,
                pcr: document.getElementById('flt-pcr').value,
                fut_oi: document.getElementById('flt-fut-oi').value,
                oi_chg: document.getElementById('flt-oi-chg').value,
                macd_day: document.getElementById('flt-macd-day').value,
                signal_day: document.getElementById('flt-signal-day').value,
                hist_day: document.getElementById('flt-hist-day').value,
                rsi_day: document.getElementById('flt-rsi-day').value,
                interp: document.getElementById('flt-interp').value
            }};
            
            localStorage.setItem('macd_multi_filters_vol', JSON.stringify(filters));
            
            const rows = document.querySelectorAll('#snapshot-table-body tr');
            rows.forEach(row => {{
                if (row.querySelector('.col-symbol')) {{
                    const matchSymbol = row.querySelector('.col-symbol').textContent.toLowerCase().includes(filters.symbol.toLowerCase().trim());
                    const matchPrice = evaluateFilter(row.querySelector('.col-price').textContent, filters.price);
                    const matchDayChange = evaluateFilter(row.querySelector('.col-day_change').textContent, filters.day_change);
                    const matchMacd15 = evaluateFilter(row.querySelector('.col-macd_15').textContent, filters.macd_15);
                    const matchSignal15 = evaluateFilter(row.querySelector('.col-signal_15').textContent, filters.signal_15);
                    const matchHist15 = evaluateFilter(row.querySelector('.col-hist_15').textContent, filters.hist_15);
                    const matchMacd45 = evaluateFilter(row.querySelector('.col-macd_45').textContent, filters.macd_45);
                    const matchSignal45 = evaluateFilter(row.querySelector('.col-signal_45').textContent, filters.signal_45);
                    const matchHist45 = evaluateFilter(row.querySelector('.col-hist_45').textContent, filters.hist_45);
                    const matchTrend = evaluateFilter(row.querySelector('.col-trend').textContent, filters.trend);
                    const matchRsi = evaluateFilter(row.querySelector('.col-rsi_15').textContent, filters.rsi);
                    const matchRsi30 = evaluateFilter(row.querySelector('.col-rsi_30').textContent, filters.rsi_30);
                    const matchRsi60 = evaluateFilter(row.querySelector('.col-rsi_60').textContent, filters.rsi_60);
                    const matchVol = evaluateFilter(row.querySelector('.col-vol').textContent, filters.vol);
                    const matchAvgVol = evaluateFilter(row.querySelector('.col-avg_vol').textContent, filters.avg_vol);
                    const matchRatio = evaluateFilter(row.querySelector('.col-ratio').textContent, filters.ratio);
                    const matchPcr = evaluateFilter(row.querySelector('.col-pcr').textContent, filters.pcr);
                    const matchFutOi = evaluateFilter(row.querySelector('.col-fut_oi').textContent, filters.fut_oi);
                    const matchOiChg = evaluateFilter(row.querySelector('.col-oi_chg').textContent, filters.oi_chg);
                    const matchMacdDay = evaluateFilter(row.querySelector('.col-macd_day').textContent, filters.macd_day);
                    const matchSignalDay = evaluateFilter(row.querySelector('.col-signal_day').textContent, filters.signal_day);
                    const matchHistDay = evaluateFilter(row.querySelector('.col-hist_day').textContent, filters.hist_day);
                    const matchRsiDay = evaluateFilter(row.querySelector('.col-rsi_day').textContent, filters.rsi_day);
                    const matchInterp = row.querySelector('.col-interp').textContent.toLowerCase().includes(filters.interp.toLowerCase().trim());
                    
                    const matchesAll = matchSymbol && matchPrice && matchDayChange && 
                                       matchMacd15 && matchSignal15 && matchHist15 &&
                                       matchMacd45 && matchSignal45 && matchHist45 &&
                                       matchTrend && matchRsi && matchRsi30 && matchRsi60 && matchVol && 
                                       matchAvgVol && matchRatio && matchPcr && matchFutOi && matchOiChg && 
                                       matchMacdDay && matchSignalDay && matchHistDay &&
                                       matchRsiDay && matchInterp;
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
                macd_15: document.getElementById('flt-dry-macd-15').value,
                signal_15: document.getElementById('flt-dry-signal-15').value,
                hist_15: document.getElementById('flt-dry-hist-15').value,
                macd_45: document.getElementById('flt-dry-macd-45').value,
                signal_45: document.getElementById('flt-dry-signal-45').value,
                hist_45: document.getElementById('flt-dry-hist-45').value,
                trend: document.getElementById('flt-dry-trend').value,
                rsi: document.getElementById('flt-dry-rsi').value,
                rsi_30: document.getElementById('flt-dry-rsi-30').value,
                rsi_60: document.getElementById('flt-dry-rsi-60').value,
                macd_day: document.getElementById('flt-dry-macd-day').value,
                signal_day: document.getElementById('flt-dry-signal-day').value,
                hist_day: document.getElementById('flt-dry-hist-day').value,
                rsi_day: document.getElementById('flt-dry-rsi-day').value,
                interp: document.getElementById('flt-dry-interp').value
            }};
            
            localStorage.setItem('macd_multi_filters_dryup', JSON.stringify(filters));
            
            const rows = document.querySelectorAll('#dryup-table-body tr');
            rows.forEach(row => {{
                if (row.querySelector('.col-symbol')) {{
                    const matchSymbol = row.querySelector('.col-symbol').textContent.toLowerCase().includes(filters.symbol.toLowerCase().trim());
                    const matchPrice = evaluateFilter(row.querySelector('.col-price').textContent, filters.price);
                    const matchRatio = evaluateFilter(row.querySelector('.col-ratio').textContent, filters.ratio);
                    const matchVol = evaluateFilter(row.querySelector('.col-vol').textContent, filters.vol);
                    const matchAvgVol = evaluateFilter(row.querySelector('.col-avg_vol').textContent, filters.avg_vol);
                    const matchMacd15 = evaluateFilter(row.querySelector('.col-macd_15').textContent, filters.macd_15);
                    const matchSignal15 = evaluateFilter(row.querySelector('.col-signal_15').textContent, filters.signal_15);
                    const matchHist15 = evaluateFilter(row.querySelector('.col-hist_15').textContent, filters.hist_15);
                    const matchMacd45 = evaluateFilter(row.querySelector('.col-macd_45').textContent, filters.macd_45);
                    const matchSignal45 = evaluateFilter(row.querySelector('.col-signal_45').textContent, filters.signal_45);
                    const matchHist45 = evaluateFilter(row.querySelector('.col-hist_45').textContent, filters.hist_45);
                    const matchTrend = evaluateFilter(row.querySelector('.col-trend').textContent, filters.trend);
                    const matchRsi = evaluateFilter(row.querySelector('.col-rsi_15').textContent, filters.rsi);
                    const matchRsi30 = evaluateFilter(row.querySelector('.col-rsi_30').textContent, filters.rsi_30);
                    const matchRsi60 = evaluateFilter(row.querySelector('.col-rsi_60').textContent, filters.rsi_60);
                    const matchMacdDay = evaluateFilter(row.querySelector('.col-macd_day').textContent, filters.macd_day);
                    const matchSignalDay = evaluateFilter(row.querySelector('.col-signal_day').textContent, filters.signal_day);
                    const matchHistDay = evaluateFilter(row.querySelector('.col-hist_day').textContent, filters.hist_day);
                    const matchRsiDay = evaluateFilter(row.querySelector('.col-rsi_day').textContent, filters.rsi_day);
                    const matchInterp = row.querySelector('.col-interp').textContent.toLowerCase().includes(filters.interp.toLowerCase().trim());
                    
                    const matchesAll = matchSymbol && matchPrice && matchRatio && matchVol && 
                                       matchAvgVol && matchMacd15 && matchSignal15 && matchHist15 &&
                                       matchMacd45 && matchSignal45 && matchHist45 && matchTrend && 
                                       matchRsi && matchRsi30 && matchRsi60 && 
                                       matchMacdDay && matchSignalDay && matchHistDay &&
                                       matchRsiDay && matchInterp;
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
                    if(document.getElementById('flt-macd-15')) document.getElementById('flt-macd-15').value = filters.macd_15 || '';
                    if(document.getElementById('flt-signal-15')) document.getElementById('flt-signal-15').value = filters.signal_15 || '';
                    if(document.getElementById('flt-hist-15')) document.getElementById('flt-hist-15').value = filters.hist_15 || '';
                    if(document.getElementById('flt-macd-45')) document.getElementById('flt-macd-45').value = filters.macd_45 || '';
                    if(document.getElementById('flt-signal-45')) document.getElementById('flt-signal-45').value = filters.signal_45 || '';
                    if(document.getElementById('flt-hist-45')) document.getElementById('flt-hist-45').value = filters.hist_45 || '';
                    document.getElementById('flt-trend').value = filters.trend || '';
                    document.getElementById('flt-rsi').value = filters.rsi || '';
                    if(document.getElementById('flt-rsi-30')) document.getElementById('flt-rsi-30').value = filters.rsi_30 || '';
                    if(document.getElementById('flt-rsi-60')) document.getElementById('flt-rsi-60').value = filters.rsi_60 || '';
                    document.getElementById('flt-vol').value = filters.vol || '';
                    document.getElementById('flt-avg-vol').value = filters.avg_vol || '';
                    document.getElementById('flt-ratio').value = filters.ratio || '';
                    document.getElementById('flt-pcr').value = filters.pcr || '';
                    document.getElementById('flt-fut-oi').value = filters.fut_oi || '';
                    document.getElementById('flt-oi-chg').value = filters.oi_chg || '';
                    if(document.getElementById('flt-macd-day')) document.getElementById('flt-macd-day').value = filters.macd_day || '';
                    if(document.getElementById('flt-signal-day')) document.getElementById('flt-signal-day').value = filters.signal_day || '';
                    if(document.getElementById('flt-hist-day')) document.getElementById('flt-hist-day').value = filters.hist_day || '';
                    if(document.getElementById('flt-rsi-day')) document.getElementById('flt-rsi-day').value = filters.rsi_day || '';
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
                    if(document.getElementById('flt-dry-macd-15')) document.getElementById('flt-dry-macd-15').value = filters.macd_15 || '';
                    if(document.getElementById('flt-dry-signal-15')) document.getElementById('flt-dry-signal-15').value = filters.signal_15 || '';
                    if(document.getElementById('flt-dry-hist-15')) document.getElementById('flt-dry-hist-15').value = filters.hist_15 || '';
                    if(document.getElementById('flt-dry-macd-45')) document.getElementById('flt-dry-macd-45').value = filters.macd_45 || '';
                    if(document.getElementById('flt-dry-signal-45')) document.getElementById('flt-dry-signal-45').value = filters.signal_45 || '';
                    if(document.getElementById('flt-dry-hist-45')) document.getElementById('flt-dry-hist-45').value = filters.hist_45 || '';
                    document.getElementById('flt-dry-trend').value = filters.trend || '';
                    document.getElementById('flt-dry-rsi').value = filters.rsi || '';
                    if(document.getElementById('flt-dry-rsi-30')) document.getElementById('flt-dry-rsi-30').value = filters.rsi_30 || '';
                    if(document.getElementById('flt-dry-rsi-60')) document.getElementById('flt-dry-rsi-60').value = filters.rsi_60 || '';
                    if(document.getElementById('flt-dry-macd-day')) document.getElementById('flt-dry-macd-day').value = filters.macd_day || '';
                    if(document.getElementById('flt-dry-signal-day')) document.getElementById('flt-dry-signal-day').value = filters.signal_day || '';
                    if(document.getElementById('flt-dry-hist-day')) document.getElementById('flt-dry-hist-day').value = filters.hist_day || '';
                    if(document.getElementById('flt-dry-rsi-day')) document.getElementById('flt-dry-rsi-day').value = filters.rsi_day || '';
                    document.getElementById('flt-dry-interp').value = filters.interp || '';
                    applyAllDryupFilters();
                }} catch(e) {{
                    console.error("Error restoring dryup filters:", e);
                }}
            }}
            
            // Reapply column visibility settings
            applyColumnVisibility();
        }}

        const DEFAULT_COLUMNS = {{
            day_change: true,
            macd_15: true,
            signal_15: true,
            hist_15: true,
            macd_45: true,
            signal_45: true,
            hist_45: true,
            trend: true,
            rsi_15: true,
            rsi_30: true,
            rsi_60: true,
            vol: true,
            avg_vol: true,
            ratio: true,
            pcr: true,
            fut_oi: true,
            oi_chg: true,
            macd_day: true,
            signal_day: true,
            hist_day: true,
            rsi_day: true,
            interp: true
        }};

        function getColumnPreferences() {{
            const saved = localStorage.getItem('macd_col_visibility');
            if (saved) {{
                try {{
                    return {{...DEFAULT_COLUMNS, ...JSON.parse(saved)}};
                }} catch(e) {{}}
            }}
            return {{...DEFAULT_COLUMNS}};
        }}

        function saveColumnPreferences(prefs) {{
            localStorage.setItem('macd_col_visibility', JSON.stringify(prefs));
        }}

        function applyColumnVisibility() {{
            const prefs = getColumnPreferences();
            for (const [col, visible] of Object.entries(prefs)) {{
                document.querySelectorAll('.col-' + col).forEach(el => {{
                    el.style.display = visible ? '' : 'none';
                }});
                const checkbox = document.getElementById('cfg-col-' + col);
                if (checkbox) {{
                    checkbox.checked = visible;
                }}
            }}
        }}

        function toggleColumn(colName) {{
            const prefs = getColumnPreferences();
            const checkbox = document.getElementById('cfg-col-' + colName);
            if (checkbox) {{
                prefs[colName] = checkbox.checked;
                saveColumnPreferences(prefs);
                applyColumnVisibility();
            }}
        }}

        function getApiUrl(path) {{
            return window.location.protocol === 'file:' ? 'http://localhost:8080' + path : path;
        }}

        function updateTrackingStatusUI(active) {{
            const btnStart = document.getElementById('btn-start');
            const btnStop = document.getElementById('btn-stop');
            const pulse = document.getElementById('status-pulse');
            const statusText = document.getElementById('status-text');
            
            if (active) {{
                if (btnStart) {{ btnStart.disabled = true; btnStart.style.opacity = 0.5; }}
                if (btnStop) {{ btnStop.disabled = false; btnStop.style.opacity = 1; }}
                if (pulse) {{
                    pulse.style.background = '#10b981';
                    pulse.style.animation = 'pulsing 1.5s infinite';
                }}
                if (statusText) statusText.innerHTML = 'LIVE MONITORING';
            }} else {{
                if (btnStart) {{ btnStart.disabled = false; btnStart.style.opacity = 1; }}
                if (btnStop) {{ btnStop.disabled = true; btnStop.style.opacity = 0.5; }}
                if (pulse) {{
                    pulse.style.background = '#9ca3af';
                    pulse.style.animation = 'none';
                }}
                if (statusText) statusText.innerHTML = 'TRACKING STOPPED';
            }}
        }}

        async function setTrackingActive(active) {{
            try {{
                const r = await fetch(getApiUrl('/config'));
                if (r.ok) {{
                    const cfg = await r.json();
                    cfg.tracking_active = active;
                    
                    const saveRes = await fetch(getApiUrl('/config'), {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify(cfg)
                    }});
                    if (saveRes.ok) {{
                        showToast(active ? "▶ Tracking started successfully!" : "⏸ Tracking stopped successfully!", false);
                        updateTrackingStatusUI(active);
                    }} else {{
                        showToast("Error updating tracking state.", true);
                    }}
                }}
            }} catch (e) {{
                showToast("Connection failed.", true);
            }}
        }}

        function toggleCustomSoundInputs(alertType) {{
            const select = document.getElementById('sound-type-' + alertType);
            const customDiv = document.getElementById('custom-fields-' + alertType);
            if (select && customDiv) {{
                customDiv.style.display = select.value === 'custom' ? 'block' : 'none';
            }}
        }}

        async function loadConfig() {{
            try {{
                const r = await fetch(getApiUrl('/config'));
                if (r.ok) {{
                    const cfg = await r.json();
                    document.getElementById('inp-interval').value = cfg.poll_interval_minutes;
                    document.getElementById('inp-momentum').value = cfg.momentum_threshold;
                    document.getElementById('inp-increase').value = cfg.min_macd_increase_alert;
                    document.getElementById('inp-vol-ratio').value = cfg.min_volume_ratio_alert !== undefined ? cfg.min_volume_ratio_alert : 2.0;
                    
                    document.getElementById('cfg-audio-enabled').checked = cfg.audio_alerts_enabled !== false;
                    document.getElementById('cfg-audio-startup').checked = cfg.audio_play_on_startup !== false;
                    
                    const profiles = cfg.audio_alert_profiles || {{}};
                    const alertTypes = [
                        "BULLISH_CROSSOVER", "BEARISH_CROSSOVER", "MOMENTUM_START", 
                        "VOLUME_DRYUP", "HIGH_VOLUME", "MACD_INCREASE", "HISTOGRAM_ACCELERATING"
                    ];
                    
                    alertTypes.forEach(atype => {{
                        const prof = profiles[atype] || {{}};
                        const enabledCb = document.getElementById('cfg-sound-enabled-' + atype);
                        if (enabledCb) enabledCb.checked = prof.enabled !== false;
                        
                        const typeSelect = document.getElementById('sound-type-' + atype);
                        if (typeSelect) {{
                            typeSelect.value = prof.sound_type || 'beep';
                            toggleCustomSoundInputs(atype);
                        }}
                        
                        const freqInput = document.getElementById('sound-freq-' + atype);
                        if (freqInput) freqInput.value = prof.custom_frequencies || '';
                        
                        const durInput = document.getElementById('sound-dur-' + atype);
                        if (durInput) durInput.value = prof.custom_durations || '';
                        
                        const waveSelect = document.getElementById('sound-wave-' + atype);
                        if (waveSelect) waveSelect.value = prof.custom_wave || 'sine';
                    }});
                    
                    document.getElementById('cfg-enable-ai').checked = cfg.enable_adaptive_ai_filters || false;
                    document.getElementById('cfg-enable-retro').checked = cfg.enable_eod_retrospective !== false;
                    
                    const loggingEnabled = cfg.logging_enabled !== false;
                    const loggingCb = document.getElementById('cfg-enable-logging');
                    if (loggingCb) loggingCb.checked = loggingEnabled;
                    const logPre = document.getElementById('system-logs-content');
                    if (logPre) logPre.style.display = loggingEnabled ? 'block' : 'none';
                    const logPlaceholder = document.getElementById('system-logs-disabled-message');
                    if (logPlaceholder) logPlaceholder.style.display = loggingEnabled ? 'none' : 'block';
                    
                    const trackingActive = cfg.tracking_active !== false;
                    updateTrackingStatusUI(trackingActive);
                }}
            }} catch (e) {{
                console.error("Error loading config:", e);
            }}
        }}
        
        async function saveConfig() {{
            const alertTypes = [
                "BULLISH_CROSSOVER", "BEARISH_CROSSOVER", "MOMENTUM_START", 
                "VOLUME_DRYUP", "HIGH_VOLUME", "MACD_INCREASE", "HISTOGRAM_ACCELERATING"
            ];
            const profiles = {{}};
            alertTypes.forEach(atype => {{
                profiles[atype] = {{
                    enabled: document.getElementById('cfg-sound-enabled-' + atype).checked,
                    sound_type: document.getElementById('sound-type-' + atype).value,
                    custom_frequencies: document.getElementById('sound-freq-' + atype).value,
                    custom_durations: document.getElementById('sound-dur-' + atype).value,
                    custom_wave: document.getElementById('sound-wave-' + atype).value
                }};
            }});

            const payload = {{
                poll_interval_minutes: parseFloat(document.getElementById('inp-interval').value),
                momentum_threshold: parseFloat(document.getElementById('inp-momentum').value),
                min_macd_increase_alert: parseFloat(document.getElementById('inp-increase').value),
                min_volume_ratio_alert: parseFloat(document.getElementById('inp-vol-ratio').value),
                
                audio_alerts_enabled: document.getElementById('cfg-audio-enabled').checked,
                audio_play_on_startup: document.getElementById('cfg-audio-startup').checked,
                audio_alert_profiles: profiles,
                
                enable_adaptive_ai_filters: document.getElementById('cfg-enable-ai').checked,
                enable_eod_retrospective: document.getElementById('cfg-enable-retro').checked,
                logging_enabled: document.getElementById('cfg-enable-logging') ? document.getElementById('cfg-enable-logging').checked : true
            }};
            
            try {{
                const r = await fetch(getApiUrl('/config'), {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify(payload)
                }});
                if (r.ok) {{
                    showToast("Settings saved successfully! Config updated.", false);
                    setTimeout(() => location.reload(), 1000);
                }} else {{
                    showToast("Error saving settings.", true);
                }}
            }} catch (e) {{
                showToast("Connection failed.", true);
            }}
        }}
        
        async function triggerForceFetch() {{
            const btn = document.getElementById('btn-force-fetch');
            const progressContainer = document.getElementById('fetch-progress-container');
            const progressText = document.getElementById('fetch-progress-text');
            const progressBar = document.getElementById('fetch-progress-bar');
            
            btn.disabled = true;
            btn.innerHTML = '⏳ Initializing...';
            progressContainer.style.display = 'block';
            progressBar.style.width = '0%';
            progressText.innerHTML = 'Starting background fetch...';
            
            try {{
                const r = await fetch(getApiUrl('/force_fetch'), {{
                    method: 'POST'
                }});
                
                if (r.ok) {{
                    showToast("⚡ Force fetch started in background", false);
                    
                    // Poll progress
                    const pollInterval = setInterval(async () => {{
                        try {{
                            const res = await fetch(getApiUrl('/force_fetch_status'));
                            if (res.ok) {{
                                const status = await res.json();
                                if (status.running) {{
                                    btn.innerHTML = '⏳ Fetching...';
                                    const pct = status.total > 0 ? Math.round((status.progress / status.total) * 100) : 0;
                                    progressBar.style.width = pct + '%';
                                    progressText.innerHTML = status.message + ' (' + pct + '%)';
                                }} else {{
                                    clearInterval(pollInterval);
                                    progressBar.style.width = '100%';
                                    
                                    if (status.error) {{
                                        progressText.innerHTML = 'Error: ' + status.error;
                                        showToast("❌ Fetch failed: " + status.error, true);
                                        btn.innerHTML = '⚡ Force Fetch TV Data';
                                        btn.disabled = false;
                                    }} else {{
                                        progressText.innerHTML = 'Success!';
                                        btn.innerHTML = '⚡ Force Fetch TV Data';
                                        btn.disabled = false;
                                        showToast("⚡ Data fetched successfully!", false);
                                        updateDashboardSeamlessly();
                                        setTimeout(() => {{
                                            progressContainer.style.display = 'none';
                                        }}, 3000);
                                    }}
                                }}
                            }}
                        }} catch (err) {{
                            console.error(err);
                        }}
                    }}, 1000);
                    
                }} else {{
                    let errMsg = "Error triggering force fetch.";
                    try {{
                        const errData = await r.json();
                        if (errData && errData.error) errMsg = errData.error;
                    }} catch (e) {{}}
                    showToast(errMsg, true);
                    btn.disabled = false;
                    btn.innerHTML = '⚡ Force Fetch TV Data';
                    progressContainer.style.display = 'none';
                }}
            }} catch (e) {{
                showToast("Connection failed.", true);
                btn.disabled = false;
                btn.innerHTML = '⚡ Force Fetch TV Data';
                progressContainer.style.display = 'none';
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
        
        // Table Sorting Logic
        const sortStates = {{}};

        function getTableId(table) {{
            if (table.id) return table.id;
            const parentDiv = table.closest('div[id]');
            if (parentDiv) return parentDiv.id + '-table';
            const allTables = Array.from(document.querySelectorAll('table'));
            return 'table-' + allTables.indexOf(table);
        }}

        function getCellValue(row, index) {{
            const cell = row.children[index];
            if (!cell) return '';
            let text = cell.textContent || cell.innerText || '';
            text = text.trim();
            if (text === '—' || text === '') return -Infinity;
            
            // Clean currency, percentage symbols and commas
            let cleaned = text.replace(/[₹$,%]/g, '');
            
            // Handle K, M, B multipliers
            if (cleaned.toUpperCase().endsWith('K')) {{
                const val = parseFloat(cleaned.slice(0, -1));
                if (!isNaN(val)) return val * 1000;
            }}
            if (cleaned.toUpperCase().endsWith('M')) {{
                const val = parseFloat(cleaned.slice(0, -1));
                if (!isNaN(val)) return val * 1000000;
            }}
            if (cleaned.toUpperCase().endsWith('B')) {{
                const val = parseFloat(cleaned.slice(0, -1));
                if (!isNaN(val)) return val * 1000000000;
            }}
            
            // Parse as float if valid number
            const num = parseFloat(cleaned);
            if (!isNaN(num) && isFinite(cleaned)) {{
                return num;
            }}
            
            return text.toLowerCase();
        }}

        function sortTable(table, colIndex, ascending) {{
            const tbody = table.querySelector('tbody');
            if (!tbody) return;
            
            const rows = Array.from(tbody.querySelectorAll('tr'));
            if (rows.length <= 1) return;
            
            const isPlaceholder = (row) => row.querySelector('td[colspan]');
            const dataRows = rows.filter(row => !isPlaceholder(row));
            const placeholderRows = rows.filter(row => isPlaceholder(row));
            
            if (dataRows.length === 0) return;
            
            dataRows.sort((rowA, rowB) => {{
                const valA = getCellValue(rowA, colIndex);
                const valB = getCellValue(rowB, colIndex);
                
                if (valA === -Infinity) return ascending ? 1 : -1;
                if (valB === -Infinity) return ascending ? -1 : 1;
                
                if (typeof valA === 'number' && typeof valB === 'number') {{
                    return ascending ? valA - valB : valB - valA;
                }}
                
                const strA = String(valA);
                const strB = String(valB);
                return ascending ? strA.localeCompare(strB) : strB.localeCompare(strA);
            }});
            
            tbody.innerHTML = '';
            dataRows.forEach(row => tbody.appendChild(row));
            placeholderRows.forEach(row => tbody.appendChild(row));
        }}

        function updateHeaderIndicators(table, activeColIndex, ascending) {{
            const headers = table.querySelectorAll('th');
            headers.forEach((th, idx) => {{
                let indicator = th.querySelector('.sort-indicator');
                if (!indicator) {{
                    indicator = document.createElement('span');
                    indicator.className = 'sort-indicator';
                    indicator.style.marginLeft = '6px';
                    indicator.style.fontSize = '10px';
                    indicator.style.display = 'inline-block';
                    th.appendChild(indicator);
                }}
                
                if (idx === activeColIndex) {{
                    indicator.textContent = ascending ? ' ▲' : ' ▼';
                    indicator.style.color = '#3b82f6';
                }} else {{
                    indicator.textContent = ' ↕';
                    indicator.style.color = 'rgba(255,255,255,0.2)';
                }}
            }});
        }}

        function reapplySorting() {{
            document.querySelectorAll('table').forEach(table => {{
                const tableId = getTableId(table);
                const state = sortStates[tableId];
                if (state) {{
                    sortTable(table, state.colIndex, state.ascending);
                    updateHeaderIndicators(table, state.colIndex, state.ascending);
                }} else {{
                    // Initialize default sort indicators (↕)
                    table.querySelectorAll('th').forEach((th, idx) => {{
                        let indicator = th.querySelector('.sort-indicator');
                        if (!indicator) {{
                            indicator = document.createElement('span');
                            indicator.className = 'sort-indicator';
                            indicator.style.marginLeft = '6px';
                            indicator.style.fontSize = '10px';
                            indicator.style.display = 'inline-block';
                            indicator.textContent = ' ↕';
                            indicator.style.color = 'rgba(255,255,255,0.2)';
                            th.appendChild(indicator);
                        }}
                    }});
                }}
            }});
        }}

        // Global Event Listener for table header click sorting
        document.addEventListener('click', function(e) {{
            const th = e.target.closest('th');
            if (!th) return;
            
            const table = th.closest('table');
            if (!table) return;
            
            // Do not sort if clicked inside an input element (like filter inputs)
            if (e.target.tagName === 'INPUT') return;
            
            const thIndex = Array.from(th.parentNode.children).indexOf(th);
            const tableId = getTableId(table);
            
            // Toggle direction
            let ascending = true;
            if (sortStates[tableId] && sortStates[tableId].colIndex === thIndex) {{
                ascending = !sortStates[tableId].ascending;
            }}
            
            sortStates[tableId] = {{ colIndex: thIndex, ascending: ascending }};
            
            sortTable(table, thIndex, ascending);
            updateHeaderIndicators(table, thIndex, ascending);
        }});

        let allRecentAlerts = [];

        function renderFocusAlerts() {{
            const jsonEl = document.getElementById('raw-alerts-json');
            if (jsonEl) {{
                try {{
                    allRecentAlerts = JSON.parse(jsonEl.textContent.trim());
                }} catch (e) {{
                    console.error("Error parsing raw alerts JSON:", e);
                }}
            }}
            
            const tbody = document.getElementById('focus-table-body');
            if (!tbody) return;
            
            const minVolRatio = parseFloat(document.getElementById('inp-focus-vol-ratio').value) || 0;
            const minSeverity = document.getElementById('inp-focus-severity').value;
            const alertTypeFilter = document.getElementById('inp-focus-type').value;
            const sortCol = document.getElementById('inp-focus-sort-col').value;
            const sortOrder = document.getElementById('inp-focus-sort-order').value;
            
            const severityOrder = {{ 'INFO': 1, 'MEDIUM': 2, 'HIGH': 3, 'CRITICAL': 4 }};
            const minSevLevel = severityOrder[minSeverity] || 1;
            
            let filtered = allRecentAlerts.filter(a => {{
                const vol = a.volume;
                const avgVol = a.average_volume;
                const ratio = (vol && avgVol && avgVol > 0) ? ((vol / avgVol) * 100) : 0;
                
                if (ratio < minVolRatio) return false;
                
                const aSev = a.severity || 'INFO';
                const aSevLevel = severityOrder[aSev] || 1;
                if (aSevLevel < minSevLevel) return false;
                
                if (alertTypeFilter !== 'ALL' && a.alert_type !== alertTypeFilter) return false;
                
                return true;
            }});
            
            filtered.sort((x, y) => {{
                let valX, valY;
                
                if (sortCol === 'vol_ratio') {{
                    valX = (x.volume && x.average_volume && x.average_volume > 0) ? ((x.volume / x.average_volume) * 100) : 0;
                    valY = (y.volume && y.average_volume && y.average_volume > 0) ? ((y.volume / y.average_volume) * 100) : 0;
                }} else if (sortCol === 'severity') {{
                    valX = severityOrder[x.severity || 'INFO'] || 1;
                    valY = severityOrder[y.severity || 'INFO'] || 1;
                }} else if (sortCol === 'price') {{
                    valX = x.price || 0;
                    valY = y.price || 0;
                }} else if (sortCol === 'symbol') {{
                    valX = (x.symbol || '').toLowerCase();
                    valY = (y.symbol || '').toLowerCase();
                }} else {{
                    valX = x.timestamp || '';
                    valY = y.timestamp || '';
                }}
                
                if (valX === valY) return 0;
                
                const asc = (sortOrder === 'asc');
                if (typeof valX === 'number' && typeof valY === 'number') {{
                    return asc ? valX - valY : valY - valX;
                }}
                
                const strX = String(valX);
                const strY = String(valY);
                return asc ? strX.localeCompare(strY) : strY.localeCompare(strX);
            }});
            
            if (filtered.length === 0) {{
                tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding: 40px; color: var(--text-muted);">No important alerts match the selected criteria. Try adjusting the thresholds.</td></tr>';
                return;
            }}
            
            let htmlRows = '';
            filtered.forEach(a => {{
                const sevColor = a.severity === 'CRITICAL' ? '#ef4444' : a.severity === 'HIGH' ? '#f97316' : a.severity === 'MEDIUM' ? '#eab308' : '#3b82f6';
                const rsiVal = a.rsi;
                const rsiStr = rsiVal !== null && rsiVal !== undefined ? rsiVal.toFixed(1) : '—';
                const vol = a.volume;
                const avgVol = a.average_volume;
                const ratio = (vol && avgVol && avgVol > 0) ? ((vol / avgVol) * 100) : 0;
                
                htmlRows += `
                <tr>
                    <td>${{a.timestamp}}</td>
                    <td style="font-weight: bold; color: #fff;">${{a.symbol}}</td>
                    <td>₹${{a.price.toFixed(2)}}</td>
                    <td><span style="color: ${{sevColor}}; font-weight: bold; background: ${{sevColor}}18; padding: 2px 8px; border-radius: 12px; font-size: 11px;">${{a.severity}}</span></td>
                    <td>${{a.alert_type}}</td>
                    <td style="color: #cbd5e1;">${{a.message}}</td>
                    <td style="font-weight: bold; color: ${{ratio >= 200 ? '#10b981' : '#fbbf24'}}">${{ratio.toFixed(1)}}%</td>
                    <td>${{a.macd_line.toFixed(3)}}</td>
                    <td>${{rsiStr}}</td>
                </tr>
                `;
            }});
            
            tbody.innerHTML = htmlRows;
        }}

        async function clearSystemLogs() {{
            if (!confirm("Are you sure you want to clear all system logs? This will truncate the log file on the server.")) return;
            try {{
                const r = await fetch(getApiUrl('/clear_logs'), {{ method: 'POST' }});
                if (r.ok) {{
                    showToast("📝 Logs successfully cleared!", false);
                    const pre = document.getElementById('system-logs-content');
                    if (pre) pre.textContent = "Logs cleared.";
                }} else {{
                    showToast("Error clearing logs.", true);
                }}
            }} catch (e) {{
                showToast("Connection failed.", true);
            }}
        }}

        async function toggleEnableLogging(cb) {{
            const enabled = cb.checked;
            const pre = document.getElementById('system-logs-content');
            if (pre) {{
                pre.style.display = enabled ? 'block' : 'none';
            }}
            const placeholder = document.getElementById('system-logs-disabled-message');
            if (placeholder) {{
                placeholder.style.display = enabled ? 'none' : 'block';
            }}
            
            try {{
                const r = await fetch(getApiUrl('/config'), {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ logging_enabled: enabled }})
                }});
                if (r.ok) {{
                    showToast(enabled ? "📝 System logging enabled!" : "⏸ System logging disabled!", false);
                    updateDashboardSeamlessly();
                }} else {{
                    showToast("Error updating logging state.", true);
                }}
            }} catch (e) {{
                showToast("Connection failed.", true);
            }}
        }}

        async function toggleAISuppression(isActive) {{
            try {{
                const r = await fetch(getApiUrl('/config'), {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ enable_adaptive_ai_filters: !isActive }})
                }});
                if (r.ok) {{
                    showToast(!isActive ? "🤖 AI Optimization activated!" : "⏸ AI Optimization stopped!", false);
                    setTimeout(() => location.reload(), 1000);
                }} else {{
                    showToast("Error updating AI Optimization state.", true);
                }}
            }} catch (e) {{
                showToast("Connection failed.", true);
            }}
        }}

        async function toggleEODRetrospective(isActive) {{
            try {{
                const r = await fetch(getApiUrl('/config'), {{
                    method: 'POST',
                    headers: {{ 'Content-Type': 'application/json' }},
                    body: JSON.stringify({{ enable_eod_retrospective: !isActive }})
                }});
                if (r.ok) {{
                    showToast(!isActive ? "🔄 EOD Retrospective activated!" : "⏸ EOD Retrospective stopped!", false);
                    setTimeout(() => location.reload(), 1000);
                }} else {{
                    showToast("Error updating retrospective state.", true);
                }}
            }} catch (e) {{
                showToast("Connection failed.", true);
            }}
        }}

        function toggleItemDetails(itemId) {{
            const detailsRow = document.getElementById('details-' + itemId);
            if (detailsRow) {{
                const isHidden = detailsRow.style.display === 'none';
                detailsRow.style.display = isHidden ? 'table-row' : 'none';
            }}
        }}

        async function triggerForceRetrospective() {{
            const btn = document.getElementById('btn-force-retro');
            if (btn) {{
                btn.disabled = true;
                btn.textContent = "⏳ Running...";
            }}
            try {{
                const r = await fetch(getApiUrl('/force_retro'), {{ method: 'POST' }});
                if (r.ok) {{
                    showToast("⚡ Retrospective evaluation started in the background!", false);
                    setTimeout(() => location.reload(), 1500);
                }} else {{
                    showToast("Error triggering retrospective.", true);
                    if (btn) {{
                        btn.disabled = false;
                        btn.textContent = "⚡ Run Retrospective Now";
                    }}
                }}
            }} catch (e) {{
                showToast("Connection failed.", true);
                if (btn) {{
                    btn.disabled = false;
                    btn.textContent = "⚡ Run Retrospective Now";
                }}
            }}
        }}

        // ── Web Audio API Client Engine ──────────────────────────────────────
        let playedAlerts = new Set();
        let systemConfig = null;

        async function fetchSystemConfigAndInit() {{
            try {{
                const r = await fetch(getApiUrl('/config'));
                if (r.ok) {{
                    systemConfig = await r.json();
                    updateAudioToggleButtonUI();
                    
                    const rawDiv = document.getElementById('raw-alerts-json');
                    if (rawDiv && rawDiv.textContent.trim()) {{
                        try {{
                            const alerts = JSON.parse(rawDiv.textContent);
                            alerts.forEach(a => {{
                                const sig = a.timestamp + '_' + a.symbol + '_' + a.alert_type;
                                playedAlerts.add(sig);
                            }});
                        }} catch(e) {{
                            console.error("Error parsing initial alerts:", e);
                        }}
                    }}
                    
                    if (systemConfig.audio_alerts_enabled && systemConfig.audio_play_on_startup && getLocalAudioEnabled()) {{
                        setTimeout(() => {{
                            playAudioPattern('startup');
                        }}, 800);
                    }}
                }}
            }} catch (e) {{
                console.error("Error loading config for audio:", e);
            }}
        }}

        function getLocalAudioEnabled() {{
            return localStorage.getItem('localAudioEnabled') !== 'false';
        }}

        function setLocalAudioEnabled(val) {{
            localStorage.setItem('localAudioEnabled', val ? 'true' : 'false');
            updateAudioToggleButtonUI();
        }}

        function updateAudioToggleButtonUI() {{
            const btn = document.getElementById('btn-audio-toggle');
            if (!btn) return;
            const localEnabled = getLocalAudioEnabled();
            const globalEnabled = systemConfig ? systemConfig.audio_alerts_enabled : true;
            
            if (!globalEnabled) {{
                btn.innerHTML = '🔇 Sound Disabled Globally';
                btn.style.background = '#dc2626';
                btn.style.boxShadow = 'none';
                btn.disabled = true;
            }} else if (localEnabled) {{
                btn.innerHTML = '🔊 Sound Enabled';
                btn.style.background = '#3b82f6';
                btn.style.boxShadow = '0 4px 12px rgba(59, 130, 246, 0.2)';
                btn.disabled = false;
            }} else {{
                btn.innerHTML = '🔇 Sound Muted';
                btn.style.background = '#6b7280';
                btn.style.boxShadow = 'none';
                btn.disabled = false;
            }}
        }}

        function toggleAudioMuteState() {{
            const nextVal = !getLocalAudioEnabled();
            setLocalAudioEnabled(nextVal);
            if (nextVal) {{
                playAudioPattern('beep');
            }}
        }}

        let audioCtx = null;
        function getAudioContext() {{
            if (!audioCtx) {{
                audioCtx = new (window.AudioContext || window.webkitAudioContext)();
            }}
            if (audioCtx.state === 'suspended') {{
                audioCtx.resume();
            }}
            return audioCtx;
        }}

        function playTone(freq, type, duration, startTime, volume = 0.15) {{
            const ctx = getAudioContext();
            const osc = ctx.createOscillator();
            const gainNode = ctx.createGain();
            
            osc.type = type;
            osc.frequency.setValueAtTime(freq, startTime);
            
            gainNode.gain.setValueAtTime(volume, startTime);
            gainNode.gain.exponentialRampToValueAtTime(0.001, startTime + duration - 0.02);
            
            osc.connect(gainNode);
            gainNode.connect(ctx.destination);
            
            osc.start(startTime);
            osc.stop(startTime + duration);
        }}

        const SOUND_PATTERNS = {{
            startup: [
                {{ freq: 261.63, type: 'sine', duration: 0.12 }},
                {{ freq: 329.63, type: 'sine', duration: 0.12 }},
                {{ freq: 392.00, type: 'sine', duration: 0.12 }},
                {{ freq: 523.25, type: 'sine', duration: 0.25 }}
            ],
            chirp: [
                {{ freq: 523.25, type: 'sine', duration: 0.08 }},
                {{ freq: 659.25, type: 'sine', duration: 0.08 }},
                {{ freq: 783.99, type: 'sine', duration: 0.18 }}
            ],
            warning: [
                {{ freq: 392.00, type: 'triangle', duration: 0.1 }},
                {{ freq: 329.63, type: 'triangle', duration: 0.1 }},
                {{ freq: 261.63, type: 'sawtooth', duration: 0.22 }}
            ],
            siren: [
                {{ freq: 880.00, type: 'sawtooth', duration: 0.12 }},
                {{ freq: 660.00, type: 'sawtooth', duration: 0.12 }},
                {{ freq: 880.00, type: 'sawtooth', duration: 0.12 }},
                {{ freq: 660.00, type: 'sawtooth', duration: 0.22 }}
            ],
            'double-chirp': [
                {{ freq: 659.25, type: 'sine', duration: 0.06 }},
                {{ freq: 783.99, type: 'sine', duration: 0.06 }},
                {{ freq: 0, type: 'sine', duration: 0.04 }},
                {{ freq: 659.25, type: 'sine', duration: 0.06 }},
                {{ freq: 783.99, type: 'sine', duration: 0.12 }}
            ],
            tada: [
                {{ freq: 440.00, type: 'sine', duration: 0.08 }},
                {{ freq: 440.00, type: 'sine', duration: 0.08 }},
                {{ freq: 554.37, type: 'sine', duration: 0.1 }},
                {{ freq: 659.25, type: 'sine', duration: 0.25 }}
            ],
            bell: [
                {{ freq: 987.77, type: 'sine', duration: 0.12 }},
                {{ freq: 783.99, type: 'sine', duration: 0.25 }}
            ],
            beep: [
                {{ freq: 523.25, type: 'sine', duration: 0.15 }}
            ],
            'beep-low': [
                {{ freq: 261.63, type: 'sine', duration: 0.15 }}
            ],
            'double-beep': [
                {{ freq: 523.25, type: 'sine', duration: 0.08 }},
                {{ freq: 0, type: 'sine', duration: 0.04 }},
                {{ freq: 523.25, type: 'sine', duration: 0.12 }}
            ],
            buzz: [
                {{ freq: 196.00, type: 'sawtooth', duration: 0.25 }}
            ]
        }};

        function playAudioPattern(patternName) {{
            try {{
                const pattern = SOUND_PATTERNS[patternName];
                if (!pattern) return;
                const ctx = getAudioContext();
                let time = ctx.currentTime;
                pattern.forEach(note => {{
                    if (note.freq > 0) {{
                        playTone(note.freq, note.type, note.duration, time);
                    }}
                    time += note.duration;
                }});
            }} catch (e) {{
                console.error("Audio playback error:", e);
                const btn = document.getElementById('btn-audio-toggle');
                if (btn) {{
                    btn.innerHTML = '⚠️ Click to Enable Sound';
                    btn.style.background = '#f59e0b';
                }}
            }}
        }}

        function playCustomNotes(freqStr, durStr, waveType) {{
            try {{
                const freqs = freqStr.split(',').map(f => parseFloat(f.trim())).filter(f => !isNaN(f));
                const durs = durStr.split(',').map(d => parseFloat(d.trim())).filter(d => !isNaN(d));
                
                if (freqs.length === 0 || durs.length === 0) return;
                
                const ctx = getAudioContext();
                let time = ctx.currentTime;
                
                for (let i = 0; i < freqs.length; i++) {{
                    const freq = freqs[i];
                    const dur = durs[i] !== undefined ? durs[i] : (durs[durs.length - 1] || 0.15);
                    if (freq > 0) {{
                        playTone(freq, waveType, dur, time);
                    }}
                    time += dur;
                }}
            }} catch(e) {{
                console.error("Error playing custom tone:", e);
            }}
        }}

        function testTone(alertType) {{
            const typeSelect = document.getElementById('sound-type-' + alertType);
            if (!typeSelect) return;
            const soundType = typeSelect.value;
            
            if (soundType === 'none') return;
            
            if (soundType === 'custom') {{
                const freqStr = document.getElementById('sound-freq-' + alertType).value;
                const durStr = document.getElementById('sound-dur-' + alertType).value;
                const waveType = document.getElementById('sound-wave-' + alertType).value;
                playCustomNotes(freqStr, durStr, waveType);
            }} else {{
                playAudioPattern(soundType);
            }}
        }}

        function checkForNewAlerts() {{
            const rawDiv = document.getElementById('raw-alerts-json');
            if (!rawDiv || !rawDiv.textContent.trim()) return;
            
            try {{
                const alerts = JSON.parse(rawDiv.textContent);
                let alertsToPlay = [];
                
                alerts.forEach(a => {{
                    const sig = a.timestamp + '_' + a.symbol + '_' + a.alert_type;
                    if (!playedAlerts.has(sig)) {{
                        playedAlerts.add(sig);
                        alertsToPlay.push(a);
                    }}
                }});
                
                if (alertsToPlay.length > 0 && getLocalAudioEnabled() && systemConfig && systemConfig.audio_alerts_enabled) {{
                    let highestAlert = null;
                    const priorityMap = {{
                        'MOMENTUM_START': 10,
                        'HIGH_VOLUME': 9,
                        'BULLISH_CROSSOVER': 8,
                        'BEARISH_CROSSOVER': 8,
                        'VOLUME_DRYUP': 7,
                        'MACD_INCREASE': 6,
                        'HISTOGRAM_ACCELERATING': 6
                    }};
                    
                    alertsToPlay.forEach(a => {{
                        if (!highestAlert || (priorityMap[a.alert_type] || 0) > (priorityMap[highestAlert.alert_type] || 0)) {{
                            highestAlert = a;
                        }}
                    }});
                    
                    if (highestAlert) {{
                        const profiles = systemConfig.audio_alert_profiles || {{}};
                        const profile = profiles[highestAlert.alert_type] || {{}};
                        
                        if (profile.enabled !== false) {{
                            const soundType = profile.sound_type || 'beep';
                            if (soundType === 'custom') {{
                                playCustomNotes(profile.custom_frequencies || '', profile.custom_durations || '', profile.custom_wave || 'sine');
                            }} else if (soundType !== 'none') {{
                                playAudioPattern(soundType);
                            }}
                            showToast(`🔊 Audible Alert: ${{highestAlert.alert_type}} for ${{highestAlert.symbol}}`, false);
                        }}
                    }}
                }}
            }} catch (e) {{
                console.error("Error checking alerts:", e);
            }}
        }}

        loadConfig();
        fetchSystemConfigAndInit();
        setTimeout(restoreFilters, 100);
        setTimeout(reapplySorting, 150);
        setTimeout(renderFocusAlerts, 160);
    </script>
    <div id="raw-alerts-json" style="display:none;">{alerts_json_str}</div>
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
