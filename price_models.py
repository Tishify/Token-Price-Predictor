import numpy as np
import pandas as pd
from datetime import datetime

def random_walk(start_price: float,
                start_time: datetime,
                end_time: datetime,
                points: int,
                vol_pct: float = 2.0) -> pd.DataFrame:
    times = pd.date_range(start=start_time, end=end_time, periods=points)
    prices = [start_price]
    for _ in range(points-1):
        step = np.random.uniform(-vol_pct, vol_pct)/100
        prices.append(max(0.0000001, prices[-1]*(1+step)))
    return pd.DataFrame({"time": times, "price": np.round(prices, 6)})