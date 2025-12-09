// src/App.js
import React, { useEffect, useState, useRef } from "react";
import Papa from "papaparse";
import {
  ChartCanvas,
  Chart,
  CandlestickSeries,
  BarSeries,
  XAxis,
  YAxis,
  MouseCoordinateX,
  MouseCoordinateY,
  OHLCTooltip,
  discontinuousTimeScaleProvider,
  CrossHairCursor,
  ZoomButtons,
} from "react-financial-charts";
import { timeFormat } from "d3-time-format";

// CSV URL (place your CSV in public/backtest_data.csv)
const CSV_URL = "/backtest_data.csv";

// parse CSV -> OHLCV array
const parseCSV = (csvString) => {
  const result = Papa.parse(csvString, { header: true, skipEmptyLines: true });
  const raw = result.data
    .map((d) => {
      const date = d.Date ? new Date(d.Date) : null;
      const open = d.Open ? parseFloat(d.Open) : NaN;
      const high = d.High ? parseFloat(d.High) : NaN;
      const low = d.Low ? parseFloat(d.Low) : NaN;
      const close = d.Close ? parseFloat(d.Close) : NaN;
      const volume = d.Volume ? parseInt(d.Volume, 10) : NaN;
      return { date, open, high, low, close, volume };
    })
    // filter out rows with invalid date or NaN
    .filter((r) => r.date instanceof Date && !Number.isNaN(r.date.getTime()) &&
                    !Number.isNaN(r.open) && !Number.isNaN(r.high) &&
                    !Number.isNaN(r.low) && !Number.isNaN(r.close) &&
                    !Number.isNaN(r.volume));

  // sort ascending by date (required)
  raw.sort((a, b) => a.date - b.date);
  return raw;
};

function App() {
  const [data, setData] = useState([]);
  const wrapperRef = useRef(null);
  const [width, setWidth] = useState(800);

  // responsive width
  useEffect(() => {
    const handleResize = () => {
      if (wrapperRef.current) setWidth(wrapperRef.current.offsetWidth);
    };
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  // load CSV
  useEffect(() => {
    fetch(CSV_URL)
      .then((res) => res.text())
      .then((text) => {
        const parsed = parseCSV(text);
        setData(parsed);
      })
      .catch((err) => {
        console.error("Failed to load CSV:", err);
      });
  }, []);

  if (!data.length) return <div>Loading CSV data...</div>;

  // prepare scale provider
  const xScaleProvider = discontinuousTimeScaleProvider.inputDateAccessor((d) => d.date);
  const { data: chartData, xScale, xAccessor, displayXAccessor } = xScaleProvider(data);

  // initial visible window: show last N bars
  const displayCount = Math.min(150, chartData.length); // show up to last 150 bars
  const startIndex = Math.max(0, chartData.length - displayCount);
  const start = xAccessor(chartData[startIndex]);
  const end = xAccessor(chartData[chartData.length - 1]);
  const xExtents = [start, end];

  // layout
  const height = 600;
  const margin = { left: 50, right: 50, top: 10, bottom: 30 };
  const candleHeight = 420;
  const volumeHeight = 120;

  return (
    <div ref={wrapperRef} style={{ width: "100%" }}>
      <h3 style={{ textAlign: "center" }}>K Line (Candlestick) + Volume — Zoom/Pan/Tooltip</h3>

      <ChartCanvas
        ratio={window.devicePixelRatio}
        width={width}
        height={height}
        margin={margin}
        data={chartData}
        seriesName="Data"
        xScale={xScale}
        xAccessor={xAccessor}
        displayXAccessor={displayXAccessor}
        xExtents={xExtents}           // IMPORTANT: initial visible range
      >
        {/* Main candlestick chart */}
        <Chart id={1} height={candleHeight} yExtents={(d) => [d.high, d.low]}>
          <XAxis />
          <YAxis />

          <CandlestickSeries />

          <MouseCoordinateX
            at="bottom"
            orient="bottom"
            displayFormat={timeFormat("%Y-%m-%d")}
          />
          <MouseCoordinateY at="right" orient="right" displayFormat={(d) => d.toFixed(2)} />

          <OHLCTooltip origin={[0, 0]} />
        </Chart>

        {/* Volume chart below */}
        <Chart
          id={2}
          height={volumeHeight}
          yExtents={(d) => d.volume}
          origin={(w, h) => [0, candleHeight]}
        >
          <XAxis />
          <YAxis tickFormat={(v) => v} />

          <BarSeries
            yAccessor={(d) => d.volume}
            fill={(d) => (d.close > d.open ? "#6BA583" : "#FF0000")}
          />
          <MouseCoordinateX
            at="bottom"
            orient="bottom"
            displayFormat={timeFormat("%Y-%m-%d")}
          />
          <MouseCoordinateY at="right" orient="right" displayFormat={(d) => d} />
        </Chart>

        {/* Zoom buttons & Crosshair Cursor */}
        <ZoomButtons />
        <CrossHairCursor />
      </ChartCanvas>
    </div>
  );
}

export default App;
