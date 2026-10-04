"""SQLite storage: append-only snapshot table, the backbone for tracking."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from pma.models import MarketSnapshot

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    ts TEXT NOT NULL,
    platform TEXT NOT NULL,
    market_id TEXT NOT NULL,
    question TEXT NOT NULL,
    prob REAL,
    bid REAL,
    ask REAL,
    volume_24h REAL,
    volume_native REAL,
    liquidity REAL,
    end_date TEXT,
    PRIMARY KEY (ts, platform, market_id)
);
CREATE INDEX IF NOT EXISTS idx_snapshots_market
    ON snapshots (platform, market_id, ts);
"""

VALUE_FIELDS = {"prob", "volume_24h", "liquidity"}


class Store:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.executescript(SCHEMA)

    def upsert(self, snaps: Iterable[MarketSnapshot]) -> int:
        rows = [s.row() for s in snaps]
        self._conn.executemany(
            "INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        self._conn.commit()
        return len(rows)

    def latest_snapshots(self, platform: Optional[str] = None) -> List[MarketSnapshot]:
        """Most recent snapshot per market (optionally filtered by platform)."""
        sql = """
            SELECT s.* FROM snapshots s
            JOIN (SELECT platform, market_id, MAX(ts) AS max_ts
                  FROM snapshots GROUP BY platform, market_id) m
              ON s.platform = m.platform AND s.market_id = m.market_id
             AND s.ts = m.max_ts
        """
        params: tuple = ()
        if platform:
            sql += " WHERE s.platform = ?"
            params = (platform,)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._to_snapshot(r) for r in rows]

    def history(self, platform: str, market_id: str, field: str = "prob",
                limit: int = 2000) -> List[Tuple[str, Optional[float]]]:
        """Chronological (ts, value) series for one market."""
        if field not in VALUE_FIELDS:
            raise ValueError(f"unsupported field: {field}")
        rows = self._conn.execute(
            f"SELECT ts, {field} FROM snapshots "
            f"WHERE platform=? AND market_id=? AND {field} IS NOT NULL "
            f"ORDER BY ts",
            (platform, market_id),
        ).fetchall()
        return rows[-limit:]

    @staticmethod
    def _to_snapshot(r) -> MarketSnapshot:
        return MarketSnapshot(
            ts=r[0], platform=r[1], market_id=r[2], question=r[3],
            prob=r[4], bid=r[5], ask=r[6], volume_24h=r[7],
            volume_native=r[8], liquidity=r[9], end_date=r[10],
        )

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
