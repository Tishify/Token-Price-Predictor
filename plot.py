import plotly.graph_objects as go
import plotly.io as pio

# Configure Kaleido for image generation
pio.kaleido.scope.default_format = 'png'
pio.kaleido.scope.default_width = 800
pio.kaleido.scope.default_height = 600


def create_line_figure(df):
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df['time'], y=df['price'], mode='lines+markers', name='Price'
    ))
    fig.update_layout(
        title='Price Chart',
        xaxis=dict(rangeslider_visible=True),
        yaxis=dict(title='Price ($)'),
        showlegend=False
    )
    return fig


def create_candlestick_figure(candles):
    df = candles.copy()
    fig = go.Figure([
        go.Candlestick(
            x=df['time'], open=df['open'], high=df['high'],
            low=df['low'], close=df['close'],
            increasing_line_color='green', decreasing_line_color='red',
            name='Price'
        ),
        go.Bar(
            x=df['time'], y=df['volume'], name='Volume',
            yaxis='y2', marker_color='grey'
        )
    ])
    annotations = [
        dict(
            x=row['time'], y=row['high'] * 1.01,
            text=str(int(row['wallet_count'])),
            showarrow=False, font=dict(size=8)
        ) for _, row in df.iterrows()
    ]
    fig.update_layout(
        title='Candlestick Chart',
        xaxis=dict(rangeslider_visible=False),
        yaxis=dict(title='Price ($)'),
        yaxis2=dict(
            title='Volume ($)', overlaying='y', side='right',
            showgrid=False, position=0.15
        ),
        annotations=annotations,
        legend=dict(orientation='h', y=1.02)
    )
    return fig


def fig_to_html_bytes(fig) -> bytes:
    return fig.to_html(full_html=True, include_plotlyjs='cdn').encode('utf-8')


def fig_to_pdf_bytes(fig) -> bytes:
    return fig.to_image(format='pdf')