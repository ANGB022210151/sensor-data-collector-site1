import argparse
from pathlib import Path
import shutil
import sys
import pandas as pd


def ensure_time_column(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    cols = [c.strip() for c in df.columns]
    df.columns = cols
    lower_map = {c.lower(): c for c in cols}
    for cand in ("time", "timestamp", "date time", "datetime", "date"):
        if cand in lower_map:
            orig = lower_map[cand]
            if orig != "time":
                df = df.rename(columns={orig: "time"})
            return df
    raise KeyError(
        f"No time-like column found in {source_name}. Columns: {list(df.columns)}"
    )


def read_csv(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    # Check if the CSV is empty (no rows)
    if df.empty:
        raise ValueError(f"CSV file is empty (no data rows): {path}")
    return df


def write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)


def append_preserve_columns(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    # Preserve existing column order and ignore any extra columns from new
    cols = list(existing.columns)
    new_aligned = new.reindex(columns=cols)
    merged = pd.concat([existing, new_aligned], ignore_index=True)
    
    # Remove duplicates based on 'time' column (keep first occurrence)
    if 'time' in merged.columns:
        before_count = len(merged)
        merged = merged.drop_duplicates(subset=['time'], keep='first')
        after_count = len(merged)
        if before_count != after_count:
            print(f"  Removed {before_count - after_count} duplicate rows")
    
    return merged


def sort_by_time_ascending(df: pd.DataFrame) -> pd.DataFrame:
    """Sort the dataframe by a time-like column ascending, if present.
    Tries to normalize strings like "Sun Dec 07 2025 23:00:00 GMT+0800 (Malaysia Time)".
    """
    try:
        df = ensure_time_column(df, source_name="merged")

        def _normalize_time_str(s):
            if not isinstance(s, str):
                return s
            t = s.strip()
            # Drop trailing locale name in parentheses
            if t.endswith(")") and "(" in t:
                t = t[: t.rfind("(")].strip()
            # Convert "GMT+0800" to "+0800" for offset parsing
            t = t.replace("GMT+", "+").replace("GMT-", "-")
            return t

        norm_time = df["time"].map(_normalize_time_str)
        dt = pd.to_datetime(norm_time, errors="coerce")
        df = (
            df.assign(_sort_key=dt)
            .sort_values(by="_sort_key", ascending=True, kind="stable")
            .drop(columns=["_sort_key"])
        )
    except Exception:
        # If anything fails, keep original order
        pass
    return df


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Merge the current dataset's merged_sensor_data.csv into a Combined folder.\n"
            "If Combined has no CSV, copy the file there. If exactly one CSV exists, merge and replace it."
        )
    )
    parser.add_argument(
        "--input",
        "-i",
        type=Path,
        default=Path.cwd(),
        help="Dataset folder that contains merged_sensor_data.csv (default: current directory)",
    )
    parser.add_argument(
        "--combined",
        "-c",
        type=Path,
        required=True,
        help="Combined folder path where the single CSV resides or will be created",
    )
    parser.add_argument(
        "--dataset-file",
        type=str,
        default="merged_sensor_data.csv",
        help="Filename in the input folder to merge (default: merged_sensor_data.csv)",
    )
    parser.add_argument(
        "--outfile",
        type=str,
        default="merged_sensor_data.csv",
        help="Filename to use in Combined if none exists yet (default: merged_sensor_data.csv)",
    )

    args = parser.parse_args(argv)
    input_dir: Path = args.input.resolve()
    combined_dir: Path = args.combined.resolve()

    dataset_csv = input_dir / args.dataset_file
    if not dataset_csv.is_file():
        print(f"ERROR: Dataset CSV not found: {dataset_csv}", file=sys.stderr)
        return 2

    combined_csvs = sorted(combined_dir.glob("*.csv")) if combined_dir.exists() else []

    # Filter out empty CSVs (invalid files)
    valid_combined_csvs = []
    for csv_path in combined_csvs:
        try:
            if csv_path.stat().st_size == 0:
                print(f"Warning: Removing empty CSV file: {csv_path}")
                csv_path.unlink()
                continue
            # Quick check if file has actual data rows
            test_df = pd.read_csv(csv_path, encoding="utf-8-sig", nrows=1)
            if test_df.empty:
                print(f"Warning: CSV has headers but no data, removing: {csv_path}")
                csv_path.unlink()
                continue
            valid_combined_csvs.append(csv_path)
        except Exception as e:
            print(f"Warning: Invalid CSV file {csv_path}: {e}, removing")
            try:
                csv_path.unlink()
            except Exception:
                pass
    
    combined_csvs = valid_combined_csvs

    if len(combined_csvs) == 0:
        # Nothing in Combined: copy as-is
        target = combined_dir / args.outfile
        target.parent.mkdir(parents=True, exist_ok=True)
        df_new = read_csv(dataset_csv)
        df_new = ensure_time_column(df_new, source_name=dataset_csv.name)
        df_new = sort_by_time_ascending(df_new)
        df_new.to_csv(target, index=False)
        print(f"No CSV in Combined. Wrote sorted copy {dataset_csv.name} -> {target}")
        return 0

    if len(combined_csvs) > 1:
        names = ", ".join(p.name for p in combined_csvs)
        print(
            "ERROR: Expected exactly one CSV in Combined, found multiple: " + names,
            file=sys.stderr,
        )
        return 3

    # Exactly one CSV present: merge and replace
    combined_path = combined_csvs[0]
    print(f"Merging {dataset_csv.name} into {combined_path.name} in {combined_dir}")

    df_new = read_csv(dataset_csv)
    df_combined = read_csv(combined_path)

    # Ensure both have a 'time' column for post-append sorting
    df_new = ensure_time_column(df_new, source_name=dataset_csv.name)
    df_combined = ensure_time_column(df_combined, source_name=combined_path.name)

    merged = append_preserve_columns(df_combined, df_new)
    merged = sort_by_time_ascending(merged)
    write_csv(merged, combined_path)
    print(f"Replaced Combined CSV with merged data: {combined_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
