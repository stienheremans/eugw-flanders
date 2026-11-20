import argparse
from pathlib import Path

from eugw_flanders.downloader import (
    AVAILABLE_YEARS,
    INDICATOR_CATALOG,
    download_eugw_data,
    get_available_years,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="eugw-download",
        description="Download EU Grassland Watch (EUGW) tiles and VRTs for Flanders (1994-2024).",
    )
    parser.add_argument(
        "-l", "--list",
        action="store_true",
        help="List all available EUGW indicator codes and exit.",
    )
    parser.add_argument(
        "--list-years",
        action="store_true",
        help="Query S3 and display exact available years per indicator in Flanders.",
    )
    parser.add_argument(
        "-i", "--indicators",
        type=str,
        default=None,
        help=(
            "Comma-separated indicator codes (e.g. LCMH,MNEV,BSAN_MONTHLY) "
            "or 'all' for all available indicators."
        ),
    )
    parser.add_argument(
        "-y", "--years",
        type=str,
        default="2024",
        help=(
            "Comma-separated years from 1994 to 2024 (e.g. 1995,2010,2024), "
            "a range (e.g. 1994-2024), or 'all' (default: 2024)."
        ),
    )
    parser.add_argument(
        "-o", "--outdir",
        type=Path,
        default=Path("./eugw_data"),
        help="Output directory (default: ./eugw_data).",
    )
    parser.add_argument(
        "-w", "--workers",
        type=int,
        default=8,
        help="Number of parallel download threads (default: 8).",
    )
    parser.add_argument(
        "--no-vrt",
        action="store_true",
        help="Download raw GeoTIFF tiles only without building .vrt mosaics.",
    )

    args = parser.parse_args()

    if args.list:
        print("Available EUGW Indicators in Flanders (1994-2024):")
        for code, desc in INDICATOR_CATALOG.items():
            print(f"  {code:<6} - {desc}")
        return

    if args.list_years:
        raw_ind = (args.indicators or "").strip()
        if not raw_ind or raw_ind.lower() in {"all", "none"}:
            target: list[str] | str = "all"
        else:
            target = [x.strip().upper() for x in raw_ind.split(",") if x.strip()]

        print("Querying CloudFerro S3 for available years in Flanders...")
        availability = get_available_years(target)
        print("\nAvailable Years per Layer:")
        for code, yrs in availability.items():
            if not yrs:
                span = "no tiles found"
            elif len(yrs) == 1:
                span = f"{yrs[0]} (1 year)"
            elif len(yrs) == int(yrs[-1]) - int(yrs[0]) + 1:
                span = f"{yrs[0]}-{yrs[-1]} ({len(yrs)} years, continuous)"
            else:
                span = f"{yrs[0]}-{yrs[-1]} ({len(yrs)} years: {', '.join(yrs)})"
            print(f"  {code:<12} - {span}")
        return

    raw_ind = (args.indicators or "").strip()
    if not raw_ind or raw_ind.lower() == "none":
        parser.error("the following arguments are required: -i/--indicators (or use --list)")

    if raw_ind.lower() == "all":
        indicators: list[str] | str = "all"
    else:
        indicators = [x.strip().upper() for x in raw_ind.split(",") if x.strip()]

    if args.years.lower() == "all":
        years: list[str] | str = AVAILABLE_YEARS
    elif "-" in args.years and "," not in args.years:
        start, end = args.years.split("-", 1)
        years = [str(y) for y in range(int(start), int(end) + 1)]
    else:
        years = [x.strip() for x in args.years.split(",") if x.strip()]

    download_eugw_data(
        indicators=indicators,
        years=years,
        output_dir=args.outdir,
        build_vrts=not args.no_vrt,
        max_workers=args.workers,
    )


if __name__ == "__main__":
    main()