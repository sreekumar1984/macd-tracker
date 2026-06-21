import os
import sqlite3
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_DIR = os.path.join(BASE_DIR, "db")
DB_PATH = os.path.join(DB_DIR, "macd_history.db")

def init_db():
    os.makedirs(DB_DIR, exist_ok=True)
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create tables if not exists
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS macd_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            price REAL,
            day_change REAL,
            macd_line REAL,
            signal_line REAL,
            histogram REAL,
            rsi REAL,
            volume REAL,
            average_volume REAL,
            total_ce_oi REAL,
            total_pe_oi REAL,
            pcr REAL,
            futures_oi REAL,
            futures_oi_change_pct REAL,
            rsi_30 REAL,
            rsi_60 REAL,
            macd_day REAL,
            macd_signal_day REAL,
            macd_hist_day REAL,
            rsi_day REAL,
            macd_45 REAL,
            macd_signal_45 REAL,
            macd_hist_45 REAL
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alerts_triggered (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            price REAL NOT NULL,
            day_change REAL,
            alert_type TEXT NOT NULL,
            message TEXT NOT NULL,
            severity TEXT NOT NULL,
            macd_line REAL,
            signal_line REAL,
            histogram REAL,
            macd_change REAL,
            histogram_change REAL,
            rsi REAL,
            volume REAL,
            average_volume REAL,
            total_ce_oi REAL,
            total_pe_oi REAL,
            pcr REAL,
            futures_oi REAL,
            futures_oi_change_pct REAL,
            rsi_30 REAL,
            rsi_60 REAL,
            macd_day REAL,
            macd_signal_day REAL,
            macd_hist_day REAL,
            rsi_day REAL,
            macd_45 REAL,
            macd_signal_45 REAL,
            macd_hist_45 REAL
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS alert_retrospectives (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_timestamp TEXT NOT NULL,
            symbol TEXT NOT NULL,
            alert_type TEXT NOT NULL,
            signal_price REAL NOT NULL,
            eod_price REAL,
            pct_change REAL,
            status TEXT NOT NULL, -- 'SUCCESS', 'FAILED', 'NEUTRAL'
            failure_reason TEXT,
            eval_timestamp TEXT NOT NULL
        )
    """)

    
    # Run automatic database migrations
    cursor.execute("PRAGMA table_info(macd_records)")
    columns = [col[1] for col in cursor.fetchall()]
    if 'rsi' not in columns:
        print("  🗄️ Database Migration: Adding 'rsi' column to 'macd_records'...")
        cursor.execute("ALTER TABLE macd_records ADD COLUMN rsi REAL")
    if 'volume' not in columns:
        print("  🗄️ Database Migration: Adding 'volume' column to 'macd_records'...")
        cursor.execute("ALTER TABLE macd_records ADD COLUMN volume REAL")
    if 'average_volume' not in columns:
        print("  🗄️ Database Migration: Adding 'average_volume' column to 'macd_records'...")
        cursor.execute("ALTER TABLE macd_records ADD COLUMN average_volume REAL")
    if 'total_ce_oi' not in columns:
        print("  🗄️ Database Migration: Adding 'total_ce_oi' column to 'macd_records'...")
        cursor.execute("ALTER TABLE macd_records ADD COLUMN total_ce_oi REAL")
    if 'total_pe_oi' not in columns:
        print("  🗄️ Database Migration: Adding 'total_pe_oi' column to 'macd_records'...")
        cursor.execute("ALTER TABLE macd_records ADD COLUMN total_pe_oi REAL")
    if 'pcr' not in columns:
        print("  🗄️ Database Migration: Adding 'pcr' column to 'macd_records'...")
        cursor.execute("ALTER TABLE macd_records ADD COLUMN pcr REAL")
    if 'futures_oi' not in columns:
        print("  🗄️ Database Migration: Adding 'futures_oi' column to 'macd_records'...")
        cursor.execute("ALTER TABLE macd_records ADD COLUMN futures_oi REAL")
    if 'futures_oi_change_pct' not in columns:
        print("  🗄️ Database Migration: Adding 'futures_oi_change_pct' column to 'macd_records'...")
        cursor.execute("ALTER TABLE macd_records ADD COLUMN futures_oi_change_pct REAL")
    if 'day_change' not in columns:
        print("  🗄️ Database Migration: Adding 'day_change' column to 'macd_records'...")
        cursor.execute("ALTER TABLE macd_records ADD COLUMN day_change REAL")
        
    for new_col in ['rsi_30', 'rsi_60', 'macd_day', 'macd_signal_day', 'macd_hist_day', 'rsi_day', 'macd_45', 'macd_signal_45', 'macd_hist_45']:
        if new_col not in columns:
            print(f"  🗄️ Database Migration: Adding '{new_col}' column to 'macd_records'...")
            cursor.execute(f"ALTER TABLE macd_records ADD COLUMN {new_col} REAL")
        
    # Also migrate alerts_triggered
    cursor.execute("PRAGMA table_info(alerts_triggered)")
    alert_columns = [col[1] for col in cursor.fetchall()]
    if 'total_ce_oi' not in alert_columns:
        print("  🗄️ Database Migration: Adding 'total_ce_oi' column to 'alerts_triggered'...")
        cursor.execute("ALTER TABLE alerts_triggered ADD COLUMN total_ce_oi REAL")
    if 'total_pe_oi' not in alert_columns:
        print("  🗄️ Database Migration: Adding 'total_pe_oi' column to 'alerts_triggered'...")
        cursor.execute("ALTER TABLE alerts_triggered ADD COLUMN total_pe_oi REAL")
    if 'pcr' not in alert_columns:
        print("  🗄️ Database Migration: Adding 'pcr' column to 'alerts_triggered'...")
        cursor.execute("ALTER TABLE alerts_triggered ADD COLUMN pcr REAL")
    if 'futures_oi' not in alert_columns:
        print("  🗄️ Database Migration: Adding 'futures_oi' column to 'alerts_triggered'...")
        cursor.execute("ALTER TABLE alerts_triggered ADD COLUMN futures_oi REAL")
    if 'futures_oi_change_pct' not in alert_columns:
        print("  🗄️ Database Migration: Adding 'futures_oi_change_pct' column to 'alerts_triggered'...")
        cursor.execute("ALTER TABLE alerts_triggered ADD COLUMN futures_oi_change_pct REAL")
    if 'day_change' not in alert_columns:
        print("  🗄️ Database Migration: Adding 'day_change' column to 'alerts_triggered'...")
        cursor.execute("ALTER TABLE alerts_triggered ADD COLUMN day_change REAL")
        
    for new_col in ['rsi_30', 'rsi_60', 'macd_day', 'macd_signal_day', 'macd_hist_day', 'rsi_day', 'macd_45', 'macd_signal_45', 'macd_hist_45']:
        if new_col not in alert_columns:
            print(f"  🗄️ Database Migration: Adding '{new_col}' column to 'alerts_triggered'...")
            cursor.execute(f"ALTER TABLE alerts_triggered ADD COLUMN {new_col} REAL")
    
    # Create indexes for fast querying
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_records_symbol_time ON macd_records (symbol, timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_records_time ON macd_records (timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_sym_time ON alerts_triggered (symbol, timestamp)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_retro_sym_time ON alert_retrospectives (symbol, alert_timestamp)")
    
    conn.commit()
    conn.close()
    print(f"Database initialized at {DB_PATH}")
 
def insert_records(records):
    """
    records is a list of tuples: (timestamp, symbol, price, day_change, macd_line, signal_line, histogram, rsi, volume, average_volume, total_ce_oi, total_pe_oi, pcr, futures_oi, futures_oi_change_pct, rsi_30, rsi_60, macd_day, macd_signal_day, macd_hist_day, rsi_day, macd_45, macd_signal_45, macd_hist_45)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.executemany("""
        INSERT INTO macd_records (timestamp, symbol, price, day_change, macd_line, signal_line, histogram, rsi, volume, average_volume, total_ce_oi, total_pe_oi, pcr, futures_oi, futures_oi_change_pct, rsi_30, rsi_60, macd_day, macd_signal_day, macd_hist_day, rsi_day, macd_45, macd_signal_45, macd_hist_45)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, records)
    
    conn.commit()
    conn.close()
 
def cleanup_old_records(days=30):
    threshold = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM macd_records WHERE timestamp < ?", (threshold,))
    deleted_macd = cursor.rowcount
    
    cursor.execute("DELETE FROM alerts_triggered WHERE timestamp < ?", (threshold,))
    deleted_alerts = cursor.rowcount
    
    cursor.execute("DELETE FROM alert_retrospectives WHERE alert_timestamp < ?", (threshold,))
    deleted_retros = cursor.rowcount
    
    conn.commit()
    conn.close()
    
    total_deleted = deleted_macd + deleted_alerts + deleted_retros
    if total_deleted > 0:
        print(f"  🧹 Housekeeping: Cleaned up {deleted_macd} macd, {deleted_alerts} alerts, {deleted_retros} retros older than {days} days.")
    return total_deleted
 
def get_db_size_mb():
    if os.path.exists(DB_PATH):
        bytes_size = os.path.getsize(DB_PATH)
        return bytes_size / (1024 * 1024)
    return 0.0
 
def insert_alerts(alerts):
    """
    alerts is a list of tuples:
    (timestamp, symbol, price, day_change, alert_type, message, severity, macd_line, signal_line, histogram, macd_change, histogram_change, rsi, volume, average_volume, total_ce_oi, total_pe_oi, pcr, futures_oi, futures_oi_change_pct, rsi_30, rsi_60, macd_day, macd_signal_day, macd_hist_day, rsi_day, macd_45, macd_signal_45, macd_hist_45)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executemany("""
        INSERT INTO alerts_triggered (timestamp, symbol, price, day_change, alert_type, message, severity, macd_line, signal_line, histogram, macd_change, histogram_change, rsi, volume, average_volume, total_ce_oi, total_pe_oi, pcr, futures_oi, futures_oi_change_pct, rsi_30, rsi_60, macd_day, macd_signal_day, macd_hist_day, rsi_day, macd_45, macd_signal_45, macd_hist_45)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, alerts)
    conn.commit()
    conn.close()

def insert_retrospectives(retros):
    """
    retros is a list of tuples:
    (alert_timestamp, symbol, alert_type, signal_price, eod_price, pct_change, status, failure_reason, eval_timestamp)
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executemany("""
        INSERT INTO alert_retrospectives (alert_timestamp, symbol, alert_type, signal_price, eod_price, pct_change, status, failure_reason, eval_timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, retros)
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_db()
    print(f"Current DB Size: {get_db_size_mb():.3f} MB")
