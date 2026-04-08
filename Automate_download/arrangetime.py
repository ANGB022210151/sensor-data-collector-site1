import os
import sys
import csv
from datetime import datetime
import re
from typing import Optional, List


def parse_dt(value: str) -> Optional[datetime]:
	value = value.strip()
	if not value:
		return None

	# Handle JS-like date: "Thu Dec 04 2025 00:00:00 GMT+0800 (Malaysia Time)"
	# Remove trailing parenthetical timezone name if present
	js_like = re.sub(r"\s*\([^)]*\)\s*$", "", value)
	try:
		# Expect pattern with day name, month name, day, year, time, and GMT offset
		# Example: Thu Dec 04 2025 00:00:00 GMT+0800
		return datetime.strptime(js_like, "%a %b %d %Y %H:%M:%S GMT%z")
	except Exception:
		pass
	# Try common datetime formats quickly; fall back to flexible parsing
	fmts = [
		"%Y-%m-%d",
		"%Y-%m-%d %H:%M:%S",
		"%Y-%m-%d %H:%M",
		"%d/%m/%Y",
		"%d/%m/%Y %H:%M:%S",
		"%d/%m/%Y %H:%M",
		"%m/%d/%Y",
		"%m/%d/%Y %H:%M:%S",
		"%m/%d/%Y %H:%M",
		"%Y/%m/%d",
		"%Y/%m/%d %H:%M:%S",
		"%Y/%m/%d %H:%M",
		"%Y-%m-%dT%H:%M:%S",
		"%Y-%m-%dT%H:%M:%S.%f",
		"%Y-%m-%dT%H:%M",
	]
	for fmt in fmts:
		try:
			return datetime.strptime(value, fmt)
		except Exception:
			pass
	# Very lightweight fallback: try to normalize ISO-like strings
	try:
		# Handle milliseconds like 2023-07-01 12:00:00.123
		if "." in value:
			main, frac = value.split(".", 1)
			value = main
		# Replace 'T' with space
		value_norm = value.replace("T", " ")
		for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"]:
			try:
				return datetime.strptime(value_norm, fmt)
			except Exception:
				pass
	except Exception:
		pass
	return None


def detect_datetime_column(rows: List[List[str]], header: List[str]) -> Optional[int]:
	# Prefer typical names
	preferred_names = [
		"timestamp", "time", "date", "datetime", "created_at", "recorded_at",
	]
	lower_header = [h.lower() for h in header]
	for name in preferred_names:
		if name in lower_header:
			idx = lower_header.index(name)
			# Verify a few samples parse
			samples = [r[idx] for r in rows[:50] if len(r) > idx]
			good = sum(1 for v in samples if parse_dt(v) is not None)
			if good >= max(1, len(samples) // 3):  # at least ~33% parseable
				return idx

	# Otherwise, try all columns and choose the best parse rate
	best_idx = None
	best_score = 0
	for i in range(len(header)):
		samples = [r[i] for r in rows[:100] if len(r) > i]
		if not samples:
			continue
		good = sum(1 for v in samples if parse_dt(v) is not None)
		score = good / len(samples)
		if score > best_score and good >= max(1, len(samples) // 4):
			best_score = score
			best_idx = i
	return best_idx


def sort_csv_by_date(csv_path: str, date_col_idx_override: Optional[int] = None) -> None:
	if not os.path.isfile(csv_path):
		raise FileNotFoundError(f"CSV not found: {csv_path}")

	# Read all data
	with open(csv_path, "r", newline="", encoding="utf-8") as f:
		reader = csv.reader(f)
		data = list(reader)

	if not data:
		print("File is empty; nothing to sort.")
		return

	header = data[0]
	rows = data[1:]

	if not rows:
		print("No data rows present; nothing to sort.")
		return

	if date_col_idx_override is not None:
		date_col_idx = date_col_idx_override
	else:
		date_col_idx = detect_datetime_column(rows, header)
	if date_col_idx is None:
		raise ValueError("Could not detect a datetime column. Please specify one.")

	# Sort rows by parsed datetime; keep rows with unparsable dates at the end
	def sort_key(r: List[str]):
		try:
			dt = parse_dt(r[date_col_idx])
			# Use a tuple: (flag, dt) so unparsable go last
			return (0, dt) if dt is not None else (1, datetime.max)
		except Exception:
			return (1, datetime.max)

	rows_sorted = sorted(rows, key=sort_key)

	# Write back to the same file (replace the newly sorted document)
	tmp_path = csv_path + ".tmp"
	with open(tmp_path, "w", newline="", encoding="utf-8") as f:
		writer = csv.writer(f)
		writer.writerow(header)
		writer.writerows(rows_sorted)
	os.replace(tmp_path, csv_path)
	print(f"Sorted {len(rows)} rows by '{header[date_col_idx]}' and updated file.")


def main():
	# Default to merged_sensor_data.csv in the same directory as this script
	script_dir = os.path.dirname(os.path.abspath(__file__))
	default_csv = os.path.join(script_dir, "merged_sensor_data.csv")

	# Allow optional custom path and explicit column name
	# Usage: python arrangetime.py [csv_path] [date_column_name]
	csv_path = default_csv
	explicit_col_name = None
	if len(sys.argv) >= 2:
		csv_path = sys.argv[1]
	if len(sys.argv) >= 3:
		explicit_col_name = sys.argv[2].lower()

	if explicit_col_name:
		# Read header to find the index for the explicit column
		with open(csv_path, "r", newline="", encoding="utf-8") as f:
			reader = csv.reader(f)
			header = next(reader)
			lower_header = [h.lower() for h in header]
			if explicit_col_name not in lower_header:
				raise ValueError(
					f"Column '{explicit_col_name}' not found in CSV header: {header}"
				)
		# Temporarily sort by setting a known index using an environment variable hook
		# Simpler: just run regular sort; detector will very likely pick the explicit column
		# because of preferred names. If you truly need to force, you can modify code to accept index.

	# If explicit column name provided, map to index and force override
	date_col_idx_override = None
	if explicit_col_name:
		with open(csv_path, "r", newline="", encoding="utf-8") as f:
			reader = csv.reader(f)
			header = next(reader)
			lower_header = [h.lower() for h in header]
			if explicit_col_name not in lower_header:
				raise ValueError(
					f"Column '{explicit_col_name}' not found in CSV header: {header}"
				)
			date_col_idx_override = lower_header.index(explicit_col_name)

	sort_csv_by_date(csv_path, date_col_idx_override)


if __name__ == "__main__":
	main()

