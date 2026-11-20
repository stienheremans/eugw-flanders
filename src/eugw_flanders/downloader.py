import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Iterable

import requests
from osgeo import gdal
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

gdal.UseExceptions()

BUCKET_URL = (
    "https://s3.waw4-1.cloudferro.com/"
    "eugw.waw4-1.npu53ji70x7yerfririieu33p23vdtccueyyvrs0uci9ow3kxff"
)
NS = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}

AVAILABLE_YEARS = [str(y) for y in range(1994, 2025)]

INDICATOR_ALIASES: dict[str, str] = {
    "BSAN_MONTHLY": "BSAN",
}

INDICATOR_CATALOG: dict[str, str] = {
    # Land Cover & Masks
    "LCMH": "Land Cover Harmonized (CLASS: 1994-2024; CONF: 2016-2024)",
    "LCMA": "Land Cover Prediction: Annual (2016-2024, 10m)",
    "LCMR": "Land Cover Prediction: Reference / Raw (2016-2024, 10m)",
    "AGGM": "Aggregated Grassland Mask (1994-2024)",
    "LSQA": "Land Cover Quality Assessment (1994-2024)",
    "S2QA": "Sentinel-2 Quality Assessment / Valid Months (2016-2024, 60m)",
    # Grassland Type
    "GTYH": "Grassland Type Harmonized (CLASS: 2000-2024 6-yr; CONF: 2018, 2024)",
    "GTYP": "Grassland Type Prediction (2000-2024 6-yr)",
    # Grassland Persistence
    "GPER": "Grassland Persistence Relative - all LC (1994-2024)",
    "GPEY": "Grassland Persistence Year - all LC (1994-2024)",
    "GALR": "Grassland Persistence Relative - arable (1994-2024)",
    "GALY": "Grassland Alteration / Last Ploughing Year - arable (1994-2024)",
    # Grassland Management & Intensity
    "GMNG": "Grassland Management Characterization (2019-2024, 10m)",
    "MNEV": "Mowing: Number of Events (2019-2024, 10m)",
    "MFED": "Mowing: First Event Date DOY (2019-2024, 10m)",
    "MLED": "Mowing: Last Event Date DOY (2019-2024, 10m)",
    "MGDI": "Mowing: Growth Duration Interval (2019-2024, 10m)",
    "MGPI": "Mowing: Growth Productivity Index (2019-2024, 10m)",
    "MNPI": "Mowing: Non-Productive Interval (2019-2024, 10m)",
    "MGRA": "Management Intensity: Grazing Events (2019-2024, annual & monthly, 10m)",
    "MMOW": "Management Intensity: Mowing Events (2019-2024, annual & monthly, 10m)",
    "MOTH": "Management Intensity: Other Events (2019-2024, annual & monthly, 10m)",
    "MPLG": "Management Intensity: Ploughing Events (2019-2024, annual & monthly, 10m)",
    # Bare Soil
    "BSAN": "Bare Soil: Monthly Anomaly / Occurrence (BSAN_MONTHLY, 2016-2024, 10m)",
    "BSOC": "Bare Soil: Monthly Occurrence (2016-2024, monthly, 10m)",
    "BSAP": "Bare Soil: Annual Proportion (2016-2024, 10m)",
    "BSRP": "Bare Soil: Relative Persistence (2016-2024, 10m)",
    "BSAT": "Bare Soil: Alteration Type (2016-2024, 10m)",
    # Grassland Productivity (Short-Term & Long-Term)
    "GSTP": "Short-Term Productivity Thematic Layer (2022-2024, 10m)",
    "GLTP": "Long-Term Productivity Thematic Layer (2011-2024)",
    "SPPC": "Short-Term Performance Percentile (2022-2024, 10m)",
    "SPPZ": "Short-Term Performance Z-Score (2022-2024, 10m)",
    "LPPC": "Long-Term Performance Percentile (2011-2024)",
    "LPPZ": "Long-Term Performance Z-Score (2011-2024)",
    "SPSC": "Short-Term State Percentile Classes Change (2022-2024, 10m)",
    "SPSP": "Short-Term State Percentile (2022-2024, 10m)",
    "SPSZ": "Short-Term State Z-Score (2022-2024, 10m)",
    "LPSC": "Long-Term State Percentile Classes Change (2011-2024)",
    "LPSP": "Long-Term State Percentile (2011-2024)",
    "LPSZ": "Long-Term State Z-Score (2011-2024)",
    "SPTR": "Short-Term Productivity Trend Slope (2022-2024, 10m)",
    "SPRR": "Short-Term Productivity Trend Relative Rate (2022-2024, 10m)",
    "SPTD": "Short-Term Productivity Trend Direction / Significance (2022-2024, 10m)",
    "SPTS": "Short-Term Productivity Trend Sen's Slope (2022-2024, 10m)",
    "LPTR": "Long-Term Productivity Trend Slope (2011-2024)",
    "LPRR": "Long-Term Productivity Trend Relative Rate (2011-2024)",
    "LPTD": "Long-Term Productivity Trend Direction / Significance (2011-2024)",
    "LPTS": "Long-Term Productivity Trend Sen's Slope (2011-2024)",
}

TILE_PATTERN = re.compile(
    r"BE_ATL_ATC_\d+_(\d{8})_(\d{8})_([A-Z0-9]+)(?:_([A-Z0-9_]+))?\.tif$",
    re.IGNORECASE,
)


def _normalize_indicators(indicators: Iterable[str] | str | None) -> set[str]:
    """Normalize indicator codes and resolve known aliases (e.g. BSAN_MONTHLY -> BSAN)."""
    if indicators is None:
        return set(INDICATOR_CATALOG.keys())
    if isinstance(indicators, str):
        if indicators.strip().lower() == "all":
            return set(INDICATOR_CATALOG.keys())
        raw_items = [indicators.strip().upper()]
    else:
        raw_items = [str(i).strip().upper() for i in indicators if i is not None]

    return {INDICATOR_ALIASES.get(code, code) for code in raw_items if code}


def _format_time_tag(start_date: str, end_date: str) -> str:
    """Format YYYY for annual/multi-year products and YYYYMM for monthly products."""
    if start_date[4:] == "0101" and end_date[4:] == "1231":
        return end_date[:4]
    if start_date[:6] == end_date[:6] and start_date[6:] == "01":
        return start_date[:6]
    return f"{start_date}_{end_date}"


def _create_session() -> requests.Session:
    session = requests.Session()
    retries = Retry(
        total=5,
        backoff_factor=1.0,
        status_forcelist=[429, 500, 502, 503, 504],
    )
    adapter = HTTPAdapter(max_retries=retries, pool_connections=16, pool_maxsize=16)
    session.mount("https://", adapter)
    session.headers.update({
        "Referer": "https://demo.eu-grassland-watch.eu/",
        "User-Agent": "eugw-flanders/0.1.0 (Research Institute for Nature and Forest - INBO)",
    })
    return session


def _find_indicator_folders(
    session: requests.Session,
    needed_indicators: set[str],
    prefix: str = "output/",
    depth: int = 0,
) -> dict[str, list[str]]:
    """Walk S3 folder prefixes to locate all matching indicator folders."""
    found: dict[str, list[str]] = defaultdict(list)
    if depth > 4:
        return found

    resp = session.get(
        BUCKET_URL,
        params={"list-type": "2", "prefix": prefix, "delimiter": "/"},
        timeout=30,
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.text)

    for cp in root.findall("s3:CommonPrefixes", NS):
        sub_prefix = cp.find("s3:Prefix", NS).text
        if "stac_dir" in sub_prefix or "_90km" in sub_prefix or "_landsat" in sub_prefix:
            continue

        folder_name = sub_prefix.rstrip("/").split("/")[-1].upper()
        if folder_name in needed_indicators:
            found[folder_name].append(sub_prefix)
            print(f"  Located S3 folder: {sub_prefix}", flush=True)
        else:
            nested = _find_indicator_folders(
                session, needed_indicators, sub_prefix, depth + 1
            )
            for k, v in nested.items():
                found[k].extend(v)

    return found


def _list_flanders_keys(session: requests.Session, folder_prefix: str) -> list[str]:
    """List Belgian Atlantic Central (BE_ATL_ATC_*) GeoTIFF keys in one S3 folder."""
    keys: list[str] = []
    continuation_token = None

    while True:
        params = {"list-type": "2", "prefix": f"{folder_prefix}BE_ATL_ATC_"}
        if continuation_token:
            params["continuation-token"] = continuation_token

        resp = session.get(BUCKET_URL, params=params, timeout=30)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)

        for content in root.findall("s3:Contents", NS):
            key = content.find("s3:Key", NS).text
            if key.lower().endswith(".tif"):
                keys.append(key)

        is_truncated = root.find("s3:IsTruncated", NS)
        if is_truncated is not None and is_truncated.text == "true":
            continuation_token = root.find("s3:NextContinuationToken", NS).text
        else:
            break

    return keys


def get_available_years(
    indicators: Iterable[str] | str | None = "all",
) -> dict[str, list[str]]:
    """Query S3 to inspect which years are available in Flanders per indicator (and suffix)."""
    target_indicators = _normalize_indicators(indicators)
    session = _create_session()
    indicator_folders = _find_indicator_folders(session, target_indicators)
    years_by_layer: dict[str, set[str]] = defaultdict(set)
    found_indicators: set[str] = set()

    for folders in indicator_folders.values():
        for folder in folders:
            for key in _list_flanders_keys(session, folder):
                match = TILE_PATTERN.search(Path(key).name)
                if not match:
                    continue
                ref_year = match.group(2)[:4]
                ind = match.group(3).upper()
                if ind not in target_indicators:
                    continue
                suffix = match.group(4).upper() if match.group(4) else ""
                layer_name = f"{ind}_{suffix}" if suffix else ind
                years_by_layer[layer_name].add(ref_year)
                found_indicators.add(ind)

    for ind in target_indicators - found_indicators:
        years_by_layer[ind] = set()

    return {layer: sorted(years_by_layer[layer]) for layer in sorted(years_by_layer)}


def _download_tile(
    session: requests.Session, key: str, tile_dir: Path
) -> tuple[str, str]:
    """Atomically download a single GeoTIFF tile if not already present locally."""
    fname = Path(key).name
    dest = tile_dir / fname
    if dest.exists() and dest.stat().st_size > 0:
        return fname, "skipped"

    tmp_dest = dest.with_suffix(".tif.part")
    url = f"{BUCKET_URL}/{key}"
    with session.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(tmp_dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)
    tmp_dest.replace(dest)
    return fname, "downloaded"


def _quiet_gdal_warnings(err_class, err_num, err_msg):
    """Suppress harmless libtiff ExtraSamples warnings while keeping errors fatal."""
    if err_class >= gdal.CE_Failure:
        raise RuntimeError(f"GDAL Error {err_num}: {err_msg}")


def download_eugw_data(
    indicators: Iterable[str] | str,
    years: Iterable[int | str] | str = "all",
    output_dir: str | Path = "./eugw_data",
    build_vrts: bool = True,
    max_workers: int = 8,
) -> dict:
    """
    Download EU Grassland Watch (EUGW) GeoTIFF tiles for Flanders and build VRT mosaics.

    Args:
        indicators: List of indicator codes (e.g. ['LCMH', 'MNEV', 'BSAN']), a single
            indicator string, or 'all' for all cataloged indicators.
        years: List of years (1994-2024) or 'all'.
        output_dir: Destination folder (creates 'tiles/' and 'vrts/' subfolders).
        build_vrts: If True, builds GDAL .vrt mosaics for each requested layer-period.
        max_workers: Number of parallel download threads.

    Returns:
        Summary dictionary with counts and generated VRT file paths.
    """
    target_indicators = _normalize_indicators(indicators)

    if isinstance(years, str):
        if years.lower() == "all":
            target_years = set(AVAILABLE_YEARS)
        else:
            target_years = {years.strip()}
    else:
        target_years = {str(y).strip() for y in years}

    invalid_years = target_years - set(AVAILABLE_YEARS)
    if invalid_years:
        raise ValueError(
            f"Unsupported year(s): {sorted(invalid_years)}. "
            "Available EUGW years in Flanders span 1994 to 2024."
        )

    out_path = Path(output_dir)
    tile_dir = out_path / "tiles"
    vrt_dir = out_path / "vrts"
    tile_dir.mkdir(parents=True, exist_ok=True)
    if build_vrts:
        vrt_dir.mkdir(parents=True, exist_ok=True)

    session = _create_session()
    print("Locating EUGW indicator folders on S3...", flush=True)
    indicator_folders = _find_indicator_folders(session, target_indicators)

    missing = target_indicators - set(indicator_folders.keys())
    if missing:
        print(f"WARNING: No S3 folder found for: {sorted(missing)}", flush=True)

    all_folders = sorted({f for folders in indicator_folders.values() for f in folders})
    selected_keys: list[str] = []
    for folder in all_folders:
        for key in _list_flanders_keys(session, folder):
            match = TILE_PATTERN.search(Path(key).name)
            if not match:
                continue
            ref_year = match.group(2)[:4]
            indicator = match.group(3).upper()
            if indicator in target_indicators and ref_year in target_years:
                selected_keys.append(key)

    selected_keys = sorted(set(selected_keys))
    total = len(selected_keys)
    print(f"\nMatched {total} Flemish GeoTIFF tiles.\n", flush=True)
    if not selected_keys:
        return {"downloaded": 0, "skipped": 0, "vrts": []}

    counts = {"downloaded": 0, "skipped": 0}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(_download_tile, session, k, tile_dir) for k in selected_keys
        ]
        for idx, future in enumerate(as_completed(futures), 1):
            fname, status = future.result()
            counts[status] += 1
            print(f"[{idx}/{total}] {status}: {fname}", flush=True)

    built_vrts: list[Path] = []
    if build_vrts:
        print("\nBuilding VRT mosaics...", flush=True)
        gdal.PushErrorHandler(_quiet_gdal_warnings)
        try:
            grouped_tiles: dict[tuple[str, str, str], list[str]] = defaultdict(list)
            for tif_path in sorted(tile_dir.glob("*.tif")):
                match = TILE_PATTERN.search(tif_path.name)
                if match:
                    start_date = match.group(1)
                    end_date = match.group(2)
                    ref_year = end_date[:4]
                    indicator = match.group(3).upper()
                    suffix = match.group(4).upper() if match.group(4) else ""
                    if indicator in target_indicators and ref_year in target_years:
                        time_tag = _format_time_tag(start_date, end_date)
                        grouped_tiles[(indicator, suffix, time_tag)].append(str(tif_path))

            for (indicator, suffix, time_tag), tif_list in sorted(grouped_tiles.items()):
                vrt_name = (
                    f"EUGW_{indicator}_{suffix}_{time_tag}.vrt"
                    if suffix
                    else f"EUGW_{indicator}_{time_tag}.vrt"
                )
                vrt_file = vrt_dir / vrt_name
                gdal.BuildVRT(str(vrt_file), tif_list)
                built_vrts.append(vrt_file)
                print(f"Built VRT: {vrt_file.name} ({len(tif_list)} tiles)", flush=True)
        finally:
            gdal.PopErrorHandler()

    print("\nDone.", flush=True)
    return {
        "downloaded": counts["downloaded"],
        "skipped": counts["skipped"],
        "vrts": built_vrts,
    }