#!/usr/bin/env python3
"""
Fetch CANE historical prices and NOAA RONI (El Niño) data,
then produce an interactive Plotly HTML with El Niño periods shaded.

Usage:
    pip install -r requirements.txt
    python plot_cane_el_nino.py

Output: `artifacts/cane_el_nino.html` in the project directory.
"""
from __future__ import annotations

import datetime
import io
from pathlib import Path
import re
import sys

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from scipy.stats import t as student_t
import yfinance as yf


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = PROJECT_ROOT / "artifacts" / "cane_el_nino.html"


TICKERS = {
    "CANE": "Teucrium Sugar Fund",
    "DBA": "Invesco DB Agriculture Fund",
    "CORN": "Teucrium Corn Fund",
    "WEAT": "Teucrium Wheat Fund",
    "SOYB": "Teucrium Soybean Fund",
    "KDP": "Keurig Dr Pepper",
    "ADM": "Archer-Daniels-Midland",
    "BG": "Bunge Global",
    "MOS": "Mosaic",
    "NTR": "Nutrien",
    "CF": "CF Industries",
    "FMC": "FMC Corp.",
    "CTVA": "Corteva",
    "TSN": "Tyson Foods",
    "DE": "Deere & Co.",
    "SBUX": "Starbucks",
    "HSY": "Hershey",
    "GIS": "General Mills",
    "CAG": "Conagra Brands",
    "FCX": "Freeport-McMoRan",
    "SCCO": "Southern Copper",
    "ELPC": "Copel",
    "SBS": "Sabesp",
    "MATX": "Matson",
    "CB": "Chubb",
}

CATEGORIES = {
    "CANE": "Sugar", "DBA": "Broad agriculture", "CORN": "Corn",
    "WEAT": "Wheat", "SOYB": "Soybeans", "KDP": "Coffee & beverages",
    "ADM": "Crop processing", "BG": "Crop processing",
    "MOS": "Fertilizer", "NTR": "Fertilizer", "CF": "Fertilizer",
    "FMC": "Crop protection", "CTVA": "Seeds & crop protection",
    "TSN": "Animal protein", "DE": "Farm equipment",
    "SBUX": "Coffee buyer", "HSY": "Cocoa buyer",
    "GIS": "Packaged food", "CAG": "Packaged food",
    "FCX": "Copper mining", "SCCO": "Copper mining",
    "ELPC": "Hydroelectric utility", "SBS": "Water utility",
    "MATX": "Ocean transport", "CB": "Property insurance",
}


def fetch_prices(tickers: tuple[str, ...] = tuple(TICKERS), start: str = "2011-01-01") -> pd.DataFrame:
    end = datetime.date.today().isoformat()
    print(f"Downloading {', '.join(tickers)} prices {start} to {end}...")
    raw = yf.download(list(tickers), start=start, end=end, auto_adjust=False, progress=False)
    if raw.empty:
        raise RuntimeError("No price data downloaded. Check ticker or network.")
    field = "Adj Close" if "Adj Close" in raw.columns.get_level_values(0) else "Close"
    prices = raw[field] if isinstance(raw.columns, pd.MultiIndex) else raw[[field]].rename(columns={field: tickers[0]})
    prices = prices.dropna(how="all").reset_index()
    available = [ticker for ticker in tickers if ticker in prices.columns and prices[ticker].notna().any()]
    if "CANE" not in available:
        raise RuntimeError("CANE price data was not returned.")
    missing = sorted(set(tickers) - set(available))
    if missing:
        print(f"Warning: no usable data for {', '.join(missing)}")
    return prices[["Date", *available]]


SEASON_CENTER_MONTH = {
    "DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6,
    "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12,
}


def parse_enso_index(text: str) -> pd.DataFrame:
    """Parse a NOAA seasonal ASCII or HTML index table."""
    if "<table" in text.lower():
        for table in pd.read_html(io.StringIO(text)):
            if table.shape[1] != 13:
                continue
            table.columns = ["year", *SEASON_CENTER_MONTH]
            table["year"] = pd.to_numeric(table["year"], errors="coerce")
            table = table.dropna(subset=["year"])
            if not table.empty:
                records = [
                    {"date": pd.Timestamp(int(row.year), month, 1), "oni": float(getattr(row, season))}
                    for row in table.itertuples(index=False)
                    for month, season in enumerate(SEASON_CENTER_MONTH, 1)
                    if pd.notna(getattr(row, season))
                ]
                return (
                    pd.DataFrame.from_records(records)
                    .drop_duplicates("date", keep="last")
                    .set_index("date")
                    .sort_index()
                )

    records: list[dict[str, object]] = []
    for line in text.splitlines():
        fields = line.split()
        if not fields:
            continue

        # Current CPC/PSL ASCII format: ``SEAS YR TOTAL ANOM``.
        if fields[0].upper() in SEASON_CENTER_MONTH and len(fields) >= 3:
            try:
                year = int(fields[1])
                anomaly = float(fields[-1])
            except ValueError:
                continue
            records.append({
                "date": pd.Timestamp(year, SEASON_CENTER_MONTH[fields[0].upper()], 1),
                "oni": anomaly,
            })
            continue

        # CPC's HTML table: year followed by DJF ... NDJ values.
        if re.fullmatch(r"\d{4}", fields[0]) and len(fields) >= 13:
            try:
                values = [float(value) for value in fields[1:13]]
            except ValueError:
                continue
            year = int(fields[0])
            records.extend(
                {"date": pd.Timestamp(year, month, 1), "oni": value}
                for month, value in enumerate(values, 1)
            )

    if not records:
        raise ValueError("Response did not contain a recognized NOAA ENSO index table")
    return (
        pd.DataFrame.from_records(records)
        .drop_duplicates("date", keep="last")
        .set_index("date")
        .sort_index()
    )


def fetch_roni() -> pd.DataFrame:
    """Fetch NOAA's official Relative Oceanic Niño Index (RONI).

    RONI replaced ONI for official ENSO monitoring in 2026. Unlike raw ONI, it
    removes the tropical-mean warming signal that can create false warm episodes.
    """
    candidate_urls = [
        "https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/",
    ]
    for url in candidate_urls:
        try:
            print(f"Trying RONI source: {url}")
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            text = r.text
        except Exception as exc:
            print(f"  Failed to fetch {url}: {exc}")
            continue

        try:
            df = parse_enso_index(text)
        except ValueError as exc:
            print(f"  Could not parse {url}: {exc}")
            continue
        else:
            print(f"Parsed RONI from {url}, {len(df)} records")
            return df

    raise RuntimeError("Could not fetch RONI data from NOAA.")


def get_el_nino_periods(
    oni_df: pd.DataFrame, threshold: float = 0.5, minimum_seasons: int = 5
) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """Return warm episodes meeting NOAA's five-overlapping-season definition."""
    mask = oni_df["oni"] >= threshold
    if mask.sum() == 0:
        return []
    mask_int = mask.astype(int)
    shifted = mask_int.shift(1, fill_value=0)
    starts = mask_int[(mask_int == 1) & (shifted == 0)].index
    ends = mask_int[(mask_int == 1) & (mask_int.shift(-1, fill_value=0) == 0)].index
    return [
        (start - pd.DateOffset(months=1), end + pd.offsets.MonthEnd(2))
        for start, end in zip(starts, ends)
        if len(oni_df.loc[start:end]) >= minimum_seasons
    ]


def calculate_correlations(prices_df: pd.DataFrame, roni_df: pd.DataFrame) -> pd.DataFrame:
    """Pearson r with autocorrelation-adjusted p-values and BH-FDR q-values."""
    prices = prices_df.set_index("Date").sort_index()
    monthly_returns = prices.resample("MS").last().pct_change(fill_method=None)
    aligned = monthly_returns.join(roni_df[["oni"]].rename(columns={"oni": "roni"}), how="inner")
    records = []
    for ticker in prices.columns:
        pair = aligned[[ticker, "roni"]].dropna()
        correlation = pair[ticker].corr(pair["roni"])
        # RONI is serially correlated. Adjust the nominal sample size using the
        # standard lag-1 effective-sample-size approximation before the t test.
        asset_ar1 = pair[ticker].autocorr(lag=1)
        roni_ar1 = pair["roni"].autocorr(lag=1)
        denominator = 1 + asset_ar1 * roni_ar1
        effective_n = len(pair) * (1 - asset_ar1 * roni_ar1) / denominator if denominator > 0 else len(pair)
        effective_n = max(3.0, min(float(len(pair)), effective_n))
        t_statistic = correlation * ((effective_n - 2) / max(1e-15, 1 - correlation ** 2)) ** 0.5
        p_value = 2 * student_t.sf(abs(t_statistic), df=effective_n - 2)
        records.append({
            "ticker": ticker,
            "category": CATEGORIES.get(ticker, "Other"),
            "correlation": correlation,
            "observations": len(pair),
            "effective_observations": effective_n,
            "p_value": p_value,
        })
    result = pd.DataFrame(records)
    valid = result["correlation"].notna() & (result["observations"] >= 24)
    rejected = result.loc[~valid, "ticker"].tolist()
    if rejected:
        print(f"Warning: insufficient correlation history for {', '.join(rejected)}")
    result = result.loc[valid].copy()

    # Benjamini-Hochberg correction controls the false-discovery rate across
    # the full stock screen. The reverse cumulative minimum enforces monotonic q.
    ordered = result["p_value"].sort_values()
    adjusted = ordered * len(ordered) / pd.Series(range(1, len(ordered) + 1), index=ordered.index)
    result["q_value"] = adjusted.iloc[::-1].cummin().iloc[::-1].clip(upper=1)
    result["significant"] = result["q_value"] < 0.05
    return result.sort_values("correlation")


def make_plot(
    prices_df: pd.DataFrame,
    roni_df: pd.DataFrame,
    periods: list[tuple[pd.Timestamp, pd.Timestamp]],
    out: str | Path = REPORT_PATH,
):
    prices_df = prices_df.copy()
    # Ensure Date column exists
    if "Date" not in prices_df.columns:
        prices_df.index.name = "Date"
        prices_df = prices_df.reset_index()

    prices_df["Date"] = pd.to_datetime(prices_df["Date"])
    prices_df = prices_df.sort_values("Date")
    first_price, last_price = prices_df["Date"].min(), prices_df["Date"].max()
    tickers = [column for column in prices_df.columns if column != "Date"]
    correlations = calculate_correlations(prices_df, roni_df)
    initially_visible = set(
        correlations.assign(abs_correlation=correlations["correlation"].abs())
        .nlargest(7, "abs_correlation")["ticker"]
    ) | {"CANE"}

    fig = make_subplots(
        rows=2, cols=1, row_heights=[0.68, 0.32], vertical_spacing=0.16,
        subplot_titles=("Adjusted prices, rebased to 100", "Correlation: monthly return vs. RONI"),
    )
    palette = ["#176B87", "#2A9D8F", "#6C5CE7", "#E9C46A", "#F4A261", "#D1495B", "#577590"]
    for position, ticker in enumerate(tickers):
        color = palette[position % len(palette)]
        series = prices_df[["Date", ticker]].dropna()
        rebased = series[ticker] / series[ticker].iloc[0] * 100
        fig.add_trace(go.Scatter(
            x=series["Date"], y=rebased, mode="lines",
            name=f"{ticker} — {TICKERS.get(ticker, ticker)}",
            line={"color": color, "width": 2.4 if ticker == "CANE" else 1.5},
            visible=True if ticker in initially_visible else "legendonly",
            hovertemplate=f"{ticker}<br>Date: %{{x|%Y-%m-%d}}<br>Index: %{{y:.1f}}<extra></extra>",
        ), row=1, col=1)

    # Add shaded rectangles for El Niño periods
    visible_periods = [(max(s, first_price), min(e, last_price)) for s, e in periods if e >= first_price and s <= last_price]
    for start, end in visible_periods:
        fig.add_vrect(
            x0=start, x1=end, fillcolor="rgba(230, 92, 63, 0.16)",
            line_width=0, layer="below", row=1, col=1,
        )

    # A legend entry for layout shapes is not supported consistently by older Plotly.js.
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode="markers", name="El Niño episode",
        marker={"symbol": "square", "size": 12, "color": "rgba(230, 92, 63, 0.35)"},
        hoverinfo="skip",
    ), row=1, col=1)

    bar_colors = [
        ("#B42318" if value < 0 else "#087E6A") if significant else "#AAB4BA"
        for value, significant in zip(correlations["correlation"], correlations["significant"])
    ]
    significance_labels = correlations["q_value"].map(
        lambda q: "***" if q < 0.001 else "**" if q < 0.01 else "*" if q < 0.05 else ""
    )
    fig.add_trace(go.Bar(
        x=correlations["correlation"], y=correlations["ticker"], orientation="h",
        name="Pearson correlation", showlegend=False, marker_color=bar_colors,
        customdata=correlations[["observations", "category", "effective_observations", "p_value", "q_value"]],
        hovertemplate=(
            "%{y} — %{customdata[1]}<br>Correlation: %{x:.3f}"
            "<br>Monthly observations: %{customdata[0]}"
            "<br>Effective observations: %{customdata[2]:.1f}"
            "<br>Adjusted t-test p: %{customdata[3]:.4f}"
            "<br>BH-FDR q: %{customdata[4]:.4f}<extra></extra>"
        ),
        text=[f"{value:+.2f}{stars}" for value, stars in zip(correlations["correlation"], significance_labels)],
        textposition="outside", cliponaxis=False,
    ), row=2, col=1)

    fig.update_layout(
        title={"text": "Agriculture & Food Securities During El Niño Episodes", "x": 0.04, "xanchor": "left", "y": 0.985},
        hovermode="x unified",
        template="plotly_white",
        autosize=True,
        margin={"l": 72, "r": 255, "t": 105, "b": 155},
        legend={"orientation": "v", "y": 0.97, "yanchor": "top", "x": 1.01, "xanchor": "left", "font": {"size": 11}},
        font={"family": "Inter, system-ui, -apple-system, sans-serif", "color": "#24313a"},
        paper_bgcolor="#fbfcfd",
        plot_bgcolor="#fbfcfd",
        height=max(1000, 620 + len(tickers) * 24),
    )

    fig.update_xaxes(
        range=[first_price, last_price], rangeslider_visible=True,
        showgrid=False, rangeslider={"thickness": 0.08},
        row=1, col=1,
    )
    fig.update_yaxes(title_text="Rebased adjusted price", gridcolor="#e5eaee", zeroline=False, row=1, col=1)
    correlation_limit = min(1.0, max(0.25, correlations["correlation"].abs().max() * 1.25))
    fig.update_xaxes(title_text="Pearson correlation coefficient", range=[-correlation_limit, correlation_limit], zeroline=True, zerolinecolor="#80909a", row=2, col=1)
    fig.update_yaxes(title_text="Security", row=2, col=1)
    fig.add_annotation(
        text=(
            "<b>How to read this plot:</b> Each bar is <a href='https://en.wikipedia.org/wiki/Pearson_correlation_coefficient'>Pearson's r</a> "
            "between a security's monthly <a href='https://en.wikipedia.org/wiki/Rate_of_return'>adjusted-price return</a> and the "
            "same month's <a href='https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/'>NOAA RONI</a> value. "
            "Bars left of zero indicate a negative relationship; bars right of zero indicate a "
            "positive relationship.<br><span style='color:#B42318'><b>Dark red</b></span> and "
            "<span style='color:#087E6A'><b>dark teal</b></span> bars are statistically significant negative and positive "
            "relationships; <span style='color:#7B878E'><b>gray</b></span> bars are not "
            "<a href='https://en.wikipedia.org/wiki/Statistical_significance'>statistically significant</a>. "
            "Stars show the corrected <a href='https://en.wikipedia.org/wiki/False_discovery_rate'>q-value</a>: "
            "* q&lt;0.05, ** q&lt;0.01, *** q&lt;0.001.<br>The "
            "<a href='https://en.wikipedia.org/wiki/Student%27s_t-test'>two-sided Pearson t test</a> uses an "
            "<a href='https://en.wikipedia.org/wiki/Autoregressive_model'>AR(1)</a>-adjusted "
            "<a href='https://en.wikipedia.org/wiki/Effective_sample_size'>effective sample size</a>, and the "
            "<a href='https://en.wikipedia.org/wiki/Benjamini%E2%80%93Hochberg_procedure'>Benjamini–Hochberg procedure</a> "
            "controls the <a href='https://en.wikipedia.org/wiki/False_discovery_rate'>false-discovery rate</a> across the "
            "25-security screen. <a href='https://en.wikipedia.org/wiki/Correlation_does_not_imply_causation'>Correlation does not establish causation</a>."
        ),
        x=0, y=-0.13, xref="paper", yref="paper", showarrow=False, xanchor="left", align="left",
        font={"size": 12, "color": "#4d5961"},
        bgcolor="rgba(238, 242, 244, 0.85)", bordercolor="#d5dde1", borderwidth=1, borderpad=8,
    )
    print(f"Writing interactive HTML to {out}...")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(
        out, include_plotlyjs="cdn", full_html=True,
        config={"displaylogo": False, "responsive": True, "scrollZoom": True},
        default_width="100%", default_height=f"{max(1000, 620 + len(tickers) * 24)}px",
    )
    print("Done.")


def main():
    try:
        prices = fetch_prices()
    except Exception as e:
        print("Error fetching prices:", e)
        sys.exit(1)

    try:
        oni = fetch_roni()
    except Exception as e:
        print("Error fetching RONI data:", e)
        sys.exit(1)

    periods = get_el_nino_periods(oni, threshold=0.5)
    make_plot(prices, oni, periods)


if __name__ == "__main__":
    main()
