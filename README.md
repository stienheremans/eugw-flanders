# eugw-flanders

Programmatic downloader and GDAL Virtual Raster (VRT) mosaic builder for **EU Grassland Watch (EUGW)** Earth Observation products covering **Flanders, Belgium** (`BE_ATL_ATC_*`, 1994–2024).

## Features

* **Complete S3 Catalog (48 Indicators):** Supports all 48 EUGW indicators available for Flanders on the CloudFerro S3 object storage—including land cover, grassland type, persistence, mowing and grazing intensity, bare soil (annual and monthly, including `BSAN` / `BSAN_MONTHLY`), and short-/long-term productivity metrics.
* **Live Availability Inspection:** Query exact available years per indicator and sub-layer directly from S3 before downloading (`--list-years`).
* **Parallel & Resumable Downloads:** Uses multi-threaded downloads with automatic retries and atomic `.part` file writes so interrupted runs can be safely resumed.
* **Automatic VRT Mosaics:** Builds seamless GDAL `.vrt` mosaics grouped by indicator, optional sub-layer suffix (`CLASS`, `CONF`), and temporal period (`YYYY` for annual/multi-year layers, `YYYYMM` for monthly layers).

## Requirements

* Python ≥ 3.10
* `requests`
* `GDAL` (`osgeo.gdal` Python bindings, e.g., installed via `conda` / `micromamba` from `conda-forge`)

## Installation

Install from source in editable or standard mode inside an environment with GDAL available:

```bash
git clone [https://github.com/inbo/eugw-flanders.git](https://github.com/inbo/eugw-flanders.git)
cd eugw-flanders
pip install -e .
```

## Usage

### Command Line (`eugw-download`)

* `--indicators` (`-i`): Comma-separated indicator codes (e.g., `LCMH,MNEV,BSAN_MONTHLY`) or `all` for all 48 cataloged indicators.
* `--years` (`-y`): Single year, comma-separated list (`1995,2010,2024`), range (`1994-2024`), or `all` (default: `2024`).
* `--outdir` (`-o`): Destination folder (default: `./eugw_data`).

```bash
# List all 48 indicator codes and descriptions
eugw-download --list

# Inspect exact available years on S3 per layer in Flanders
eugw-download --list-years
eugw-download --list-years --indicators LCMH,MNEV,BSAN_MONTHLY

# Download specific indicators across a multi-year range
eugw-download --indicators MNEV,MFED,SPPC --years 2022-2024 --outdir ./eugw_data

# Download monthly bare soil layers for a single year
eugw-download --indicators BSAN_MONTHLY --years 2024 --outdir ./eugw_data

# Download all available indicators for 2024
eugw-download --indicators all --years 2024 --outdir ./eugw_data
```

> **Note:** Combining `--indicators all --years all` will download tens of thousands of GeoTIFF tiles across the 1994–2024 archive. Ensure sufficient disk space before running a full archive download.

### Python API

```python
from eugw_flanders import download_eugw_data, get_available_years

# Inspect available years on S3
years = get_available_years(["LCMH", "MNEV", "BSAN"])
print(years)

# Download tiles and build VRT mosaics
result = download_eugw_data(
    indicators=["LCMH", "MNEV", "BSAN"],
    years=[2023, 2024],
    output_dir="./eugw_data",
)
print(result["vrts"])
```

## Output Structure

All downloads are saved inside `--outdir` (default: `./eugw_data`) using the following structure:

```text
eugw_data/
├── tiles/
│   ├── BE_ATL_ATC_0043_20240101_20241231_LCMH_CLASS.tif
│   ├── BE_ATL_ATC_0043_20240101_20241231_LCMH_CONF.tif
│   ├── BE_ATL_ATC_0043_20240101_20241231_MNEV.tif
│   ├── BE_ATL_ATC_0043_20240101_20240131_BSAN.tif
│   └── ...
└── vrts/
    ├── EUGW_LCMH_CLASS_2024.vrt
    ├── EUGW_LCMH_CONF_2024.vrt
    ├── EUGW_MNEV_2024.vrt
    ├── EUGW_BSAN_202401.vrt
    └── ...
```

* **`tiles/`** — Raw 15 km × 15 km GeoTIFF tiles (`BE_ATL_ATC_*`) downloaded from S3. Keep this folder intact, as the `.vrt` files reference these underlying tiles.
* **`vrts/`** — Seamless GDAL Virtual Rasters grouped by indicator, optional sub-layer suffix, and time period:
  * `EUGW_<INDICATOR>_<YYYY>.vrt` — Single-band annual or multi-year indicators (e.g., `EUGW_MNEV_2024.vrt`).
  * `EUGW_<INDICATOR>_<SUFFIX>_<YYYY>.vrt` — Thematic indicators with separate sub-layers such as `CLASS` and `CONF` (e.g., `EUGW_LCMH_CLASS_2024.vrt`).
  * `EUGW_<INDICATOR>_<YYYYMM>.vrt` — Monthly products (e.g., `EUGW_BSAN_202401.vrt` through `EUGW_BSAN_202412.vrt`).

> **Note on Sub-Layers (`CLASS` vs. `CONF`):** Thematic products such as `LCMH` and `GTYH` provide both a discrete classification map (`CLASS`) and a pixel-level confidence layer (`CONF`). Not all sub-layers span the same years (`LCMH_CLASS` covers `1994–2024`, whereas `LCMH_CONF` covers `2016–2024`). Run `eugw-download --list-years` to check exact coverage.

## Documentation & Data Sources

* **EU Grassland Watch Portal:** [ec.europa.eu/eu-grassland-watch](https://ec.europa.eu/eu-grassland-watch/)
* **Official List of Indicators & Services:** [demo.eu-grassland-watch.eu/disclaimer.html](https://demo.eu-grassland-watch.eu/disclaimer.html)
* **Copernicus Context:** [Tracking grassland conservation with EU Grasslands Watch (CLMS)](https://land.copernicus.eu/en/use-cases/tracking-grassland-conservation-with-eu-grasslands-watch)

### Spatial & Temporal Notes

* **Spatial Extent:** EUGW processes 15 km × 15 km ETRS89-LAEA (`EPSG:3035`) tiles intersecting Natura 2000 grassland sites (`BE_ATL_ATC_*` in Flanders). Areas outside those tiles are absent from the S3 archive.
* **Resolution Shift (1994–2024):** Historical harmonized layers in Flanders from `1994–2015` are derived from Landsat at **30 m** resolution, whereas Sentinel-2 era layers (`2016–2024`) are provided at **10 m** resolution (`60 m` for `S2QA`).
* **S3 Endpoint Stability:** Tile URLs point to the public CloudFerro S3 bucket currently backing the EU Grassland Watch platform and may require updating if the European Commission migrates storage paths in a future release.

## Attribution & Disclaimer

This package is an independent utility developed at the **Research Institute for Nature and Forest (INBO)** to retrieve public raster tiles from the EU Grassland Watch CloudFerro object storage. It is not officially affiliated with or endorsed by the European Commission or the European Environment Agency.

All downloaded datasets are produced under the EU Grassland Watch initiative using Copernicus Land Monitoring Service (CLMS) and public Earth Observation data. When using these datasets in publications or reports, please cite the original EU Grassland Watch platform and Copernicus data sources.