import pandas as pd
import re
from io import StringIO

def parse_text_signals(text: str) -> pd.DataFrame:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    rows = []
    pattern = re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\d{2}:\d{2})\s+(buy|sell)\s+([\d.,]+)(?:\s+([\d.,]+))?", re.IGNORECASE)
    for ln in lines:
        m = pattern.search(ln.replace(",", "."))
        if not m:
            continue
        date, tm, op, pct, price = m.groups()
        rows.append({
            "time": f"{date} {tm}",
            "operation": op.lower(),
            "pct": float(pct),
            "price": float(price) if price else None
        })
    return pd.DataFrame(rows)

def parse_file_signals(path: str) -> pd.DataFrame:
    if path.endswith(".csv"):
        return pd.read_csv(path)
    return pd.read_excel(path)

def build_curve_from_signals(df_sig: pd.DataFrame, start_price: float = 0.01,
                             step_pct: float = 1.0) -> pd.DataFrame:
    df_sig = df_sig.sort_values("time")
    if "price" in df_sig.columns and df_sig["price"].notna().any():
        return df_sig[["time", "price"]]
    price = start_price
    prices = []
    for _, r in df_sig.iterrows():
        if r["operation"] == "buy":
            price *= (1 + step_pct/100)
        else:
            price *= (1 - step_pct/100)
        prices.append(price)
    out = pd.DataFrame({"time": pd.to_datetime(df_sig["time"]), "price": prices})
    return out
