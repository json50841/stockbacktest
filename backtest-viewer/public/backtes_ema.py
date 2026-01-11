import pandas as pd
import numpy as np
import json
from datetime import datetime
from dateutil.relativedelta import relativedelta

# =========================================================
# 全局参数
# =========================================================
SYMBOL = "UGL"
CSV_FILE = "UGL_M30_202001101630_202601092300.csv"

START_DATE = "2025-01-01"
END_DATE   = "2026-01-01"

INITIAL_CASH = 100000
INITIAL_SHARES = 100

FAST_EMA = 9
SLOW_EMA = 21

MARTINGALE_MULT = 2
INITIAL_CASH_BASE = 4.5

LOOKBACK_MONTHS = 3
GRID_RANGE = np.arange(1, 10, 0.5)

# =========================================================
# 数据加载
# =========================================================
def load_data(path, start, end):
    df = pd.read_csv(path, sep="\t")
    df["datetime"] = pd.to_datetime(df["<DATE>"] + " " + df["<TIME>"])
    df.set_index("datetime", inplace=True)
    df = df.rename(columns={
        "<OPEN>":"open","<HIGH>":"high",
        "<LOW>":"low","<CLOSE>":"close"
    })
    df = df.loc[start:end]
    df["ema_fast"] = df["close"].ewm(span=FAST_EMA, adjust=False).mean()
    df["ema_slow"] = df["close"].ewm(span=SLOW_EMA, adjust=False).mean()
    return df

# =========================================================
# 单参数完整回测（给 Grid 用，返回净盈亏）
# =========================================================
def run_single_backtest(df, cash_base, initial_cash=INITIAL_CASH):
    cash = initial_cash
    shares = INITIAL_SHARES
    pos = None
    entry_price = None
    martingale_level = 0
    max_shares = 1600  # 最大马丁手数限制

    for _, row in df.iterrows():
        price = row.close

        # === 持仓处理 ===
        if pos:
            pnl = (price - entry_price) * shares if pos == "LONG" else (entry_price - price) * shares
            threshold = cash_base * shares

            if abs(pnl) >= threshold:
                cash += pnl

                if pnl > 0:
                    shares = INITIAL_SHARES
                    martingale_level = 0
                else:
                    shares = min(shares * MARTINGALE_MULT, max_shares)  # 限制最大手数
                    martingale_level += 1

                pos = None
                entry_price = None

        # === 开仓（资金检查） ===
        if not pos:
            required_cash = shares * price
            if cash < required_cash:
                # 资金不足时直接判定为大亏损
                return -1e9

            if row.ema_fast > row.ema_slow:
                pos = "LONG"
                entry_price = price
            elif row.ema_fast < row.ema_slow:
                pos = "SHORT"
                entry_price = price

    # 最终净盈亏
    return cash - initial_cash

# =========================================================
# 回望网格搜索（过去 n 个月）
# =========================================================
def grid_search(df):
    results = []
    for cb in GRID_RANGE:
        pnl = run_single_backtest(df, cb)
        results.append((cb, pnl))

    # 按盈亏排序（从小到大）
    results.sort(key=lambda x: x[1])

    # 取中位及之后
    mid = len(results) // 2
    selected = results[mid:]

    # 在原筛选结果中，选择 cash_base 最大的
    return max(selected, key=lambda x: x[0])[0]


# =========================================================
# 主 Walk-Forward 回测（增加资金校验，不删减功能）
# =========================================================
def main_backtest(df):
    cash = INITIAL_CASH
    shares = INITIAL_SHARES
    pos = None
    entry_price = None
    entry_time = None
    martingale_level = 0

    current_cash_base = INITIAL_CASH_BASE
    trades = []
    equity_curve = []

    last_grid_time = pd.to_datetime(START_DATE)

    for time, row in df.iterrows():
        price = row.close
        equity_curve.append(round(cash, 2))

        # === 是否触发回望参数更新 ===
        if time >= last_grid_time + relativedelta(months=LOOKBACK_MONTHS):
            lookback_start = time - relativedelta(months=LOOKBACK_MONTHS)
            lookback_df = df.loc[lookback_start:time]
            current_cash_base = grid_search(lookback_df)
            last_grid_time = time

        # === 平仓判断 ===
        if pos:
            pnl = (price - entry_price) * shares if pos == "LONG" else (entry_price - price) * shares
            threshold = current_cash_base * shares

            if abs(pnl) >= threshold:
                cash += pnl

                trades.append({
                    "Entry Time": entry_time,
                    "Exit Time": time,
                    "Direction": pos,
                    "Shares": shares,
                    "Martingale Level": martingale_level,
                    "Cash Base": current_cash_base,
                    "Entry Price": round(entry_price, 2),
                    "Exit Price": round(price, 2),
                    "PnL": round(pnl, 2),
                    "Equity": round(cash, 2)
                })

                # === 马丁恢复 / 翻倍 ===
                if pnl > 0:
                    shares = INITIAL_SHARES
                    martingale_level = 0
                else:
                    shares *= MARTINGALE_MULT
                    martingale_level += 1

                pos = None
                entry_price = None
                entry_time = None

        # === 开仓（增加资金是否足够判断） ===
        if not pos:
            required_cash = shares * price  # 保守保证金假设

            # === 多头 ===
            if row.ema_fast > row.ema_slow:
                if cash >= required_cash:
                    pos = "LONG"
                    entry_price = price
                    entry_time = time
                else:
                    # 资金不足，跳过本次信号
                    pass

            # === 空头 ===
            elif row.ema_fast < row.ema_slow:
                if cash >= required_cash:
                    pos = "SHORT"
                    entry_price = price
                    entry_time = time
                else:
                    # 资金不足，跳过本次信号
                    pass

    return trades, equity_curve

# =========================================================
# HTML 报告（美化版，不删减功能）
# =========================================================
def generate_html(trades, equity):
    import json

    win = sum(1 for t in trades if t["PnL"] > 0)
    total = len(trades)
    total_pnl = round(sum(t["PnL"] for t in trades), 2)
    max_level = max((t["Martingale Level"] for t in trades), default=0)
    win_rate = win / total * 100 if total else 0

    rows = ""
    for i, t in enumerate(trades):
        dcol = "#2ecc71" if t["Direction"] == "LONG" else "#e74c3c"
        pcol = "#2ecc71" if t["PnL"] > 0 else "#e74c3c"
        bg = "#fafafa" if i % 2 == 0 else "#ffffff"

        rows += f"""
<tr style="background:{bg}">
<td>{t['Entry Time']}</td>
<td>{t['Exit Time']}</td>
<td style="color:{dcol};font-weight:bold">{t['Direction']}</td>
<td>{t['Shares']}</td>
<td>{t['Martingale Level']}</td>
<td>{t['Cash Base']}</td>
<td>{t['Entry Price']}</td>
<td>{t['Exit Price']}</td>
<td style="color:{pcol};font-weight:bold">{round(t['PnL'],2)}</td>
<td>{round(t['Equity'],2)}</td>
</tr>
"""

    eq_json = json.dumps(equity)

    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{SYMBOL} Walk-Forward Report</title>

<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

<style>
body {{
    font-family: Arial, sans-serif;
    background:#f4f6f8;
    margin:0;
    padding:30px;
}}

.container {{
    max-width: 1400px;
    margin:auto;
    background:#ffffff;
    padding:30px;
    border-radius:8px;
    box-shadow:0 2px 10px rgba(0,0,0,0.08);
}}

h1 {{
    border-bottom:2px solid #333;
    padding-bottom:10px;
}}

.stats {{
    display:grid;
    grid-template-columns: repeat(auto-fit,minmax(220px,1fr));
    gap:15px;
    margin:20px 0;
}}

.stat-box {{
    background:#f9f9f9;
    padding:15px;
    border-radius:6px;
    border-left:4px solid #3498db;
}}

.stat-box b {{
    display:block;
    margin-bottom:5px;
}}

table {{
    width:100%;
    border-collapse:collapse;
    margin-top:20px;
    font-size:14px;
}}

th, td {{
    border:1px solid #ddd;
    padding:8px;
    text-align:center;
}}

th {{
    background:#f1f1f1;
    position:sticky;
    top:0;
    z-index:10;
}}

tr:hover {{
    background:#ffffe0 !important;
}}

canvas {{
    margin-top:30px;
}}
</style>
</head>

<body>
<div class="container">

<h1>{SYMBOL} EMA Martingale Walk-Forward Report</h1>

<div class="stats">
  <div class="stat-box"><b>Period</b>{START_DATE} → {END_DATE}</div>
  <div class="stat-box"><b>Initial Cash</b>{INITIAL_CASH}</div>
  <div class="stat-box"><b>Initial Shares</b>{INITIAL_SHARES}</div>
  <div class="stat-box"><b>EMA</b>{FAST_EMA} / {SLOW_EMA}</div>
  <div class="stat-box"><b>Martingale Mult</b>{MARTINGALE_MULT}</div>
  <div class="stat-box"><b>Grid Lookback</b>{LOOKBACK_MONTHS} months</div>
  <div class="stat-box"><b>Total Trades</b>{total}</div>
  <div class="stat-box"><b>Win Rate</b>{win_rate:.2f}%</div>
  <div class="stat-box"><b>Total PnL</b>{total_pnl}</div>
  <div class="stat-box"><b>Max Martingale Level</b>{max_level}</div>
</div>

<canvas id="eq"></canvas>

<script>
new Chart(document.getElementById("eq"), {{
    type: "line",
    data: {{
        labels: [...Array({len(equity)}).keys()],
        datasets: [{{
            label: "Equity Curve",
            data: {eq_json},
            borderColor: "#3498db",
            fill: false,
            tension: 0.1
        }}]
    }},
    options: {{
        responsive:true,
        plugins: {{
            legend: {{ display:true }}
        }}
    }}
}});
</script>

<table>
<thead>
<tr>
<th>Entry Time</th>
<th>Exit Time</th>
<th>Direction</th>
<th>Shares</th>
<th>Martingale Level</th>
<th>Cash Base</th>
<th>Entry Price</th>
<th>Exit Price</th>
<th>PnL</th>
<th>Equity</th>
</tr>
</thead>
<tbody>
{rows}
</tbody>
</table>

</div>
</body>
</html>
"""

    with open(f"{SYMBOL}_WalkForward_Report.html", "w", encoding="utf-8") as f:
        f.write(html)

    print(f"HTML report generated: {SYMBOL}_WalkForward_Report.html")

# =========================================================
# 主入口
# =========================================================
def main():
    df = load_data(CSV_FILE, START_DATE, END_DATE)
    trades, equity = main_backtest(df)
    generate_html(trades, equity)
    print("Walk-Forward backtest completed")

if __name__ == "__main__":
    main()
