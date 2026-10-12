"""How the user travelled between consecutive photos on a trip map.

A trip is the located photos of one view (an album, All photos, Unsorted or the
recycle bin) in capture order; a *segment* joins two consecutive photos. The
user can tag a segment with how they moved (car, plane, ...). Tags are stored
per view and per ordered photo pair, so they survive restarts, and are
reconciled every time the map is opened against the photos actually plotted:

- a segment whose two photos are still consecutive keeps its mode;
- when a photo is inserted between two photos, both new segments inherit the
  mode of the segment they split;
- when a photo is removed (deleted, recycled, moved out of the album, or no
  longer located), every segment touching it loses its mode, and the segment
  that now joins its neighbours starts untagged.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

# Allowed travel modes, in the order the map offers them.
TRIP_MODES = ("car", "plane", "foot", "bike", "tuktuk", "bus", "taxi", "boat")
TRIP_SCOPE_MAX_LENGTH = 64


@dataclass(frozen=True)
class TripSegment:
    """The travel mode of one segment between two consecutive photos."""

    from_asset_id: int
    to_asset_id: int
    mode: str


def trip_check_scope(scope: str) -> str:
    """Validate a view scope key such as ``all`` or ``album:3``.

    scope: the map's view key.
    Returns the scope. Raises ``ValueError`` when it is empty or unreasonable.
    """
    if not isinstance(scope, str) or not scope.strip() or len(scope) > TRIP_SCOPE_MAX_LENGTH:
        raise ValueError("Trip scope must be a short, non-empty string")
    return scope


def trip_check_ids(asset_ids: list[int]) -> list[int]:
    """Validate an ordered list of distinct positive asset ids."""
    if not isinstance(asset_ids, list) or any(
        type(value) is not int or value <= 0 for value in asset_ids
    ):
        raise ValueError("Trip asset ids must be positive integers")
    if len(set(asset_ids)) != len(asset_ids):
        raise ValueError("Trip asset ids must be distinct")
    return asset_ids


def trip_stored(connection: sqlite3.Connection, scope: str) -> dict[tuple[int, int], str]:
    """Return every stored segment mode of one view."""
    rows = connection.execute(
        "SELECT from_asset_id, to_asset_id, mode FROM trip_segments WHERE scope = ?",
        (scope,),
    ).fetchall()
    return {(int(row[0]), int(row[1])): str(row[2]) for row in rows}


def trip_reconcile(
    connection: sqlite3.Connection, scope: str, asset_ids: list[int]
) -> list[TripSegment]:
    """Bring a view's stored modes in line with the photos now on its map.

    connection: an open catalog connection; the caller commits.
    scope: the view key.
    asset_ids: the plotted photos, in capture order.
    Returns the modes of the current consecutive segments that have one.
    """
    scope = trip_check_scope(scope)
    ids = trip_check_ids(asset_ids)
    position = {asset_id: index for index, asset_id in enumerate(ids)}
    current = set(zip(ids, ids[1:], strict=False))
    stored = trip_stored(connection, scope)
    result = {pair: mode for pair, mode in stored.items() if pair in current}
    for pair, mode in stored.items():
        if pair in current:
            continue
        connection.execute(
            "DELETE FROM trip_segments WHERE scope = ? AND from_asset_id = ? AND to_asset_id = ?",
            (scope, *pair),
        )
        start, end = position.get(pair[0]), position.get(pair[1])
        if start is None or end is None or start >= end:
            # A photo of this segment left the view (or the order changed):
            # the user's choice no longer describes any real leg of the trip.
            continue
        # Photos were inserted inside this segment: every leg it now spans was
        # travelled the same way.
        for index in range(start, end):
            leg = (ids[index], ids[index + 1])
            if leg not in result:
                result[leg] = mode
                connection.execute(
                    "INSERT OR REPLACE INTO trip_segments"
                    "(scope, from_asset_id, to_asset_id, mode) VALUES (?, ?, ?, ?)",
                    (scope, *leg, mode),
                )
    return [
        TripSegment(from_id, to_id, result[(from_id, to_id)])
        for from_id, to_id in zip(ids, ids[1:], strict=False)
        if (from_id, to_id) in result
    ]


def trip_set_mode(
    connection: sqlite3.Connection,
    scope: str,
    from_asset_id: int,
    to_asset_id: int,
    mode: str | None,
) -> TripSegment | None:
    """Store (or clear) how the user travelled along one segment.

    connection: an open catalog connection; the caller commits.
    scope: the view key.
    from_asset_id: the earlier photo of the segment.
    to_asset_id: the later photo.
    mode: one of ``TRIP_MODES``, or None to clear the segment.
    Returns the stored segment, or None when it was cleared.
    """
    scope = trip_check_scope(scope)
    trip_check_ids([from_asset_id, to_asset_id])
    if mode is not None and mode not in TRIP_MODES:
        raise ValueError(f"Unknown travel mode: {mode}")
    for asset_id in (from_asset_id, to_asset_id):
        if connection.execute("SELECT 1 FROM assets WHERE id = ?", (asset_id,)).fetchone() is None:
            raise ValueError(f"Unknown asset: {asset_id}")
    if mode is None:
        connection.execute(
            "DELETE FROM trip_segments WHERE scope = ? AND from_asset_id = ? AND to_asset_id = ?",
            (scope, from_asset_id, to_asset_id),
        )
        return None
    connection.execute(
        "INSERT OR REPLACE INTO trip_segments(scope, from_asset_id, to_asset_id, mode)"
        " VALUES (?, ?, ?, ?)",
        (scope, from_asset_id, to_asset_id, mode),
    )
    return TripSegment(from_asset_id, to_asset_id, mode)
