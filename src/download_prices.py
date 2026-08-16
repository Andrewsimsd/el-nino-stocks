from pathlib import Path
import yfinance as yf

PROJECT_ROOT = Path(__file__).resolve().parent.parent

TICKERS = ["CANE"]          # Later: ["CANE", "AAPL", "SPY"]
START = "2011-01-01"
END = None                  # None means through the latest available date
INTERVAL = "1d"

output_dir = PROJECT_ROOT / "artifacts" / "stock_data"
output_dir.mkdir(parents=True, exist_ok=True)

for ticker in TICKERS:
    data = yf.download(
        ticker,
        start=START,
        end=END,
        interval=INTERVAL,
        auto_adjust=False,  # Retain raw OHLC plus adjusted close
        actions=True,       # Include dividends and splits
        progress=False,
    )

    if data.empty:
        print(f"No data returned for {ticker}")
        continue

    filename = output_dir / f"{ticker}_{INTERVAL}.csv"
    data.to_csv(filename)
    print(f"Saved {len(data):,} rows to {filename}")
