// src/App.js
import React, { useEffect, useState } from "react";
import Papa from "papaparse";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
  ResponsiveContainer,
} from "recharts";

const CSV_URL = "/trades.csv";

export default function App() {
  const [trades, setTrades] = useState([]);
  const [equity, setEquity] = useState([]);

  // Load CSV
  useEffect(() => {
    fetch(CSV_URL)
      .then((res) => res.text())
      .then((text) => {
        const parsed = Papa.parse(text, { header: true, skipEmptyLines: true });

        const rows = parsed.data.map((r) => ({
          entryDate: r["Entry Date"],
          exitDate: r["Exit Date"],
          entryPrice: Number(r["Entry Price"]),
          exitPrice: Number(r["Exit Price"]),
          pnl: Number(r["PnL"]),
        }));

        setTrades(rows);

        // ---- Create equity curve ----
        let cumulative = 0;
        const equityRows = rows.map((t) => {
          cumulative += t.pnl;
          return {
            date: t.entryDate,
            pnl: t.pnl,
            equity: Number(cumulative.toFixed(6)),
          };
        });

        setEquity(equityRows);
      });
  }, []);

  if (!equity.length) return <div style={{ padding: 20 }}>Loading data…</div>;

  // Summary
  const totalPnL = equity[equity.length - 1].equity.toFixed(4);
  const winRate =
    ((trades.filter((t) => t.pnl > 0).length / trades.length) * 100).toFixed(2);

  return (
    <div style={{ padding: 20, fontFamily: "Arial" }}>
      <h2>Equity Curve (资金曲线)</h2>

      <div style={{ marginBottom: 20 }}>
        <strong>Total Trades:</strong> {trades.length} <br />
        <strong>Win Rate:</strong> {winRate}% <br />
        <strong>Total PnL:</strong> {totalPnL}
      </div>

      {/* ---- Equity Curve Chart ---- */}
      <div style={{ width: "100%", height: 400 }}>
        <ResponsiveContainer>
          <LineChart data={equity}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis dataKey="date" />
            <YAxis />
            <Tooltip />
            <Line
              type="monotone"
              dataKey="equity"
              stroke="#007bff"
              strokeWidth={2}
              dot={false}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* ---- Table ---- */}
      <h3 style={{ marginTop: 30 }}>Trade List</h3>
      <table
        border="1"
        cellPadding="8"
        style={{ borderCollapse: "collapse", width: "100%" }}
      >
        <thead>
          <tr>
            <th>Entry Date</th>
            <th>Exit Date</th>
            <th>Entry Price</th>
            <th>Exit Price</th>
            <th>PnL</th>
          </tr>
        </thead>
        <tbody>
          {trades.map((t, i) => (
            <tr key={i}>
              <td>{t.entryDate}</td>
              <td>{t.exitDate}</td>
              <td>{t.entryPrice.toFixed(4)}</td>
              <td>{t.exitPrice.toFixed(4)}</td>
              <td style={{ color: t.pnl >= 0 ? "green" : "red" }}>
                {t.pnl.toFixed(4)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
