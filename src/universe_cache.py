"""Broad US equity universe discovery and resumable monthly-price caching."""
from __future__ import annotations

import io
from pathlib import Path
import shutil
import time

import pandas as pd
import requests
import yfinance as yf


NASDAQ_FILES = (
    "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
)


def clear_cache(cache_dir: Path) -> None:
    """Remove only this application's known cache directory."""
    if cache_dir.exists():
        shutil.rmtree(cache_dir)


def _normalise_yahoo_symbol(symbol: object) -> str:
    if pd.isna(symbol):
        return ""
    return str(symbol).strip().replace(".", "-").replace("$", "-")


def fetch_us_universe(session: requests.Session | None = None) -> pd.DataFrame:
    """Fetch ordinary Nasdaq/NYSE/NYSE American listings from Nasdaq Trader."""
    session = session or requests.Session()
    frames = []
    for url in NASDAQ_FILES:
        response = session.get(url, timeout=45)
        response.raise_for_status()
        table = pd.read_csv(io.StringIO(response.text), sep="|")
        table = table[~table.iloc[:, 0].astype(str).str.startswith("File Creation Time")]
        if "Symbol" in table:
            selected = table.loc[
                (table["Test Issue"] == "N")
                & (table["ETF"] == "N")
                & (table.get("NextShares", "N") == "N"),
                ["Symbol", "Security Name"],
            ].rename(columns={"Symbol": "ticker", "Security Name": "name"})
        else:
            selected = table.loc[
                (table["Test Issue"] == "N") & (table["ETF"] == "N"),
                ["ACT Symbol", "Security Name"],
            ].rename(columns={"ACT Symbol": "ticker", "Security Name": "name"})
        # Nasdaq's files also contain preferred shares, warrants, rights, units,
        # and debt. Keep operating-company common/ordinary equity (including
        # ADRs and dot-suffixed share classes) for an interpretable stock screen.
        excluded_security_types = (
            r"Warrant|Right(?:s)?(?: |$)|Unit(?:s)?(?: |$)|Preferred|Preference|"
            r"Depositary Shares|Notes? due|Debenture|Bond|Trust Certificate"
        )
        selected = selected.loc[
            ~selected["name"].astype(str).str.contains(excluded_security_types, case=False, regex=True, na=False)
            & ~selected["ticker"].astype(str).str.contains(r"[\^$]", regex=True, na=False)
            & ~selected["ticker"].astype(str).str.endswith((".R", ".U", ".W"), na=False)
        ]
        frames.append(selected)
    universe = pd.concat(frames, ignore_index=True)
    universe["ticker"] = universe["ticker"].astype(str).map(_normalise_yahoo_symbol)
    universe = universe[universe["ticker"].str.fullmatch(r"[A-Z0-9-]+", na=False)]
    universe["country"] = "United States"
    universe["category"] = "Broad US equity universe"
    return universe.drop_duplicates("ticker").sort_values("ticker").reset_index(drop=True)


def load_or_update_universe(
    cache_dir: Path,
    mode: str,
    supplemental: pd.DataFrame,
) -> pd.DataFrame:
    path = cache_dir / "universe.csv"
    if mode in {"auto", "local-only"} and path.exists():
        return pd.read_csv(path)
    if mode == "local-only":
        raise FileNotFoundError(f"No cached universe at {path}; run with --data-mode update first")
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        universe = fetch_us_universe()
    except Exception:
        if not path.exists():
            raise
        print("Warning: universe refresh failed; retaining cached universe")
        universe = pd.read_csv(path)
    universe = pd.concat([universe, supplemental], ignore_index=True)
    universe = universe.drop_duplicates("ticker", keep="last").sort_values("ticker")
    universe.to_csv(path, index=False)
    return universe


def _extract_adjusted_close(raw: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    if raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        fields = raw.columns.get_level_values(0)
        field = "Adj Close" if "Adj Close" in fields else "Close"
        result = raw[field].copy()
        if isinstance(result, pd.Series):
            result = result.to_frame(symbols[0])
    else:
        field = "Adj Close" if "Adj Close" in raw else "Close"
        result = raw[[field]].rename(columns={field: symbols[0]})
    result.index = pd.to_datetime(result.index).tz_localize(None).to_period("M").to_timestamp()
    return result.groupby(level=0).last().dropna(how="all")


def _download_batch(symbols: list[str], start: str) -> pd.DataFrame:
    for attempt in range(3):
        try:
            raw = yf.download(
                symbols, start=start, interval="1mo", auto_adjust=False,
                actions=False, progress=False, threads=True, timeout=30,
            )
            return _extract_adjusted_close(raw, symbols)
        except Exception as exc:
            if attempt == 2:
                print(f"Warning: batch failed after 3 attempts ({symbols[0]}...): {exc}")
            else:
                time.sleep(2 ** attempt)
    return pd.DataFrame()


def _merge_prices(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    combined = old.combine_first(new)
    combined.update(new)
    return combined.sort_index().sort_index(axis=1)


def load_or_update_prices(
    cache_dir: Path,
    universe: pd.DataFrame,
    mode: str,
    start: str = "2011-01-01",
    batch_size: int = 100,
) -> pd.DataFrame:
    """Load cached monthly prices, optionally refreshing them in resumable batches."""
    path = cache_dir / "monthly_adjusted_prices.csv.gz"
    cached = pd.read_csv(path, index_col=0, parse_dates=True) if path.exists() else pd.DataFrame()
    symbols = universe["ticker"].tolist()
    cached = cached[[symbol for symbol in symbols if symbol in cached.columns]]
    if mode in {"auto", "local-only"} and not cached.empty:
        return cached
    if mode == "local-only":
        raise FileNotFoundError(f"No cached prices at {path}; run with --data-mode update first")

    cache_dir.mkdir(parents=True, exist_ok=True)
    existing = [symbol for symbol in symbols if symbol in cached and cached[symbol].notna().any()]
    new_symbols = [symbol for symbol in symbols if symbol not in existing]

    jobs: list[tuple[list[str], str]] = []
    for offset in range(0, len(new_symbols), batch_size):
        jobs.append((new_symbols[offset:offset + batch_size], start))
    if existing:
        last_date = cached.index.max() if not cached.empty else pd.Timestamp(start)
        refresh_start = (last_date - pd.DateOffset(months=2)).date().isoformat()
        for offset in range(0, len(existing), batch_size):
            jobs.append((existing[offset:offset + batch_size], refresh_start))

    print(f"Updating {len(symbols):,} symbols in {len(jobs):,} batches; {len(new_symbols):,} need full history")
    for number, (batch, batch_start) in enumerate(jobs, 1):
        downloaded = _download_batch(batch, batch_start)
        if not downloaded.empty:
            cached = _merge_prices(cached, downloaded)
        if number % 10 == 0 or number == len(jobs):
            cached.to_csv(path, compression="gzip", float_format="%.8g")
            print(f"  checkpoint {number:,}/{len(jobs):,}: {cached.shape[1]:,} symbols cached")
    if cached.empty:
        raise RuntimeError("No prices could be downloaded")
    return cached
