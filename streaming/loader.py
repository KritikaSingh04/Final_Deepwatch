"""Telemetry loading with tolerant schema mapping and validation.

Accepts any correctly formatted CSV/XLSX — no dependence on filenames.
The loader:

* discovers the time column and the inlet/outlet pressure columns
  case-insensitively (exact dev-schema headers are NOT required);
* accepts relative time in milliseconds or seconds, or wall-clock
  timestamps (converted to relative seconds);
* drops malformed rows (non-numeric / missing values) and sorts by time
  if the file is out of order, reporting both as warnings;
* quarantines the Status Flag column (if present) so it can NEVER reach
  the analytics engine — carried for display only, and never required;
* returns a `validation` summary the UI shows on load ("Dataset loaded",
  sample count, sampling interval, channels detected, flag ignored).

Raises LoaderError with a human-readable message when a required channel
cannot be identified.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

MIN_SAMPLES = 20


class LoaderError(ValueError):
    """Raised when a file cannot be interpreted as pipeline telemetry."""


class MultiSheetWorkbook(LoaderError):
    """Raised when an XLSX holds several valid telemetry sheets and no
    sheet was specified — the caller must ask the user to choose one.
    Worksheets are NEVER silently chosen or concatenated."""

    def __init__(self, sheets: list[str]):
        self.sheets = sheets
        super().__init__(
            f"{len(sheets)} evaluation scenarios detected "
            f"({', '.join(sheets)}) — select a scenario to begin")


@dataclass
class TelemetrySet:
    name: str
    times_s: list[float]
    p_in: list[float]
    p_out: list[float]
    sheet: Optional[str] = None             # worksheet name for XLSX workbooks
    ref_flags: Optional[list[str]] = None   # display-only; not fed to the engine
    columns: dict = field(default_factory=dict)
    validation: dict = field(default_factory=dict)

    def __len__(self):
        return len(self.times_s)

    @property
    def label(self) -> str:
        return f"{self.name} › {self.sheet}" if self.sheet else self.name

    @property
    def sample_dt(self) -> float:
        if len(self.times_s) < 2:
            return 0.1
        diffs = sorted(self.times_s[i + 1] - self.times_s[i]
                       for i in range(min(200, len(self.times_s) - 1)))
        return diffs[len(diffs) // 2]


def inspect_sheets(path: str) -> list[dict]:
    """List worksheets of an XLSX with a validity verdict per sheet.

    A sheet is valid telemetry when a time channel and both pressure
    channels can be identified in its header row (non-data sheets such as
    Read_Me fail this and are ignored). CSVs report a single entry."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".xlsx", ".xls"):
        return [{"sheet": None, "valid": True, "reason": "csv"}]
    try:
        xl = pd.ExcelFile(path)
    except Exception as exc:
        raise LoaderError(f"could not read workbook: {exc}") from exc
    out = []
    for sheet in xl.sheet_names:
        try:
            head = xl.parse(sheet, nrows=8)
            head.columns = [str(c).strip() for c in head.columns]
            _find_time_column(head)
            ok = (_find_column(head, ["inlet", "press"]) or
                  _find_column(head, ["inlet"])) is not None and \
                 (_find_column(head, ["outlet", "press"]) or
                  _find_column(head, ["outlet"])) is not None
            out.append({"sheet": sheet, "valid": bool(ok),
                        "reason": None if ok else "pressure channels not found"})
        except Exception as exc:
            out.append({"sheet": sheet, "valid": False, "reason": str(exc)})
    return out


def load(path: str, sheet: Optional[str] = None) -> TelemetrySet:
    """Load one telemetry set. For XLSX workbooks a specific worksheet may
    be given; with several valid sheets and none specified,
    MultiSheetWorkbook is raised — sheets are never concatenated."""
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".xlsx", ".xls"):
            xl = pd.ExcelFile(path)
            if sheet is not None:
                if sheet not in xl.sheet_names:
                    raise LoaderError(
                        f"worksheet {sheet!r} not found — workbook has: "
                        f"{xl.sheet_names}")
            else:
                valid = [s["sheet"] for s in inspect_sheets(path) if s["valid"]]
                if not valid:
                    raise LoaderError(
                        "no valid telemetry worksheet found — telemetry "
                        "sheets need time + inlet/outlet pressure columns")
                if len(valid) > 1:
                    raise MultiSheetWorkbook(valid)
                sheet = valid[0]
            df = xl.parse(sheet)
        else:
            df = pd.read_csv(path, encoding="utf-8-sig")
    except LoaderError:
        raise
    except Exception as exc:
        raise LoaderError(f"could not read file: {exc}") from exc
    if df.empty:
        raise LoaderError("file contains no data rows"
                          + (f" (sheet {sheet!r})" if sheet else ""))
    df.columns = [str(c).strip() for c in df.columns]

    time_col, unit = _find_time_column(df)
    in_col = (_find_column(df, ["inlet", "press"])
              or _find_column(df, ["inlet"])
              or _find_column(df, ["upstream", "press"]))
    out_col = (_find_column(df, ["outlet", "press"])
               or _find_column(df, ["outlet"])
               or _find_column(df, ["downstream", "press"]))
    if in_col is None:
        raise LoaderError(
            f"no inlet-pressure column found — headers seen: {list(df.columns)}")
    if out_col is None:
        raise LoaderError(
            f"no outlet-pressure column found — headers seen: {list(df.columns)}")
    flag_col = (_find_column(df, ["status", "flag"])
                or _find_column(df, ["flag"]))

    if unit == "ms":
        times = pd.to_numeric(df[time_col], errors="coerce") / 1000.0
    elif unit == "s":
        times = pd.to_numeric(df[time_col], errors="coerce")
    else:  # wall clock
        stamps = pd.to_datetime(df[time_col].astype(str), errors="coerce")
        times = (stamps - stamps.min()).dt.total_seconds()

    p_in = pd.to_numeric(df[in_col], errors="coerce")
    p_out = pd.to_numeric(df[out_col], errors="coerce")
    mask = times.notna() & p_in.notna() & p_out.notna()
    dropped = int((~mask).sum())

    sub = pd.DataFrame({"t": times[mask], "pi": p_in[mask], "po": p_out[mask]})
    if flag_col is not None:
        sub["fl"] = df.loc[mask, flag_col].astype(str)

    warnings: list[str] = []
    if dropped:
        warnings.append(f"{dropped} malformed row(s) dropped")
    if not sub["t"].is_monotonic_increasing:
        sub = sub.sort_values("t", kind="stable")
        warnings.append("rows were out of time order — sorted by timestamp")
    dup = int(sub["t"].duplicated().sum())
    if dup:
        sub = sub[~sub["t"].duplicated()]
        warnings.append(f"{dup} duplicate timestamp(s) dropped")
    if len(sub) < MIN_SAMPLES:
        raise LoaderError(
            f"only {len(sub)} usable samples — need at least {MIN_SAMPLES}")

    tel = TelemetrySet(
        name=os.path.basename(path),
        sheet=sheet,
        times_s=[round(float(t), 4) for t in sub["t"]],
        p_in=[float(v) for v in sub["pi"]],
        p_out=[float(v) for v in sub["po"]],
        ref_flags=sub["fl"].tolist() if flag_col is not None else None,
        columns={"time": time_col, "inlet": in_col, "outlet": out_col,
                 "status_flag_present": flag_col is not None,
                 "time_unit": unit},
    )

    gaps = sorted(tel.times_s[i + 1] - tel.times_s[i]
                  for i in range(len(tel.times_s) - 1))
    dt_med = gaps[len(gaps) // 2] if gaps else 0.1
    uniform = bool(gaps) and (gaps[-1] - gaps[0]) <= max(0.25 * dt_med, 1e-4)
    if gaps and not uniform:
        warnings.append(
            f"non-uniform sampling (gaps {gaps[0]*1000:.0f}–{gaps[-1]*1000:.0f} ms); "
            f"engine uses measured spacing")

    tel.validation = {
        "samples": len(tel),
        "sheet": sheet,
        "sample_dt_ms": round(dt_med * 1000, 1),
        "duration_s": round(tel.times_s[-1] - tel.times_s[0], 2),
        "channels": {"time": time_col, "inlet": in_col, "outlet": out_col},
        "status_flag_present": flag_col is not None,
        "status_flag_column": flag_col,
        "dropped_rows": dropped,
        "uniform_sampling": uniform,
        "warnings": warnings,
    }
    return tel


def _find_time_column(df: pd.DataFrame):
    lower = {c.lower(): c for c in df.columns}
    # prefer an explicit relative-time column
    for lc, c in lower.items():
        if "relative" in lc and "time" in lc:
            return c, ("ms" if "ms" in lc or _looks_like_ms(df[c]) else "s")
    for lc, c in lower.items():
        if ("time" in lc and "stamp" not in lc) or lc in ("t", "t (s)", "t(s)"):
            return c, ("ms" if "ms" in lc or _looks_like_ms(df[c]) else "s")
    for lc, c in lower.items():
        if "timestamp" in lc or "date" in lc:
            return c, "wall"
    raise LoaderError(
        f"no time/timestamp column found — headers seen: {list(df.columns)}")


def _looks_like_ms(series) -> bool:
    vals = pd.to_numeric(series, errors="coerce").dropna()
    if len(vals) < 2:
        return False
    step = float(vals.iloc[1] - vals.iloc[0])
    return abs(step) >= 5.0  # 100 ms sampling => step of ~100 in ms units


def _find_column(df: pd.DataFrame, keywords: list[str]):
    for c in df.columns:
        lc = c.lower()
        if all(k in lc for k in keywords):
            return c
    return None
