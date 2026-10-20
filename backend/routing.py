"""Directed OSM graph. Snaps are explicit unverified connectors, never fake paths."""

import math
import numpy as np
from scipy.sparse import load_npz
from scipy.sparse.csgraph import connected_components, dijkstra
from scipy.spatial import cKDTree
from .settings import DATA


# Unverified connector from a point to the walking network. Large buildings (malls,
# monuments) put their centre ~80-130 m from the nearest street; the connector time
# is added to the route at 75 m/min and labelled as unverified. The client may choose
# a radius within [MIN_SNAP_M, MAX_ALLOWED_SNAP_M].
MAX_SNAP_M = 150
MIN_SNAP_M = 30
MAX_ALLOWED_SNAP_M = 300


def meters(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 6371000 * 2 * math.asin(min(1, math.sqrt(h)))


class Router:
    def __init__(self):
        self.coords = np.load(DATA / "graph" / "coordinates.npy")
        self.xy = np.column_stack(
            (
                self.coords[:, 1] * math.cos(math.radians(51.13)) * 111320,
                self.coords[:, 0] * 111320,
            )
        )
        self.graph = load_npz(DATA / "graph" / "walking_seconds.npz")
        self.no_steps = load_npz(DATA / "graph" / "no_steps_seconds.npz")
        # Snap only to the main walking network: indoor or unconnected OSM fragments
        # (e.g. paths inside a mall) would otherwise trap a start with no reachable places.
        _, labels = connected_components(self.graph, directed=True, connection="weak")
        self.main_nodes = np.flatnonzero(labels == np.bincount(labels).argmax())
        self.tree = cKDTree(self.xy[self.main_nodes])

    def snap(self, point):
        lat, lon = point
        _, i = self.tree.query(
            (lon * math.cos(math.radians(51.13)) * 111320, lat * 111320)
        )
        node = int(self.main_nodes[int(i)])
        return node, meters(point, self.coords[node])

    def paths(self, origin, no_steps=False, max_minutes=180, max_snap_m=MAX_SNAP_M):
        node, snap = self.snap(origin)
        if snap > max_snap_m:
            return None
        times, pred = dijkstra(
            self.no_steps if no_steps else self.graph,
            directed=True,
            indices=node,
            return_predecessors=True,
            limit=max_minutes * 60,
        )
        # The radius travels with the state so destinations use the same limit.
        return node, snap, times, pred, max_snap_m

    def route(self, origin, destination, no_steps=False, state=None):
        state = state if state is not None else self.paths(origin, no_steps)
        if state is None:
            return None
        start, osnap, times, pred, max_snap_m = state
        target, dsnap = self.snap(destination)
        if dsnap > max_snap_m or not np.isfinite(times[target]):
            return None
        path = [target]
        cur = target
        while cur != start:
            cur = int(pred[cur])
            if cur < 0:
                return None
            path.append(cur)
        coords = self.coords[path[::-1]].tolist()
        # Include time allowance for the unverified associations, separately labelled.
        graph_minutes = float(times[target]) / 60
        return {
            "geometry": coords,
            "network_distance_m": round(
                sum(meters(a, b) for a, b in zip(coords, coords[1:])), 1
            ),
            "network_duration_min": round(graph_minutes, 1),
            "duration_min": round(graph_minutes + (osnap + dsnap) / 75, 1),
            "origin_snap_m": round(osnap, 1),
            "destination_snap_m": round(dsnap, 1),
            "door_to_door_verified": False,
            "wheelchair_accessibility_verified": False,
            "steps_excluded": no_steps,
            "warnings": [
                "Привязки к дорожкам не проверены. Последний участок до входа уточните на месте.",
                "Ограничения и состояние дорожек взяты из снимка OSM, без проверки в реальном времени.",
            ],
            "source_url": "https://www.openstreetmap.org/copyright",
        }
