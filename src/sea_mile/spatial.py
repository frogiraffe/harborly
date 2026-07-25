"""Spatial indexing and nearest-neighbour queries for port registry records."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import Any

import numpy as np
import pandas as pd

from sea_mile.geo import _EARTH_RADIUS_NMI

try:
    from scipy.spatial import cKDTree
except ImportError:  # pragma: no cover - exercised only without the optional extra
    cKDTree = None  # type: ignore[assignment, misc]


@dataclass(frozen=True, slots=True)
class SpatialMatch:
    """A registry record selected by a nearest-neighbour query."""

    registry_id: str
    distance_nmi: float


@dataclass(frozen=True, slots=True)
class _CoordinateIndex:
    registry_id: np.ndarray
    country_code: np.ndarray
    provider_priority: np.ndarray
    lat_rad: np.ndarray
    lon_rad: np.ndarray
    cartesian: np.ndarray


class PortSpatialIndex:
    """Immutable spatial view over the coordinate-bearing registry records."""

    def __init__(
        self,
        registry: pd.DataFrame,
        *,
        provider_priority: dict[str, int],
    ) -> None:
        self._index = self._build_index(registry, provider_priority)

    @cached_property
    def _kdtree(self) -> Any:
        if cKDTree is None or self._index.registry_id.shape[0] == 0:
            return None
        return cKDTree(self._index.cartesian)

    def nearest(
        self,
        latitude: float,
        longitude: float,
        *,
        country_code: str | None,
        limit: int,
        max_distance_nmi: float | None,
    ) -> list[SpatialMatch]:
        """Return stable distance-ranked registry IDs near a coordinate."""

        index = self._index
        positions = self._candidate_positions(latitude, longitude, country_code, limit)
        if positions.size == 0:
            return []

        lat1 = np.radians(latitude)
        lon1 = np.radians(longitude)
        lat2 = index.lat_rad[positions]
        lon2 = index.lon_rad[positions]
        haversine = (
            np.sin((lat2 - lat1) / 2) ** 2
            + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
        )
        distances = (
            _EARTH_RADIUS_NMI * 2 * np.arcsin(np.sqrt(np.clip(haversine, 0.0, 1.0)))
        )
        registry_ids = index.registry_id[positions]
        priorities = index.provider_priority[positions]

        if max_distance_nmi is not None:
            within = distances <= max_distance_nmi
            distances = distances[within]
            registry_ids = registry_ids[within]
            priorities = priorities[within]
        if distances.size == 0:
            return []

        # lexsort reads keys last-first: distance, then provider, then ID.
        order = np.lexsort((registry_ids, priorities, distances))[:limit]
        return [
            SpatialMatch(str(registry_ids[position]), float(distances[position]))
            for position in order
        ]

    def _candidate_positions(
        self,
        latitude: float,
        longitude: float,
        country_code: str | None,
        limit: int,
    ) -> np.ndarray:
        index = self._index
        size = index.registry_id.shape[0]
        if self._kdtree is not None and country_code is None:
            point = _EARTH_RADIUS_NMI * np.array(
                [
                    np.cos(np.radians(latitude)) * np.cos(np.radians(longitude)),
                    np.cos(np.radians(latitude)) * np.sin(np.radians(longitude)),
                    np.sin(np.radians(latitude)),
                ]
            )
            count = min(limit + 8, size)
            if count == 0:
                return np.array([], dtype=np.intp)
            distances, found = self._kdtree.query(point, k=count)
            distances = np.atleast_1d(distances)
            found = np.atleast_1d(found)
            if count < size:
                tied = self._kdtree.query_ball_point(
                    point, r=float(distances[-1]) + 1e-6
                )
                if len(tied) > found.size:
                    found = np.asarray(tied, dtype=np.intp)
            return found

        mask = np.ones(size, dtype=bool)
        if country_code:
            mask &= index.country_code == country_code.upper()
        return np.nonzero(mask)[0]

    @staticmethod
    def _build_index(
        registry: pd.DataFrame, provider_priority: dict[str, int]
    ) -> _CoordinateIndex:
        frame = registry.dropna(subset=["latitude", "longitude"])
        latitude = frame["latitude"].to_numpy(dtype=float)
        longitude = frame["longitude"].to_numpy(dtype=float)
        valid = (
            np.isfinite(latitude)
            & np.isfinite(longitude)
            & (np.abs(latitude) <= 90)
            & (np.abs(longitude) <= 180)
            & ~((latitude == 0.0) & (longitude == 0.0))
        )
        frame = frame[valid]
        priorities = (
            frame["provider"].map(provider_priority).fillna(99).to_numpy(dtype=float)
        )
        lat_rad = np.radians(frame["latitude"].to_numpy(dtype=float))
        lon_rad = np.radians(frame["longitude"].to_numpy(dtype=float))
        cartesian = _EARTH_RADIUS_NMI * np.column_stack(
            (
                np.cos(lat_rad) * np.cos(lon_rad),
                np.cos(lat_rad) * np.sin(lon_rad),
                np.sin(lat_rad),
            )
        )
        return _CoordinateIndex(
            registry_id=frame["registry_id"].to_numpy(),
            country_code=frame["country_code"].to_numpy(),
            provider_priority=priorities,
            lat_rad=lat_rad,
            lon_rad=lon_rad,
            cartesian=cartesian,
        )
