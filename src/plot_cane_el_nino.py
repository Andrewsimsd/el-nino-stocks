#!/usr/bin/env python3
"""Run the cached broad-universe ENSO predictive screen and build its report.

Usage:
    pip install -r requirements.txt
    python src/plot_cane_el_nino.py --data-mode local-only

Output: `artifacts/cane_el_nino.html` in the project directory.
"""
from __future__ import annotations

import argparse
import io
from pathlib import Path
import re
import sys

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests

from universe_cache import clear_cache, load_or_update_prices, load_or_update_universe
from predictive_screen import calculate_predictive_screen


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH = PROJECT_ROOT / "artifacts" / "cane_el_nino.html"
RESULTS_PATH = PROJECT_ROOT / "artifacts" / "el_nino_screen.csv.gz"
CACHE_DIR = PROJECT_ROOT / "artifacts" / "cache"


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
    "GNC.AX": "GrainCorp",
    "QBE.AX": "QBE Insurance Group",
    "SMTO3.SA": "Sao Martinho",
    "SUZB3.SA": "Suzano",
    "CPLE3.SA": "Copel",
    "UPL.NS": "UPL",
    "EIDPARRY.NS": "EID Parry",
    "AALI.JK": "Astra Agro Lestari",
    "5285.KL": "SD Guthrie",
    "2802.T": "Ajinomoto",
    "SALM.OL": "SalMar",
    "SQM": "Sociedad Quimica y Minera de Chile",
    "OMN.JO": "Omnia Holdings",
    "GRUMAB.MX": "Gruma",
    "MUV2.DE": "Munich Re",
    "MEL.NZ": "Meridian Energy",
    "TU.BK": "Thai Union Group",
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
    "GNC.AX": "Grain handling & processing", "QBE.AX": "Property insurance",
    "SMTO3.SA": "Sugar & ethanol", "SUZB3.SA": "Pulp & forestry",
    "CPLE3.SA": "Hydroelectric utility", "UPL.NS": "Crop protection",
    "EIDPARRY.NS": "Sugar & farm inputs", "AALI.JK": "Palm oil",
    "5285.KL": "Palm oil", "2802.T": "Food ingredients",
    "SALM.OL": "Salmon aquaculture", "SQM": "Fertilizer & lithium mining",
    "OMN.JO": "Fertilizer & farm inputs", "GRUMAB.MX": "Corn processing",
    "MUV2.DE": "Reinsurance", "MEL.NZ": "Hydroelectric utility",
    "TU.BK": "Seafood processing",
}

COUNTRIES = {
    "CANE": "United States", "DBA": "United States", "CORN": "United States",
    "WEAT": "United States", "SOYB": "United States", "KDP": "United States",
    "ADM": "United States", "BG": "United States", "MOS": "United States",
    "NTR": "Canada", "CF": "United States", "FMC": "United States",
    "CTVA": "United States", "TSN": "United States", "DE": "United States",
    "SBUX": "United States", "HSY": "United States", "GIS": "United States",
    "CAG": "United States", "FCX": "United States", "SCCO": "Peru / Mexico",
    "ELPC": "Brazil", "SBS": "Brazil", "MATX": "United States",
    "CB": "Switzerland", "GNC.AX": "Australia", "QBE.AX": "Australia",
    "SMTO3.SA": "Brazil", "SUZB3.SA": "Brazil", "CPLE3.SA": "Brazil",
    "UPL.NS": "India", "EIDPARRY.NS": "India", "AALI.JK": "Indonesia",
    "5285.KL": "Malaysia", "2802.T": "Japan", "SALM.OL": "Norway",
    "SQM": "Chile", "OMN.JO": "South Africa", "GRUMAB.MX": "Mexico",
    "MUV2.DE": "Germany", "MEL.NZ": "New Zealand", "TU.BK": "Thailand",
}


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


def fetch_roni(mode: str = "update", cache_dir: Path = CACHE_DIR) -> pd.DataFrame:
    """Fetch NOAA's official Relative Oceanic Niño Index (RONI).

    RONI replaced ONI for official ENSO monitoring in 2026. Unlike raw ONI, it
    removes the tropical-mean warming signal that can create false warm episodes.
    """
    cache_path = cache_dir / "roni.csv"
    if mode in {"auto", "local-only"} and cache_path.exists():
        return pd.read_csv(cache_path, index_col="date", parse_dates=True)
    if mode == "local-only":
        raise FileNotFoundError(f"No cached RONI data at {cache_path}; run with --data-mode update first")

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
            cache_dir.mkdir(parents=True, exist_ok=True)
            df.to_csv(cache_path, index_label="date")
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


def make_plot(
    prices_df: pd.DataFrame,
    roni_df: pd.DataFrame,
    periods: list[tuple[pd.Timestamp, pd.Timestamp]],
    out: str | Path = REPORT_PATH,
    top_n: int = 25,
    min_observations: int = 60,
    security_metadata: pd.DataFrame | None = None,
):
    prices_df = prices_df.copy()
    # Ensure Date column exists
    if "Date" not in prices_df.columns:
        prices_df.index.name = "Date"
        prices_df = prices_df.reset_index()

    prices_df["Date"] = pd.to_datetime(prices_df["Date"])
    prices_df = prices_df.sort_values("Date")
    first_price, last_price = prices_df["Date"].min(), prices_df["Date"].max()
    selected_results, all_tests = calculate_predictive_screen(
        prices_df, roni_df, min_observations=min_observations
    )
    if security_metadata is not None:
        for row in security_metadata.itertuples(index=False):
            TICKERS[row.ticker] = str(row.name)
            CATEGORIES[row.ticker] = str(row.category)
            COUNTRIES[row.ticker] = str(row.country)
        for frame in (selected_results, all_tests):
            frame["name"] = frame["ticker"].map(TICKERS)
            frame["category"] = frame["ticker"].map(CATEGORIES).fillna("Other")
            frame["country"] = frame["ticker"].map(COUNTRIES).fillna("Other")
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    all_tests.sort_values(["q_value", "selection_score"], ascending=[True, False]).to_csv(
        RESULTS_PATH, index=False, compression="gzip"
    )
    print(f"Wrote full statistical audit table to {RESULTS_PATH}")
    correlations = (
        selected_results.assign(abs_expected=lambda frame: frame["expected_abnormal_return"].abs())
        .sort_values(
            ["passes_validation", "significant", "selection_score", "abs_expected"],
            ascending=[False, False, False, False],
        )
        .head(top_n)
        .sort_values("expected_abnormal_return")
    )
    tickers = correlations["ticker"].tolist()
    prices_df = prices_df[["Date", *tickers]]
    initially_visible = set(tickers)

    fig = make_subplots(
        rows=2, cols=1, row_heights=[0.68, 0.32], vertical_spacing=0.16,
        subplot_titles=("Adjusted prices, rebased to 100", "Predicted abnormal return under the latest positive RONI signal"),
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
        ("#B42318" if value < 0 else "#087E6A") if significant and validated else "#AAB4BA"
        for value, significant, validated in zip(
            correlations["expected_abnormal_return"], correlations["significant"], correlations["passes_validation"]
        )
    ]
    significance_labels = correlations["q_value"].map(
        lambda q: "***" if q < 0.001 else "**" if q < 0.01 else "*" if q < 0.05 else ""
    )
    fig.add_trace(go.Bar(
        x=correlations["expected_abnormal_return"], y=correlations["ticker"], orientation="h",
        name="Predicted abnormal return", showlegend=False, marker_color=bar_colors,
        customdata=correlations[[
            "horizon_months", "category", "country", "oos_r2", "directional_accuracy",
            "el_nino_events", "event_sign_consistency", "correlation", "p_value", "q_value",
        ]],
        hovertemplate=(
            "%{y} — %{customdata[1]}<br>Country: %{customdata[2]}"
            "<br>Selected horizon: %{customdata[0]:.0f} months"
            "<br>Predicted abnormal return: %{x:.2%}"
            "<br>RONI correlation: %{customdata[7]:.3f}"
            "<br>Walk-forward OOS R²: %{customdata[3]:.3f}"
            "<br>Directional accuracy: %{customdata[4]:.1%}"
            "<br>El Niño events: %{customdata[5]:.0f}"
            "<br>Event sign consistency: %{customdata[6]:.1%}"
            "<br>HAC p-value: %{customdata[8]:.4f}"
            "<br>BH-FDR q: %{customdata[9]:.4f}<extra></extra>"
        ),
        text=[f"{value:+.1%}{stars}" for value, stars in zip(correlations["expected_abnormal_return"], significance_labels)],
        textposition="outside", cliponaxis=False,
    ), row=2, col=1)

    fig.update_layout(
        title={"text": "Global Weather-Sensitive Securities During El Niño Episodes", "x": 0.04, "xanchor": "left", "y": 0.985},
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
    return_limit = max(0.01, correlations["expected_abnormal_return"].abs().max() * 1.25)
    fig.update_xaxes(title_text="Model-implied abnormal return", range=[-return_limit, return_limit], tickformat=".1%", zeroline=True, zerolinecolor="#80909a", row=2, col=1)
    fig.update_yaxes(title_text="Security", row=2, col=1)
    fig.add_annotation(
        text=(
            "<b>How to read this plot:</b> Each bar is the model-implied market-adjusted return over its selected 1, 3, or 6 month horizon, "
            "using the latest observed positive <a href='https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/'>NOAA RONI</a> signal. "
            "Horizons are selected using walk-forward out-of-sample performance and consistency across historical El Niño episodes. "
            "Dark bars pass both validation and universe-wide significance; gray bars remain exploratory. "
            "Stars show the corrected <a href='https://en.wikipedia.org/wiki/False_discovery_rate'>q-value</a>: "
            "* q&lt;0.05, ** q&lt;0.01, *** q&lt;0.001.<br>The "
            "The predictive regression uses <a href='https://en.wikipedia.org/wiki/Newey%E2%80%93West_estimator'>Newey–West HAC standard errors</a> "
            "to account for heteroskedasticity and serial dependence, and the "
            "<a href='https://en.wikipedia.org/wiki/Benjamini%E2%80%93Hochberg_procedure'>Benjamini–Hochberg procedure</a> "
            "controls the <a href='https://en.wikipedia.org/wiki/False_discovery_rate'>false-discovery rate</a> across the "
            f"{len(all_tests):,} stock–horizon tests. The {len(correlations)} strongest validated rankings are shown; "
            f"{int((correlations['significant'] & correlations['passes_validation']).sum())} pass both validation and q&lt;0.05. "
            "<a href='https://en.wikipedia.org/wiki/Correlation_does_not_imply_causation'>Correlation does not establish causation</a>."
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Screen a cached broad equity universe against NOAA RONI")
    parser.add_argument(
        "--data-mode", choices=("auto", "local-only", "update"), default="auto",
        help="auto uses cache if present; local-only forbids downloads; update refreshes all caches",
    )
    parser.add_argument("--clear-cache", action="store_true", help="delete cached universe, RONI, and prices before running")
    parser.add_argument("--top", type=int, default=25, help="maximum ranked securities to report (default: 25)")
    parser.add_argument(
        "--min-observations", type=int, default=60,
        help="minimum matched monthly returns per security (default: 60)",
    )
    parser.add_argument("--batch-size", type=int, default=100, help="Yahoo download batch size (default: 100)")
    return parser.parse_args()


def main():
    args = parse_args()
    if args.top < 1 or args.batch_size < 1 or args.min_observations < 24:
        raise SystemExit("--top/--batch-size must be positive and --min-observations must be at least 24")
    if args.clear_cache:
        clear_cache(CACHE_DIR)
        print(f"Cleared cache: {CACHE_DIR}")

    supplemental = pd.DataFrame([
        {"ticker": ticker, "name": name, "country": COUNTRIES[ticker], "category": CATEGORIES[ticker]}
        for ticker, name in TICKERS.items()
    ])
    try:
        universe = load_or_update_universe(CACHE_DIR, args.data_mode, supplemental)
        monthly = load_or_update_prices(
            CACHE_DIR, universe, args.data_mode, batch_size=args.batch_size
        )
        # CSV loading creates one block per column; consolidate before adding Date
        # so broad-universe local runs do not trigger pandas fragmentation warnings.
        monthly = pd.DataFrame(
            monthly.to_numpy(copy=False), index=monthly.index, columns=monthly.columns
        )
        prices = monthly.rename_axis("Date").reset_index()
    except Exception as e:
        print("Error fetching prices:", e)
        sys.exit(1)

    try:
        oni = fetch_roni(args.data_mode)
    except Exception as e:
        print("Error fetching RONI data:", e)
        sys.exit(1)

    periods = get_el_nino_periods(oni, threshold=0.5)
    make_plot(
        prices, oni, periods, top_n=args.top,
        min_observations=args.min_observations, security_metadata=universe,
    )


if __name__ == "__main__":
    main()
