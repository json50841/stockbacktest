# =========================================================
# Imports
# =========================================================
import matplotlib
matplotlib.use("Agg")

import backtrader as bt
import yfinance as yf
import pandas as pd
import matplotlib.pyplot as plt


# =========================================================
# Strategy
# =========================================================
class SmaCrossStrategy(bt.Strategy):
    params = dict(
        fast=5,
        slow=15,

        initial_shares=100,          # 初始股票股数
        max_capital_usage_pct=0.9,  # 单笔最大资金使用比例

        stop_loss_points=2.5,       # 固定止损点（美元）
        take_profit_points=2.5,     # 固定止盈点（美元）

        recovery_mult=2             # Recovery 翻倍系数
    )

    def __init__(self):
        self.fast_sma = bt.indicators.SMA(self.data.close, period=self.p.fast)
        self.slow_sma = bt.indicators.SMA(self.data.close, period=self.p.slow)

        self.in_recovery = False
        self.recovery_shares = self.p.initial_shares
        self.last_trade_direction = None

        self.trade_log = []
        self.equity_curve = []

        self._prev_pos = 0
        self._entry = None


    # ------------------------------
    # 资金检查
    # ------------------------------
    def check_capital(self, shares):
        price = self.data.close[0]
        return abs(price * shares) <= self.broker.getvalue() * self.p.max_capital_usage_pct


    # ------------------------------
    # 主逻辑
    # ------------------------------
    def next(self):
        self.equity_curve.append(self.broker.getvalue())

        # ===== 无持仓：准备开仓 =====
        if not self.position:

            # ---------- 正常模式（均线策略） ----------
            if not self.in_recovery:
                shares = self.p.initial_shares
                if not self.check_capital(shares):
                    return

                if self.fast_sma[0] > self.slow_sma[0]:
                    self.last_trade_direction = "LONG"
                    self.buy(size=shares)

                elif self.fast_sma[0] < self.slow_sma[0]:
                    self.last_trade_direction = "SHORT"
                    self.sell(size=shares)

            # ---------- Recovery 模式（仅在亏损后） ----------
            else:
                shares = self.recovery_shares
                if not self.check_capital(shares):
                    return

                # 严格反方向
                if self.last_trade_direction == "LONG":
                    self.last_trade_direction = "SHORT"
                    self.sell(size=shares)
                else:
                    self.last_trade_direction = "LONG"
                    self.buy(size=shares)

        # ===== 有持仓：止盈止损 =====
        else:
            entry = self.position.price
            price = self.data.close[0]

            if self.position.size > 0:
                if price <= entry - self.p.stop_loss_points:
                    self.close()
                elif price >= entry + self.p.take_profit_points:
                    self.close()
            else:
                if price >= entry + self.p.stop_loss_points:
                    self.close()
                elif price <= entry - self.p.take_profit_points:
                    self.close()


    # ------------------------------
    # 成交回调（CSV 唯一来源）
    # ------------------------------
    def notify_order(self, order):
        if order.status in [order.Submitted, order.Accepted]:
            return

        if order.status == order.Completed:
            new_pos = self.position.size
            prev_pos = self._prev_pos

            price = order.executed.price
            dt = bt.num2date(order.executed.dt).strftime("%Y-%m-%d %H:%M")

            # ===== 开仓 =====
            if prev_pos == 0 and new_pos != 0:
                self._entry = {
                    "Entry Date": dt,
                    "Direction": "LONG" if new_pos > 0 else "SHORT",
                    "Shares": abs(new_pos),
                    "Entry Price": price
                }

            # ===== 平仓 =====
            elif prev_pos != 0 and new_pos == 0 and self._entry:
                qty = self._entry["Shares"]

                if self._entry["Direction"] == "LONG":
                    pnl = (price - self._entry["Entry Price"]) * qty
                else:
                    pnl = (self._entry["Entry Price"] - price) * qty

                # -------- Recovery 状态管理（关键修正点） --------
                if pnl < 0:
                    # 亏损 → 进入 Recovery
                    self.in_recovery = True
                    self.recovery_shares *= self.p.recovery_mult
                else:
                    # 盈利 → 完全回到均线策略
                    self.in_recovery = False
                    self.recovery_shares = self.p.initial_shares
                    self.last_trade_direction = None  # ⭐ 强制清空方向记忆

                self.trade_log.append({
                    "Entry Date": self._entry["Entry Date"],
                    "Exit Date": dt,
                    "Direction": self._entry["Direction"],
                    "Shares": qty,
                    "Entry Price": self._entry["Entry Price"],
                    "Exit Price": price,
                    "PnL ($)": pnl
                })

                self._entry = None

            self._prev_pos = new_pos


# =========================================================
# Data
# =========================================================
def get_minute_data(symbol):
    df = yf.download(symbol, period="60d", interval="30m",
                     auto_adjust=True, progress=False)

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.rename(columns={
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume"
    })

    df["openinterest"] = 0
    return df[["open", "high", "low", "close", "volume", "openinterest"]]


# =========================================================
# Main
# =========================================================
if __name__ == "__main__":
    data = bt.feeds.PandasData(
        dataname=get_minute_data("TSLL"),
        timeframe=bt.TimeFrame.Minutes,
        compression=30
    )

    cerebro = bt.Cerebro()
    cerebro.adddata(data)
    cerebro.addstrategy(SmaCrossStrategy)

    cerebro.broker.setcash(100000)
    cerebro.broker.setcommission(commission=0.001)

    strat = cerebro.run()[0]

    pd.DataFrame(strat.trade_log).to_csv("trades.csv", index=False)

    plt.plot(strat.equity_curve)
    plt.title("Equity Curve")
    plt.savefig("equity_curve.png")
