import matplotlib
matplotlib.use('Agg')
import backtrader as bt
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt

# ---------------- Strategy ----------------
class SmaCrossStrategy(bt.Strategy):
    params = dict(
        fast=10,
        slow=30,
        stop_loss_pct=0.02,
        take_profit_pct=0.04
    )

    def __init__(self):
        self.fast_sma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.fast)
        self.slow_sma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.slow)
        self.trade_log = []
        self.equity_curve = []

    def next(self):
        self.equity_curve.append(self.broker.getvalue())
        if not self.position:
            if self.fast_sma[0] > self.slow_sma[0]:
                self.buy()
        else:
            if self.data.close[0] <= self.position.price * (1 - self.p.stop_loss_pct):
                self.close()
            elif self.data.close[0] >= self.position.price * (1 + self.p.take_profit_pct):
                self.close()
            elif self.fast_sma[0] < self.slow_sma[0]:
                self.close()

    def notify_trade(self, trade):
        if trade.isclosed:
            size = trade.size if trade.size != 0 else 1
            exit_price = trade.price + trade.pnl / size
            trade_info = {
                "Entry Date": bt.num2date(trade.dtopen).strftime("%Y-%m-%d %H:%M"),
                "Exit Date": bt.num2date(trade.dtclose).strftime("%Y-%m-%d %H:%M"),
                "Entry Price": trade.price,
                "Exit Price": exit_price,
                "PnL": trade.pnl
            }
            self.trade_log.append(trade_info)

# ---------------- Data Loader ----------------
def get_minute_data(symbol, period='60d', interval='30m'):
    df = yf.download(symbol, interval=interval, period=period, auto_adjust=True, progress=False)

    # 打印列名，确认实际返回
    print("Columns from Yahoo:", df.columns.tolist())

    # 如果是多级索引，取 level=0
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    # 保证列名是字符串
    df.columns = [str(c) for c in df.columns]

    # 检查是否有必须列
    required_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    for col in required_cols:
        if col not in df.columns:
            raise ValueError(f"Yahoo data is missing column: {col}")

    # 重命名列为 Backtrader 标准
    df = df.rename(columns={
        'Open': 'open',
        'High': 'high',
        'Low': 'low',
        'Close': 'close',
        'Volume': 'volume'
    })

    # 补充 openinterest
    df['openinterest'] = 0

    # 保留顺序
    df = df[['open', 'high', 'low', 'close', 'volume', 'openinterest']]
    df.index = pd.to_datetime(df.index)
    return df

# ---------------- HTML Export ----------------
def save_html_from_csv(csv_file, html_file, equity_curve_img=None):
    df = pd.read_csv(csv_file)
    img_html = f'<img src="{equity_curve_img}" width="600">' if equity_curve_img else ""
    html = f"""
    <html>
    <body>
    <h1>Backtest Report</h1>
    {img_html}
    {df.to_html(index=False)}
    </body>
    </html>
    """
    with open(html_file, "w", encoding="utf-8") as f:
        f.write(html)

# ---------------- Main ----------------
if __name__ == "__main__":
    symbol = "AAPL"
    df = get_minute_data(symbol, period='60d', interval='30m')

    data_feed = bt.feeds.PandasData(
        dataname=df,
        timeframe=bt.TimeFrame.Minutes,
        compression=30
    )

    cerebro = bt.Cerebro()
    cerebro.adddata(data_feed)
    cerebro.addstrategy(SmaCrossStrategy)

    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)

    strategies = cerebro.run()
    strategy = strategies[0]

    trades_df = pd.DataFrame(strategy.trade_log)
    trades_df.to_csv("trades.csv", index=False)

    plt.figure(figsize=(12, 6))
    plt.plot(strategy.equity_curve)
    plt.title("Equity Curve")
    plt.xlabel("Bars (30-min intervals)")
    plt.ylabel("Portfolio Value ($)")
    plt.tight_layout()
    plt.savefig("equity_curve.png")
    plt.close()

    save_html_from_csv("trades.csv", "backtest_report.html", "equity_curve.png")

    print("Backtest completed!")
