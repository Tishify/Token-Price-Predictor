import plotly.express as px
import pandas as pd
from io import BytesIO
import plotly.io as pio

def fig_to_html_bytes(fig) -> bytes:
    return fig.to_html(full_html=True, include_plotlyjs="cdn").encode("utf-8")

def fig_to_pdf_bytes(fig) -> bytes:
    return fig.to_image(format="pdf")

def price_plot(df: pd.DataFrame):
    df = df.copy()
    df["time"] = pd.to_datetime(df["time"])
    fig = px.line(df, x="time", y="price", title="Price curve", markers=True)
    fig.update_layout(xaxis_title="Time", yaxis_title="Price ($)", dragmode="pan")
    return fig
