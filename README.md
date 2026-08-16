# El Niño Securities Screen

This project generates an interactive report that compares weather-sensitive securities with NOAA's Relative Oceanic Niño Index (RONI). It is an exploratory correlation screen, not a trading model or evidence that El Niño causes security returns.

## Project layout

```text
.
├── artifacts/
│   └── cane_el_nino.html       # Generated interactive report
├── src/
│   ├── plot_cane_el_nino.py    # Main data, statistics, and chart pipeline
│   └── download_prices.py      # Optional raw CANE price downloader
├── README.md
└── requirements.txt
```

## Setup and usage

Python 3.10 or newer is recommended. From the project root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python src/plot_cane_el_nino.py
```

Open `artifacts/cane_el_nino.html` in a web browser. The script always writes there, even if launched from another working directory. It requires internet access because prices come from Yahoo Finance and RONI comes from NOAA.

To download raw CANE history separately:

```bash
python src/download_prices.py
```

That optional script writes CSV data to `artifacts/stock_data/`.

## Securities screened

The report covers several plausible El Niño transmission channels:

- Commodity funds: `CANE`, `DBA`, `CORN`, `WEAT`, `SOYB`
- Crop processing and inputs: `ADM`, `BG`, `MOS`, `NTR`, `CF`, `FMC`, `CTVA`
- Food and agriculture demand: `TSN`, `DE`, `SBUX`, `KDP`, `HSY`, `GIS`, `CAG`
- Rainfall-sensitive mining and utilities: `FCX`, `SCCO`, `ELPC`, `SBS`
- Transport and insured weather losses: `MATX`, `CB`

Candidate channels are motivated by [FAO's overview of El Niño risks](https://www.fao.org/el-nino/en/) and the [World Bank's review of commodity impacts](https://thedocs.worldbank.org/en/doc/916451445285454750-0050022015/original/CMOOct2015FeatureElNino.pdf). Inclusion is only a screening hypothesis.

## How the report works

The upper chart uses adjusted closing prices, which account for splits and distributions. Each series is rebased to 100 at its first available observation so securities with different price scales can be compared. NOAA RONI warm episodes are shaded when RONI is at least 0.5°C for five consecutive overlapping three-month seasons. The seven largest absolute correlations plus `CANE` are visible initially; other series can be enabled from the legend.

The lower chart calculates Pearson's correlation coefficient between each security's monthly adjusted-price return and the contemporaneous monthly RONI value. Using returns instead of price levels reduces spurious correlations caused by unrelated long-term price trends.

## Interpreting correlation and significance

- A negative coefficient means returns tended to be lower in months with higher RONI values.
- A positive coefficient means returns tended to be higher in months with higher RONI values.
- Coefficients near zero indicate little contemporaneous linear relationship.
- Dark red bars are statistically significant negative correlations.
- Dark teal bars are statistically significant positive correlations.
- Gray bars do not pass the corrected 5% significance threshold.
- `*`, `**`, and `***` mean corrected q-values below 0.05, 0.01, and 0.001 respectively.

Significance begins with the conventional two-sided Student's t test for Pearson's correlation. Because RONI is serially correlated, the test reduces the nominal sample size using a lag-1 AR effective-sample-size approximation. It then applies the Benjamini–Hochberg procedure across the full screen to control the false-discovery rate. Exact observations, effective observations, p-values, and corrected q-values are available in each bar's tooltip; the report caption links to further explanations of every statistical term.

These adjustments reduce common sources of false positives, but they do not control for market returns, seasonality, commodity prices, macroeconomic conditions, nonlinear effects, or lagged responses. Statistical significance is not the same as economic importance, and correlation does not establish causation.

## Data notes

- Security prices: Yahoo Finance through `yfinance`
- ENSO measure: [NOAA CPC RONI](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso/roni/)
- Minimum correlation history: 24 matched monthly observations
- Output is refreshed whenever the main script runs
