# El Niño Securities Screen

This project tests whether NOAA's Relative Oceanic Niño Index (RONI), observed at month `t`, predicts market-adjusted security returns over the following 1, 3, or 6 months. It generates an interactive report containing the strongest validated forecasts and a compressed audit table containing every stock–horizon test.

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

- `artifacts/cane_el_nino.html`: interactive charts for up to `--top` securities, ranked by predictive selection score
- `artifacts/el_nino_screen.csv.gz`: every eligible stock–horizon test, including expected abnormal return, out-of-sample results, episode stability, HAC inference, and BH-FDR significance

The HTML report rebases each displayed adjusted-price series to 100 and shades El Niño episodes where RONI is at least 0.5°C for five consecutive overlapping seasons.

## Statistical method

For each security and each predefined 1-, 3-, and 6-month horizon, the script:

1. Converts monthly adjusted prices to percentage returns.
2. Compounds the security's returns over the future horizon and subtracts the corresponding return of a robust broad-universe market proxy. The proxy is the cross-sectional median monthly return, which reduces sensitivity to individual outliers.
3. Aligns that future abnormal return with RONI known at the beginning of the forecast window. RONI is never shifted backward from the future.
4. Requires 60 matched observations by default. `--min-observations` can change this value but cannot be lower than 24.
5. Regresses future abnormal return on RONI with an intercept. It reports the slope, Pearson correlation, model-implied abnormal return under the latest positive RONI observation, and a two-sided p-value.
6. Uses Newey–West heteroskedasticity-and-autocorrelation-consistent standard errors. Bandwidth is the greater of `floor(4(n/100)^(2/9))` and `horizon - 1`, accounting for dependence induced by overlapping forward returns.
7. Performs expanding-window out-of-sample validation. Training labels whose forward-return windows have not ended by the prediction date are purged, preventing look-ahead leakage. The audit table reports out-of-sample R², directional accuracy, and prediction count.
8. Measures sign consistency across distinct historical El Niño episodes. Validation requires positive out-of-sample R², at least three episodes, and matching effect direction in at least two-thirds of them.
9. Applies Benjamini–Hochberg correction jointly across every eligible stock–horizon test. Statistical significance requires `q < 0.05`.
10. Selects one horizon per stock, prioritizing validation and then a score combining effect-to-residual-risk, out-of-sample R², and episode consistency. The final ranking prioritizes validated, statistically significant results. Gray results remain exploratory.

This design tests prediction rather than contemporaneous association and addresses market-wide returns, multiple comparisons, heteroskedasticity, serial dependence, overlapping horizons, and basic temporal validation. It does not establish that El Niño caused a price change. It also does not control for sector, country, currency, commodity, or firm-specific news factors, nonlinear effects, or survivorship bias.

The model uses historical observed RONI because a stable machine-readable archive of official real-time NOAA/IRI forecast vintages is not available to the script. Its latest estimate is therefore conditional on the current observed RONI signal; it is not a backtest of changes in NOAA's published forecast probabilities.

## Project files

```text
.
├── artifacts/
│   ├── cache/
│   ├── cane_el_nino.html
│   └── el_nino_screen.csv.gz
├── src/
│   ├── plot_cane_el_nino.py
│   ├── predictive_screen.py
│   └── universe_cache.py
├── README.md
└── requirements.txt
```

Data sources:

- Security universe: [Nasdaq Trader symbol directory](https://www.nasdaqtrader.com/Trader.aspx?id=SymbolDirDefs)
- Security prices: Yahoo Finance through `yfinance`
- ENSO index: [NOAA CPC RONI](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/)
