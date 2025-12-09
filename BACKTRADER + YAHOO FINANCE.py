import matplotlib
matplotlib.use('Agg')  # Headless mode

import backtrader as bt
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt

# ---------------- Strategy ----------------
class SmaCrossStrategy(bt.Strategy):
    params = dict(fast=10, slow=30, stop_loss_pct=0.02, take_profit_pct=0.04)

    def __init__(self):
        self.fast_sma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.fast)
        self.slow_sma = bt.indicators.SimpleMovingAverage(self.data.close, period=self.p.slow)
        self.trade_log = []

    def next(self):
        if not self.position:
            if self.fast_sma[0] > self.slow_sma[0]:
                self.buy()
        else:
            # Stop loss / Take profit
            if self.data.close[0] <= self.position.price * (1 - self.p.stop_loss_pct):
                self.close()
            elif self.data.close[0] >= self.position.price * (1 + self.p.take_profit_pct):
                self.close()
            # SMA crossover exit
            elif self.fast_sma[0] < self.slow_sma[0]:
                self.close()

    def notify_trade(self, trade):
        if trade.isclosed:
            entry_price = trade.price
            exit_price = trade.price + trade.pnl / trade.size if trade.size != 0 else trade.price
            # Use self.data.datetime for correct timestamps
            entry_date = bt.num2date(trade.dtopen).date() if trade.dtopen else ''
            exit_date = bt.num2date(trade.dtclose).date() if trade.dtclose else ''

            trade_info = {
                'Entry Date': entry_date,
                'Exit Date': exit_date,
                'Entry Price': entry_price,
                'Exit Price': exit_price,
                'Size': trade.size,
                'Stop Loss': entry_price * (1 - self.p.stop_loss_pct),
                'Take Profit': entry_price * (1 + self.p.take_profit_pct),
                'PnL': trade.pnl
            }
            self.trade_log.append(trade_info)
            print("Trade closed:", trade_info)

# ---------------- Data ----------------
def get_data(symbol, start, end):
    df = yf.download(symbol, start=start, end=end, auto_adjust=False, progress=False)
    # Ensure single-level columns
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index)
    return df

# ---------------- HTML Report ----------------
def save_html_from_csv(csv_file, html_file, equity_curve_img=None):
    df = pd.read_csv(csv_file)
    equity_img_html = f'<img src="{equity_curve_img}" alt="Equity Curve">' if equity_curve_img else ''
    
    html_str = f'''
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <title>Backtest Report</title>
    <link rel="stylesheet" type="text/css" 
          href="https://cdn.datatables.net/1.13.6/css/jquery.dataTables.css">
    <script src="https://code.jquery.com/jquery-3.6.0.min.js"></script>
    <script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.js"></script>
    </head>
    <body>
    <h2>Backtest Report</h2>
    {equity_img_html}
    {df.to_html(index=False, classes='display', table_id='trade_table')}
    <script>
      $(document).ready(function () {{
          $('#trade_table').DataTable({{ "pageLength": 25 }});
      }});
    </script>
    </body>
    </html>
    '''
    with open(html_file, 'w') as f:
        f.write(html_str)

# ---------------- Main ----------------
if __name__ == "__main__":
    symbol = "AAPL"
    start_date = "2010-01-01"
    end_date = "2024-01-01"

    df = get_data(symbol, start_date, end_date)
    data_feed = bt.feeds.PandasData(dataname=df)  # pass dataframe, not tuple

    cerebro = bt.Cerebro()
    cerebro.adddata(data_feed)
    cerebro.addstrategy(SmaCrossStrategy)

    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)

    print("Starting Portfolio Value:", cerebro.broker.getvalue())
    results = cerebro.run()
    strategy_instance = results[0]
    print("Final Portfolio Value:", cerebro.broker.getvalue())

    # ---------------- Save Trades ----------------
    trades_df = pd.DataFrame(strategy_instance.trade_log)
    trades_csv = 'trades.csv'
    trades_df.to_csv(trades_csv, index=False)
    print(f"Trades saved to {trades_csv}")

    # ---------------- Equity Curve ----------------
    plt.figure(figsize=(10,6))
    plt.plot(df.index, [cerebro.broker.startingcash]*len(df), label='Portfolio Value')  # simple curve
    equity_curve_img = 'equity_curve.png'
    plt.savefig(equity_curve_img)

    # ---------------- Convert CSV → Interactive HTML ----------------
    trades_html = 'backtest_report.html'
    save_html_from_csv(trades_csv, trades_html, equity_curve_img)
    print(f"HTML report saved to {trades_html}")
