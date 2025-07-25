import pandas as pd
import re

# --- Loading and validation ---

def load_signals(path: str) -> pd.DataFrame:
    if path.lower().endswith(('.xls', '.xlsx')):
        df = pd.read_excel(path)
    else:
        df = pd.read_csv(path)
    df.columns = df.columns.str.strip().str.lower().str.replace(' ', '_')
    df['time'] = pd.to_datetime(df['time'])
    required = {'time','wallet','operation','pct','volume_$','balance_$','price'}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns: {missing}")
    return df

# --- Text parsing fallback ---

def parse_text_signals(text: str) -> pd.DataFrame:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    rows = []
    pattern = re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s+(buy|sell)\s+([\d.,]+)(?:\s+([\d.,]+))?", re.IGNORECASE)
    for ln in lines:
        m = pattern.search(ln.replace(',', '.'))
        if not m:
            continue
        date, tm, op, pct, price = m.groups()
        rows.append({
            'time': f"{date} {tm}",
            'wallet': 'unknown',
            'operation': op.lower(),
            'pct': float(pct),
            'volume_$': None,
            'balance_$': None,
            'price': float(price) if price else None
        })
    return pd.DataFrame(rows)

# --- Resampling into candles ---

def resample_signals_to_candles(df: pd.DataFrame, interval: str) -> pd.DataFrame:
    alias = {'5m':'5T','15m':'15T','30m':'30T','4h':'4H'}[interval]
    df = df.set_index('time')
    ohlc = df['price'].resample(alias).agg(open='first', high='max', low='min', close='last')
    volume = df['volume_$'].resample(alias).sum().rename('volume')
    wallet_count = df['wallet'].resample(alias).nunique().rename('wallet_count')
    candles = pd.concat([ohlc, volume, wallet_count], axis=1)
    candles = candles.dropna(subset=['open']).reset_index()
    return candles