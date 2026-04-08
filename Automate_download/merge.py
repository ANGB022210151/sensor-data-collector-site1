import argparse
from pathlib import Path
import sys
import pandas as pd


def find_csv_by_keywords(folder: Path, keywords: list[str]) -> Path:
    """Return the first CSV in folder whose name contains any keyword (case-insensitive).
    Prefers the shortest filename if multiple matches. Raises a helpful error if not found.
    """
    folder = folder.resolve()
    if not folder.is_dir():
        raise FileNotFoundError(f"Input folder does not exist: {folder}")

    csvs = list(folder.glob("*.csv"))
    if not csvs:
        raise FileNotFoundError(f"No CSV files found in {folder}")

    lower_keywords = [k.casefold() for k in keywords]
    matches: list[Path] = []
    for p in csvs:
        name = p.name.casefold()
        if any(k in name for k in lower_keywords):
            matches.append(p)

    if not matches:
        available = ", ".join(sorted(p.name for p in csvs))
        raise FileNotFoundError(
            f"No CSV found matching any of {keywords} in {folder}. Available: {available}"
        )

    # Prefer the shortest filename to break ties (often the most canonical)
    matches.sort(key=lambda p: (len(p.name), p.name))
    return matches[0]


def load_df(csv_path: Path) -> pd.DataFrame:
    # Be tolerant of BOM and common encodings
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    # Normalize column names to lower for robust key matching
    df.columns = [c.strip() for c in df.columns]
    lower_map = {c.lower(): c for c in df.columns}
    # Try to ensure there is a 'time' column name for merging
    time_candidates = [
        "time",
        "timestamp",
        "date time",
        "datetime",
        "date",
    ]
    for cand in time_candidates:
        if cand in lower_map:
            # Rename the original-cased column to 'time' if needed
            orig = lower_map[cand]
            if orig != "time":
                df = df.rename(columns={orig: "time"})
            break
    if "time" not in df.columns:
        raise KeyError(
            f"No time-like column found in {csv_path.name}. Columns: {list(df.columns)}"
        )
    return df


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Merge sensor CSVs by detecting files via keywords (temperature, turbidity, TDS, pH).\n"
            "Reads from an input folder and writes merged CSV to the output folder."
        )
    )
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=Path.cwd(),
        help="Folder containing the CSV files (default: current directory)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        help="Folder to write merged CSV (default: same as --input)",
    )
    parser.add_argument(
        "--outfile",
        type=str,
        default="merged_sensor_data.csv",
        help="Output CSV filename (default: merged_sensor_data.csv)",
    )
    parser.add_argument(
        "--sort",
        type=str,
        choices=["none", "date", "datetime"],
        default="datetime",
        help=(
            "Sorting mode: 'none' preserves original order; 'date' sorts by calendar date only; "
            "'datetime' sorts by full timestamp. Default: datetime"
        ),
    )
    parser.add_argument(
        "--order",
        type=str,
        choices=["asc", "desc"],
        default="asc",
        help="Sort order when --sort is not 'none': 'asc' for oldest-first, 'desc' for newest-first (default: asc)",
    )

    args = parser.parse_args(argv)
    in_dir: Path = args.input.resolve()
    out_dir: Path = (args.output.resolve() if args.output else in_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Define keyword sets for each sensor type
    # Use broad, case-insensitive substrings to tolerate varying file names
    temp_csv = find_csv_by_keywords(in_dir, ["temperature"])  # e.g., Temperature (°C)-....csv
    tds_csv = find_csv_by_keywords(
        in_dir,
        ["tds", "dissolve solid", "dissolved solid", "total dissolved", "dissolve"],
    )
    turb_csv = find_csv_by_keywords(in_dir, ["turbidity"])  # e.g., Turbidity (NTU)-....csv
    ph_csv = find_csv_by_keywords(in_dir, ["ph"])  # e.g., pH-....csv

    print("Detected files:")
    print(f"  Temperature: {temp_csv.name}")
    print(f"  TDS:         {tds_csv.name}")
    print(f"  Turbidity:   {turb_csv.name}")
    print(f"  pH:          {ph_csv.name}")

    df_temp = load_df(temp_csv)
    df_tds = load_df(tds_csv)
    df_turbidity = load_df(turb_csv)
    df_ph = load_df(ph_csv)

    # Merge on 'time' column, outer join to avoid losing rows
    df_new = (
        df_temp.merge(df_tds, on="time", how="outer")
        .merge(df_turbidity, on="time", how="outer")
        .merge(df_ph, on="time", how="outer")
    )

    # If existing merged CSV exists in output, APPEND new rows below (do not replace)
    out_path = out_dir / args.outfile
    if out_path.exists():
        try:
            df_existing = pd.read_csv(out_path, encoding="utf-8-sig")
            # Align columns: preserve existing order and add any new columns at the end
            existing_cols = list(df_existing.columns)
            new_extra_cols = [c for c in df_new.columns if c not in existing_cols]
            all_cols = existing_cols + new_extra_cols
            df_existing = df_existing.reindex(columns=all_cols)
            df_new_aligned = df_new.reindex(columns=all_cols)
            df_merged = pd.concat([df_existing, df_new_aligned], ignore_index=True)
            print(f"Appended {len(df_new_aligned)} new rows to existing {len(df_existing)} rows.")
        except Exception as e:
            # Fallback: if existing cannot be read, just use new data
            df_merged = df_new
            print(f"Warning: could not read existing merged CSV ({e}); using new data only.")
    else:
        df_merged = df_new

    # Optional sorting based on date/datetime; default preserves original order
    if args.sort != "none":
        try:
            # Normalize common time string variants like:
            # "Sun Dec 07 2025 23:00:00 GMT+0800 (Malaysia Time)"
            def _normalize_time_str(s: str) -> str:
                if not isinstance(s, str):
                    return s
                t = s.strip()
                # Drop trailing locale name in parentheses
                if t.endswith(")") and "(" in t:
                    t = t[: t.rfind("(")].strip()
                # Convert "GMT+0800" to "+0800" for offset parsing
                t = t.replace("GMT+", "+").replace("GMT-", "-")
                return t

            norm_time = df_merged["time"].map(_normalize_time_str)
            dt = pd.to_datetime(norm_time, errors="coerce")
            ascending = args.order == "asc"
            if args.sort == "date":
                # Sort only by calendar date, keep intra-day order stable
                sort_key = dt.dt.date
            else:  # datetime
                sort_key = dt
            df_merged = (
                df_merged.assign(_sort_key=sort_key)
                .sort_values(by="_sort_key", ascending=ascending, kind="stable")
                .drop(columns=["_sort_key"])
            )
        except Exception:
            # If parsing fails, keep original order
            pass

    df_merged.to_csv(out_path, index=False)
    print(f"\nUpdated merged CSV: {out_path}")
    # Show a quick preview
    with pd.option_context("display.width", 200, "display.max_columns", None):
        print(df_merged.head())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())