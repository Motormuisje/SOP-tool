"""
S&OP Planning Engine - Cycle Manager
Saves and loads previous cycle planning results so that
Month-over-Month comparisons can be computed on the next run.

Storage format: Parquet (compact, typed, fast).
"""

import hashlib
import json
import os
import tempfile
import pandas as pd
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


class CycleManager:
    """Persist and retrieve the previous planning cycle's DataFrame."""

    DEFAULT_FILENAME = "previous_cycle_values.parquet"
    META_FILENAME = "previous_cycle_meta.json"

    def __init__(self, storage_dir: str):
        self.storage_dir = Path(storage_dir)
        self._path = self.storage_dir / self.DEFAULT_FILENAME
        self._meta_path = self.storage_dir / self.META_FILENAME

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def has_previous_cycle(self) -> bool:
        """Return True if a previous-cycle snapshot exists on disk."""
        return self._path.is_file()

    def load_previous_cycle(self) -> pd.DataFrame:
        """Load the previous cycle DataFrame.

        Returns an empty DataFrame if the file is missing or corrupt.
        """
        if not self.has_previous_cycle():
            return pd.DataFrame()
        try:
            return pd.read_parquet(self._path)
        except Exception as exc:
            print(f"  Warning: could not read previous cycle ({exc}); starting fresh.")
            return pd.DataFrame()

    def save_current_as_previous(self, df: pd.DataFrame, planning_month: str = None) -> None:
        """Overwrite the previous-cycle snapshot with the current results.

        Creates the storage directory if it does not exist.
        """
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        parquet_df = df.copy()
        for column in parquet_df.columns:
            # Text columns, named by dtype instead of select_dtypes("object"):
            # pandas 3 gives text its own dtype and still lets "object" select
            # it, but warns that pandas 4 will stop doing so.
            dtype = parquet_df[column].dtype
            if not (pd.api.types.is_object_dtype(dtype) or isinstance(dtype, pd.StringDtype)):
                continue
            parquet_df[column] = parquet_df[column].map(
                lambda value: None
                if pd.api.types.is_scalar(value) and pd.isna(value)
                else str(value)
            )
        # Write beside the target under a unique name and swap in: a reader
        # (or a crash) halfway through a direct write saw a truncated parquet,
        # reported as "no previous cycle" (BUGS.md L7). Unique names keep two
        # overlapping writers from replacing each other's temporary files.
        # Two files cannot be swapped as one, so the metadata names the
        # snapshot it belongs to (sha256) and load_metadata() ignores metadata
        # that does not match the snapshot on disk.
        fd, tmp_name = tempfile.mkstemp(prefix=self._path.name + ".", suffix=".tmp", dir=self.storage_dir)
        os.close(fd)
        tmp_path = Path(tmp_name)
        fd, tmp_meta_name = tempfile.mkstemp(prefix=self._meta_path.name + ".", suffix=".tmp", dir=self.storage_dir)
        os.close(fd)
        tmp_meta_path = Path(tmp_meta_name)
        try:
            parquet_df.to_parquet(tmp_path, index=False)
            meta = {
                "planning_month": planning_month or "",
                "snapshot_sha256": _sha256(tmp_path),
            }
            with open(tmp_meta_path, "w") as f:
                json.dump(meta, f)
            os.replace(tmp_path, self._path)
            os.replace(tmp_meta_path, self._meta_path)
        finally:
            for leftover in (tmp_path, tmp_meta_path):
                if leftover.is_file():
                    leftover.unlink()
        print(f"  Previous-cycle snapshot saved -> {self._path}")

    def load_metadata(self) -> dict:
        """Return metadata dict for the stored previous cycle (e.g. planning_month)."""
        if not self._meta_path.is_file():
            return {}
        try:
            with open(self._meta_path) as f:
                meta = json.load(f)
        except Exception:
            return {}
        expected = meta.get("snapshot_sha256") if isinstance(meta, dict) else None
        try:
            matches = (not expected) or (self._path.is_file() and _sha256(self._path) == expected)
        except OSError:
            matches = False  # snapshot replaced or removed while we read it
        if not matches:
            # Metadata of another snapshot (a write in progress, or a crash
            # between the two swaps): unknown is honest, a wrong month is not.
            return {}
        return meta

    def clear(self) -> None:
        """Remove the stored snapshot (useful for testing)."""
        if self._path.is_file():
            self._path.unlink()
        if self._meta_path.is_file():
            self._meta_path.unlink()
