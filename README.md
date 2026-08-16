# El Niño Securities Screen

This project screens a broad equity universe for relationships between monthly security returns and NOAA's Relative Oceanic Niño Index (RONI). It generates an interactive report containing the strongest correlations and a compressed audit table containing every eligible result.

This is an exploratory statistical screen, not a trading model. Correlation does not establish causation, and statistical significance does not imply that a relationship is economically meaningful or tradable.

## Setup

Python 3.10 or newer is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running the screen

Perform the initial universe and price download:

```bash
python src/plot_cane_el_nino.py --data-mode update
```

Later runs can use one of three data modes:

```bash
# Use cached data when available; download only when no cache exists.
python src/plot_cane_el_nino.py

# Prohibit network requests and require an existing cache.
python src/plot_cane_el_nino.py --data-mode local-only

# Refresh the universe and RONI, download full history for new symbols,
# and update recent prices for previously cached symbols.
python src/plot_cane_el_nino.py --data-mode update
```

Additional options:

```bash
# Delete artifacts/cache/ and rebuild it.
python src/plot_cane_el_nino.py --clear-cache --data-mode update

# Show 50 results, require seven years of monthly observations, and use
# download batches of 200 symbols.
python src/plot_cane_el_nino.py \
  --top 50 \
  --min-observations 84 \
  --batch-size 200 \
  --data-mode update
```

Run `python src/plot_cane_el_nino.py --help` for the complete CLI reference.

## Data universe and cache

The script builds its primary universe from the Nasdaq Trader symbol directories for Nasdaq and other US-listed securities. It removes entries identified as ETFs, test issues, preferred shares, warrants, rights, units, or debt. A curated set of international and weather-sensitive securities defined in `plot_cane_el_nino.py` is then added to the universe.

Yahoo Finance does not provide an authoritative list of every global stock, so this is a broad reproducible universe rather than complete worldwide coverage.

The cache is stored under `artifacts/cache/`:

- `universe.csv`: resolved screening universe and metadata
- `monthly_adjusted_prices.csv.gz`: monthly adjusted prices
- `roni.csv`: parsed NOAA RONI observations

Price downloads run in resumable batches and checkpoint every ten batches. `--clear-cache` removes only this directory; generated reports remain intact.

## Outputs

Every successful run creates:

- `artifacts/cane_el_nino.html`: interactive charts for up to `--top` securities, ranked by absolute correlation
- `artifacts/el_nino_screen.csv.gz`: the complete eligible result set, including observations, correlation, regression slope, HAC bandwidth, p-value, BH-FDR q-value, and significance flag

The HTML report rebases each displayed adjusted-price series to 100 and shades El Niño episodes where RONI is at least 0.5°C for five consecutive overlapping seasons.

## Statistical method

For each security, the script:

1. Converts monthly adjusted prices to percentage returns.
2. Aligns returns with contemporaneous monthly RONI values.
3. Requires 60 matched observations by default. `--min-observations` can change this value but cannot be lower than 24.
4. Reports Pearson's correlation coefficient.
5. Regresses return on RONI with an intercept and calculates a two-sided p-value using Newey–West heteroskedasticity-and-autocorrelation-consistent standard errors. The automatic bandwidth is `floor(4(n/100)^(2/9))`.
6. Applies the Benjamini–Hochberg correction across the entire eligible universe, not only the displayed results. A result is marked significant when its corrected q-value is below 0.05.
7. Displays the securities with the largest absolute correlations, whether significant or not. Significant positive and negative results are colored teal and red; nonsignificant results are gray.

The method addresses multiple comparisons, heteroskedasticity, and short-run serial dependence. It does not control for market returns, seasonality, other economic variables, nonlinear or lagged effects, or survivorship bias in the current listing universe.

## Project files

```text
.
├── artifacts/
│   ├── cache/
│   ├── cane_el_nino.html
│   └── el_nino_screen.csv.gz
├── src/
│   ├── plot_cane_el_nino.py
│   └── universe_cache.py
├── README.md
└── requirements.txt
```

Data sources:

- Security universe: [Nasdaq Trader symbol directory](https://www.nasdaqtrader.com/Trader.aspx?id=SymbolDirDefs)
- Security prices: Yahoo Finance through `yfinance`
- ENSO index: [NOAA CPC RONI](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/)
