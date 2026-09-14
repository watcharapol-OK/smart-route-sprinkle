# =====================================================================================
#  SMART ROUTE REBALANCER — PRODUCTION BUILD v3.0
#  Multi-Donor Fleet Rebalancing + High-Contrast KPI Cards & Visual Banners
#  ---------------------------------------------------------------------------------
#  requirements.txt:
#      streamlit>=1.31
#      pandas>=2.0
#      numpy>=1.24
#      folium>=0.15
#      scipy>=1.10
#      requests>=2.31
# =====================================================================================
from __future__ import annotations

import base64
import json
import math
import re
import time
from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple

import folium
import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from folium import plugins

try:
    from scipy.spatial import cKDTree
    HAS_SCIPY = True
except Exception:
    HAS_SCIPY = False

st.set_page_config(
    page_title="Smart Route Rebalancer v3.0",
    layout="wide",
    initial_sidebar_state="expanded",
)

# =====================================================================================
#  SECTION 1 — CONSTANTS & DOMAIN MODEL
# =====================================================================================
WORKING_DAYS = 6
WEEKS_PER_MONTH = 4.333
DAYS_PER_MONTH = WORKING_DAYS * WEEKS_PER_MONTH

DEFAULT_MONTHLY_CAPACITY = 4160.0
DEFAULT_DAILY_CONTROL_CAP = 156.0
DEFAULT_MAX_STOPS_PER_DAY = 90

OVERFLOW_LABEL = "ส่วนเกิน (Overflow)"

NO_TRUCK_TOKENS = {
    "", "nan", "none", "null", "-", "ไม่ระบุ", "na", "n/a",
}

OPTIMAL_MIN = 140
OPTIMAL_MAX = 155
AVOID_MIN = 121
AVOID_MAX = 139
TARGET_DAY_CAP = 148
ESCALATE_THRESHOLD = 160
ESCALATE_TARGET_MIN = 180
ESCALATE_TARGET_MAX = 190

EARTH_RADIUS_M = 6371008.8

DAY_NAMES = {0: "จันทร์", 1: "อังคาร", 2: "พุธ", 3: "พฤหัสบดี", 4: "ศุกร์", 5: "เสาร์"}
DAY_SHORT = {0: "จ", 1: "อ", 2: "พ", 3: "พฤ", 4: "ศ", 5: "ส"}

DAY_TOKENS: List[Tuple[str, int]] = [
    ("จันทร์", 0), ("อังคาร", 1), ("พฤหัสบดี", 3), ("พฤหัสฯ", 3), ("พฤหัส", 3), ("พฤ", 3),
    ("พุธ", 2), ("ศุกร์", 4), ("เสาร์", 5), ("monday", 0), ("tuesday", 1), ("wednesday", 2),
    ("thursday", 3), ("friday", 4), ("saturday", 5), ("mon", 0), ("tue", 1), ("wed", 2),
    ("thu", 3), ("fri", 4), ("sat", 5), ("จ", 0), ("อ", 1), ("พ", 2), ("ศ", 4), ("ส", 5),
]

ALL_DAYS_TOKENS = ("ทุกวัน", "จ-ส", "จันทร์-เสาร์", "จ.-ส.", "ทุกวันทำการ")

# =====================================================================================
#  SECTION 2 — PURE HELPERS
# =====================================================================================
def parse_days_from_string(val_str) -> Tuple[List[int], str]:
    raw = "" if val_str is None else str(val_str)
    val = raw.strip().lower()
    if val.lower() in NO_TRUCK_TOKENS:
        return [], "empty"

    compact = re.sub(r"\s+", "", val)
    if any(token in compact for token in ALL_DAYS_TOKENS):
        return list(range(WORKING_DAYS)), "ok"

    days = set()
    tokens = re.split(r"[,|/+\-;\s]+", val)
    for token in tokens:
        token = token.strip().strip(".")
        if not token:
            continue
        if token.isdigit():
            number = int(token)
            if 1 <= number <= WORKING_DAYS:
                days.add(number - 1)
            continue
        for name, day_index in DAY_TOKENS:
            if name in token:
                days.add(day_index)
                break

    if not days:
        return [], "unparsed"
    return sorted(days), "ok"


def format_days_to_string(days_list: Sequence[int]) -> str:
    if not days_list:
        return "ไม่ระบุ"
    days = sorted({int(d) for d in days_list if 0 <= int(d) < WORKING_DAYS})
    if not days:
        return "ไม่ระบุ"
    if len(days) == WORKING_DAYS:
        return "จ-ส"
    return ", ".join(DAY_NAMES[d] for d in days)


def format_days_short(days_list: Sequence[int]) -> str:
    if not days_list:
        return "-"
    days = sorted({int(d) for d in days_list if 0 <= int(d) < WORKING_DAYS})
    if not days:
        return "-"
    if len(days) == WORKING_DAYS:
        return "จ-ส"
    return "".join(DAY_SHORT[d] for d in days)


def project_xy(lat, lon, lat0: Optional[float] = None) -> Tuple[np.ndarray, np.ndarray, float]:
    lat_arr = np.asarray(lat, dtype=float)
    lon_arr = np.asarray(lon, dtype=float)
    if lat_arr.size == 0 or lon_arr.size == 0:
        return np.asarray([], dtype=float), np.asarray([], dtype=float), 0.0 if lat0 is None else float(lat0)
    if lat0 is None:
        lat0 = float(np.nanmean(lat_arr))
    scale = math.cos(math.radians(lat0))
    x = np.radians(lon_arr) * EARTH_RADIUS_M * scale
    y = np.radians(lat_arr) * EARTH_RADIUS_M
    return x, y, lat0


def knn_indices(xy: np.ndarray, k: int) -> np.ndarray:
    xy = np.asarray(xy, dtype=float)
    n = len(xy)
    k = int(min(max(0, k), max(0, n - 1)))
    if k <= 0:
        return np.zeros((n, 0), dtype=int)
    if HAS_SCIPY:
        tree = cKDTree(xy)
        _, indices = tree.query(xy, k=k + 1, workers=-1)
        if k == 1:
            indices = np.asarray(indices).reshape(n, 2)
        return np.asarray(indices[:, 1:], dtype=int)

    output = np.zeros((n, k), dtype=int)
    chunk_size = 512
    for start in range(0, n, chunk_size):
        end = min(n, start + chunk_size)
        distances = ((xy[start:end, None, :] - xy[None, :, :]) ** 2).sum(axis=2)
        local_rows = np.arange(end - start)
        global_rows = np.arange(start, end)
        distances[local_rows, global_rows] = np.inf
        nearest = np.argpartition(distances, kth=k - 1, axis=1)[:, :k]
        nearest_distances = np.take_along_axis(distances, nearest, axis=1)
        order = np.argsort(nearest_distances, axis=1)
        output[start:end] = np.take_along_axis(nearest, order, axis=1)
    return output


def kmeans_seeds(xy: np.ndarray, weights: np.ndarray, k: int, iters: int = 20, seed: int = 42) -> np.ndarray:
    xy = np.asarray(xy, dtype=float)
    weights = np.asarray(weights, dtype=float)
    n = len(xy)
    if n == 0:
        return np.zeros((0, 2), dtype=float)
    k = max(1, min(int(k), n))
    rng = np.random.default_rng(seed)
    valid_weights = np.where(np.isfinite(weights) & (weights > 0), weights, 1e-9)

    first_index = rng.choice(n, p=valid_weights / valid_weights.sum())
    centers = [xy[first_index]]

    for _ in range(k - 1):
        cur_centers = np.asarray(centers, dtype=float)
        dist_sq = np.min(((xy[:, None, :] - cur_centers[None, :, :]) ** 2).sum(axis=2), axis=1)
        probs = dist_sq * valid_weights
        if probs.sum() > 0:
            probs = probs / probs.sum()
        else:
            probs = np.full(n, 1.0 / n)
        centers.append(xy[rng.choice(n, p=probs)])

    centers_arr = np.asarray(centers, dtype=float)
    for _ in range(max(1, int(iters))):
        dist_sq = ((xy[:, None, :] - centers_arr[None, :, :]) ** 2).sum(axis=2)
        labels = dist_sq.argmin(axis=1)
        new_centers = centers_arr.copy()
        for c_idx in range(k):
            mask = labels == c_idx
            if not mask.any():
                continue
            new_centers[c_idx] = np.average(xy[mask], axis=0, weights=valid_weights[mask])
        if np.allclose(new_centers, centers_arr, atol=1e-3, rtol=0.0):
            break
        centers_arr = new_centers
    return centers_arr


def clean_truck_ids(values: Sequence) -> List[str]:
    output = []
    for value in values:
        t_id = str(value).strip()
        if t_id.lower() in NO_TRUCK_TOKENS:
            continue
        output.append(t_id)
    return sorted(set(output))


def guess_col(substrings: Sequence[str], cols: Sequence[str], fallback: Optional[str] = None, allow_none: bool = False) -> Optional[str]:
    for column in cols:
        column_text = str(column).lower()
        if any(str(sub).lower() in column_text for sub in substrings):
            return column
    if allow_none:
        return None
    return fallback if fallback is not None else (cols[0] if len(cols) else None)

# =====================================================================================
#  SECTION 3 — CONFIG / RESULT DATACLASSES
# =====================================================================================
@dataclass
class ZoningConfig:
    lat_col: str
    lon_col: str
    vol_col: str
    truck_col: str
    id_col: str
    day_col: str
    name_col: Optional[str] = None

    monthly_capacity: float = DEFAULT_MONTHLY_CAPACITY
    daily_control_cap: float = DEFAULT_DAILY_CONTROL_CAP
    max_stops_per_day: int = DEFAULT_MAX_STOPS_PER_DAY

    core_ratio: float = 65.0
    core_floor: float = 20.0
    core_step: float = 10.0

    tol_pct: float = 5.0
    tol_mode: str = "target"
    polish_tol_multiplier: float = 1.2

    knn_k: int = 8
    knn_rounds: int = 4
    knn_majority: float = 0.6

    enable_stray_cleanup: bool = True
    enable_majority_vote: bool = True
    enable_swap: bool = True
    swap_rounds: int = 3

    allow_vip_day_move: bool = False
    daily_passes: int = 12

    use_road: bool = False
    road_provider: str = "osrm"
    osrm_url: str = "https://router.project-osrm.org"
    gmaps_key: str = ""


@dataclass
class ZoningResult:
    result_df: pd.DataFrame
    stops_df: pd.DataFrame
    daily_matrix: np.ndarray
    daily_stops: np.ndarray
    final_daily: Dict[str, np.ndarray]
    targets: Dict[str, float]
    loads: Dict[str, float]
    core_ratio_used: float
    metrics: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    infos: List[str] = field(default_factory=list)

# =====================================================================================
#  SECTION 4 — CAPACITY PLANNING & FLEET DIAGNOSTIC
# =====================================================================================
def compute_default_targets(vol_by_truck: Dict[str, float], dissolve: Sequence[str], keep: Sequence[str], new_trucks: Sequence[str], cap_units: float) -> Tuple[Dict[str, float], float]:
    cap_limit = max(0.0, float(cap_units))
    pool = float(sum(float(vol_by_truck.get(t, 0.0)) for t in dissolve))
    targets: Dict[str, float] = {}

    for t in keep:
        vol = max(0.0, float(vol_by_truck.get(t, 0.0)))
        if vol > cap_limit:
            pool += vol - cap_limit
            targets[t] = cap_limit
        else:
            targets[t] = vol

    for t in new_trucks:
        targets[t] = 0.0

    for t in new_trucks:
        if pool <= 1e-6:
            break
        alloc = min(cap_limit - targets.get(t, 0.0), pool)
        targets[t] = targets.get(t, 0.0) + alloc
        pool -= alloc

    for _ in range(60):
        if pool <= 1e-6:
            break
        headroom = {t: max(0.0, cap_limit - tgt) for t, tgt in targets.items() if cap_limit - tgt > 1e-6}
        if not headroom:
            break
        total_head = sum(headroom.values())
        if total_head <= 1e-9:
            break
        ratio = min(1.0, pool / total_head)
        for t, avail in headroom.items():
            alloc = min(pool, avail * ratio)
            targets[t] += alloc
            pool -= alloc
            if pool <= 1e-6:
                pool = 0.0
                break
    return targets, max(0.0, pool)


def diagnose_fleet(df: pd.DataFrame, cfg: ZoningConfig) -> pd.DataFrame:
    output_rows = []
    if df.empty:
        return pd.DataFrame()

    for truck, group in df.groupby(cfg.truck_col, dropna=False):
        truck_id = str(truck).strip()
        if truck_id.lower() in NO_TRUCK_TOKENS:
            continue
        daily_vol = np.zeros(WORKING_DAYS, dtype=float)
        daily_stops = np.zeros(WORKING_DAYS, dtype=float)

        for _, row in group.iterrows():
            days, _ = parse_days_from_string(row.get(cfg.day_col))
            if not days:
                days = list(range(WORKING_DAYS))
            vol_m = float(pd.to_numeric(row.get(cfg.vol_col), errors="coerce") or 0.0)
            vol_per_day = vol_m / max(1, len(days)) / WEEKS_PER_MONTH
            for d in days:
                daily_vol[d] += vol_per_day
                daily_stops[d] += 1

        tot_vol = float(pd.to_numeric(group[cfg.vol_col], errors="coerce").fillna(0).sum())
        peak_v = float(daily_vol.max())
        peak_s = int(round(float(daily_stops.max())))

        if peak_v > cfg.daily_control_cap:
            status = "🔴 เกินเพดาน"
        elif peak_v >= OPTIMAL_MIN:
            status = "🟢 เหมาะสม"
        elif peak_v >= AVOID_MIN:
            status = "🟡 ควรเลี่ยง"
        else:
            status = "⚪ เบาเกิน"

        output_rows.append({
            "เบอร์รถ": truck_id,
            "จำนวนลูกค้า": int(len(group)),
            "ยอด/เดือน": int(round(tot_vol)),
            "ภาระงาน(%)": round(tot_vol / max(1.0, cfg.monthly_capacity) * 100.0, 1),
            "โหลดสูงสุด/วัน": int(round(peak_v)),
            "จุดจอดสูงสุด/วัน": peak_s,
            "ส่วนเกิน/วัน": int(round(max(0.0, peak_v - cfg.daily_control_cap))),
            "สถานะ": status,
        })

    out_df = pd.DataFrame(output_rows)
    return out_df.sort_values("โหลดสูงสุด/วัน", ascending=False).reset_index(drop=True) if not out_df.empty else out_df

# =====================================================================================
#  SECTION 5 — CORE ZONING & SATELLITE POCKET CONSOLIDATION
# =====================================================================================
def _tolerance_for(truck: str, targets: Dict[str, float], cfg: ZoningConfig) -> float:
    if cfg.tol_mode == "target":
        return max(40.0, (cfg.tol_pct / 100.0) * max(0.0, targets.get(truck, 0.0)))
    return (cfg.tol_pct / 100.0) * max(0.0, cfg.monthly_capacity)


def build_stops(df: pd.DataFrame, cfg: ZoningConfig) -> pd.DataFrame:
    stops = (
        df.groupby("coord_key", dropna=False)
        .agg(
            lat=(cfg.lat_col, "first"),
            lon=(cfg.lon_col, "first"),
            x=("x", "first"),
            y=("y", "first"),
            total_vol=(cfg.vol_col, "sum"),
            n_cust=(cfg.id_col, "count"),
            orig_truck=(cfg.truck_col, "first"),
            has_vip_lock=("is_vip_locked", "any"),
        )
        .reset_index()
    )
    stops["orig_truck"] = stops["orig_truck"].astype(str).str.strip()
    stops["total_vol"] = pd.to_numeric(stops["total_vol"], errors="coerce").fillna(0.0).astype(float)
    return stops


def compute_core_keys(stops: pd.DataFrame, ratio: float, eligible_trucks: Sequence[str], ratio_override: Optional[Dict[str, float]] = None) -> set:
    core_keys = set()
    if stops.empty or ratio <= 0:
        return core_keys
    ratio_override = ratio_override or {}

    for truck in eligible_trucks:
        t_ratio = min(float(ratio), float(ratio_override.get(truck, 100.0)))
        if t_ratio <= 0:
            continue
        group = stops[stops["orig_truck"] == truck].copy()
        if group.empty:
            continue
        weights = np.maximum(group["total_vol"].to_numpy(dtype=float), 1e-9)
        cx, cy = float(np.average(group["x"], weights=weights)), float(np.average(group["y"], weights=weights))
        group["_dist_sq"] = (group["x"] - cx) ** 2 + (group["y"] - cy) ** 2
        group = group.sort_values("_dist_sq", ascending=True)
        tot = max(1e-6, float(group["total_vol"].sum()))
        selected = (group["total_vol"].cumsum() / tot) <= (t_ratio / 100.0)
        if not selected.any() and len(group):
            selected.iloc[0] = True
        core_keys.update(group.loc[selected, "coord_key"].tolist())
    return core_keys


def _assign_capacitated(stops: pd.DataFrame, trucks: List[str], targets: Dict[str, float], tolerance: Dict[str, float], seeds: Dict[str, Tuple[float, float]], road: Optional[np.ndarray], max_rounds: int = 80) -> Tuple[np.ndarray, Dict[str, float]]:
    n_stops, n_trucks = len(stops), len(trucks)
    if n_stops == 0:
        return np.asarray([], dtype=int), {t: 0.0 for t in trucks}
    if n_trucks == 0:
        return np.full(n_stops, -1, dtype=int), {}

    coords = stops[["x", "y"]].to_numpy(dtype=float)
    vols = stops["total_vol"].to_numpy(dtype=float)
    t_idx = {t: i for i, t in enumerate(trucks)}
    assigned = np.array([t_idx.get(v, -1) if isinstance(v, str) else -1 for v in stops["assigned_truck"].tolist()], dtype=int)
    loads = {t: 0.0 for t in trucks}

    for idx in np.where(assigned >= 0)[0]:
        loads[trucks[assigned[idx]]] += vols[idx]

    for _ in range(max(1, int(max_rounds))):
        el_trucks = [t for t in trucks if loads[t] < targets.get(t, 0.0) - 1e-9]
        if not el_trucks:
            break
        cand_indices = np.where(assigned < 0)[0]
        if cand_indices.size == 0:
            break
        el_cols = [t_idx[t] for t in el_trucks]

        centers = []
        for t in el_trucks:
            mask = assigned == t_idx[t]
            if mask.any():
                center = np.average(coords[mask], axis=0, weights=np.maximum(vols[mask], 1e-9))
            else:
                center = np.asarray(seeds.get(t, (coords[:, 0].mean(), coords[:, 1].mean())), dtype=float)
            centers.append(center)
        centers_arr = np.asarray(centers, dtype=float)
        dist = np.sqrt(((coords[cand_indices][:, None, :] - centers_arr[None, :, :]) ** 2).sum(axis=2))

        caps = np.asarray([targets.get(t, 0.0) + tolerance.get(t, 0.0) for t in el_trucks], dtype=float)
        cur_loads = np.asarray([loads[t] for t in el_trucks], dtype=float)
        feasible = cur_loads[None, :] + vols[cand_indices][:, None] <= caps[None, :]
        dist = np.where(feasible, dist, np.inf)

        best_t_local = dist.argmin(axis=1)
        best_d = dist[np.arange(len(cand_indices)), best_t_local]
        feas_rows = np.isfinite(best_d)
        if not feas_rows.any():
            break

        feas_cand = cand_indices[feas_rows]
        feas_t_indices = best_t_local[feas_rows]
        order = np.argsort(best_d[feas_rows])
        placed = False

        for pos in order:
            s_idx = feas_cand[pos]
            if assigned[s_idx] >= 0:
                continue
            t = el_trucks[feas_t_indices[pos]]
            if loads[t] + vols[s_idx] > targets.get(t, 0.0) + tolerance.get(t, 0.0):
                continue
            assigned[s_idx] = t_idx[t]
            loads[t] += vols[s_idx]
            placed = True
        if not placed:
            break

    # Relaxed Best-fit
    for s_idx in np.where(assigned < 0)[0]:
        cand_trucks = [t for t in trucks if targets.get(t, 0.0) > 0]
        if not cand_trucks:
            continue
        best_t = max(cand_trucks, key=lambda t: targets.get(t, 0.0) - loads.get(t, 0.0))
        tgt = targets.get(best_t, 0.0)
        if loads.get(best_t, 0.0) + vols[s_idx] <= tgt + max(tolerance.get(best_t, 0.0), tgt * 0.20):
            assigned[s_idx] = t_idx[best_t]
            loads[best_t] += vols[s_idx]

    return assigned, loads


def consolidate_satellite_pockets(
    stops: pd.DataFrame,
    trucks: List[str],
    targets: Dict[str, float],
    loads: Dict[str, float],
    tolerance: Dict[str, float],
    pocket_radius_m: float = 450.0,
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    stops = stops.copy()
    loads = dict(loads)
    n = len(stops)
    if n <= 1:
        return stops, loads

    coords = stops[["x", "y"]].to_numpy(dtype=float)

    if HAS_SCIPY:
        tree = cKDTree(coords)
        pairs = tree.query_pairs(r=pocket_radius_m)
    else:
        pairs = []
        for i in range(n):
            dists_sq = ((coords[i] - coords[i+1:]) ** 2).sum(axis=1)
            for j_offset, d2 in enumerate(dists_sq):
                if d2 <= pocket_radius_m ** 2:
                    pairs.append((i, i + 1 + j_offset))

    parent = list(range(n))
    def find(i):
        path = []
        while parent[i] != i:
            path.append(i)
            i = parent[i]
        for p in path:
            parent[p] = i
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[ri] = rj

    for i, j in pairs:
        union(i, j)

    components: Dict[int, List[int]] = {}
    for i in range(n):
        root = find(i)
        components.setdefault(root, []).append(i)

    centers = {}
    for t in trucks:
        grp = stops[stops["assigned_truck"] == t]
        if not grp.empty:
            w = np.maximum(grp["total_vol"].to_numpy(dtype=float), 1e-9)
            centers[t] = np.average(grp[["x", "y"]].to_numpy(dtype=float), axis=0, weights=w)

    for root, member_indices in components.items():
        if len(member_indices) >= n * 0.45:
            continue

        member_stops = stops.iloc[member_indices]
        assigned_trucks = [t for t in member_stops["assigned_truck"].unique().tolist() if t in trucks]

        if len(set(assigned_trucks)) > 1:
            pw = np.maximum(member_stops["total_vol"].to_numpy(dtype=float), 1e-9)
            pocket_center = np.average(member_stops[["x", "y"]].to_numpy(dtype=float), axis=0, weights=pw)

            vip_trucks = member_stops.loc[member_stops["is_locked"].astype(bool), "assigned_truck"].tolist()
            vip_trucks = [t for t in vip_trucks if t in trucks]

            if vip_trucks:
                best_truck = vip_trucks[0]
            else:
                best_truck = None
                best_dist = float("inf")
                for t in assigned_trucks:
                    if t in centers:
                        d = np.sqrt(((pocket_center - centers[t]) ** 2).sum())
                        if d < best_dist:
                            best_dist = d
                            best_truck = t

            if best_truck is None and assigned_trucks:
                best_truck = assigned_trucks[0]

            if best_truck is not None:
                for s_idx in member_indices:
                    old_t = stops.at[s_idx, "assigned_truck"]
                    if old_t != best_truck:
                        if not bool(stops.at[s_idx, "is_locked"]) or old_t not in trucks:
                            v = float(stops.at[s_idx, "total_vol"])
                            stops.at[s_idx, "assigned_truck"] = best_truck
                            if old_t in loads:
                                loads[old_t] -= v
                            loads[best_truck] = loads.get(best_truck, 0.0) + v

    return stops, loads


def cleanup_stray_points(stops: pd.DataFrame, trucks: List[str], targets: Dict[str, float], loads: Dict[str, float], tolerance: Dict[str, float], multiplier: float, rounds: int = 3) -> Tuple[pd.DataFrame, Dict[str, float]]:
    stops = stops.copy()
    loads = dict(loads)
    for _ in range(max(1, int(rounds))):
        changed = False
        centers = {}
        for t in trucks:
            grp = stops[stops["assigned_truck"] == t]
            if not grp.empty:
                w = np.maximum(grp["total_vol"].to_numpy(dtype=float), 1e-9)
                centers[t] = (float(np.average(grp["x"], weights=w)), float(np.average(grp["y"], weights=w)))

        for t in trucks:
            mask = (stops["assigned_truck"] == t) & (~stops["is_locked"].astype(bool))
            grp = stops[mask]
            if len(grp) < 3 or t not in centers:
                continue
            cx, cy = centers[t]
            dists = np.sqrt((grp["x"] - cx) ** 2 + (grp["y"] - cy) ** 2)
            stray_indices = grp.index[dists > (float(dists.median()) * 3.0 + 1.0)]

            for s_idx in stray_indices:
                stop = stops.loc[s_idx]
                own_d_sq = (stop["x"] - cx) ** 2 + (stop["y"] - cy) ** 2
                best_t, best_d_sq = None, float("inf")
                for ot, (ox, oy) in centers.items():
                    if ot == t:
                        continue
                    d_sq = (stop["x"] - ox) ** 2 + (stop["y"] - oy) ** 2
                    if d_sq < best_d_sq:
                        best_d_sq, best_t = d_sq, ot
                if best_t is None:
                    continue
                proj = loads.get(best_t, 0.0) + float(stop["total_vol"])
                allowed = targets.get(best_t, 0.0) + tolerance.get(best_t, 0.0) * multiplier
                if best_d_sq < own_d_sq * 0.6 and proj <= allowed:
                    vol = float(stop["total_vol"])
                    stops.at[s_idx, "assigned_truck"] = best_t
                    loads[t] -= vol
                    loads[best_t] += vol
                    changed = True
        if not changed:
            break
    return stops, loads


def majority_vote_smoothing(stops: pd.DataFrame, trucks: List[str], targets: Dict[str, float], loads: Dict[str, float], tolerance: Dict[str, float], cfg: ZoningConfig) -> Tuple[pd.DataFrame, Dict[str, float]]:
    stops = stops.copy().reset_index(drop=True)
    loads = dict(loads)
    n_stops = len(stops)
    if n_stops < cfg.knn_k + 2:
        return stops, loads

    coords = stops[["x", "y"]].to_numpy(dtype=float)
    nbrs = knn_indices(coords, cfg.knn_k)
    locked = stops["is_locked"].astype(bool).to_numpy()
    vols = stops["total_vol"].to_numpy(dtype=float)
    val_trucks = set(trucks)

    for _ in range(max(1, int(cfg.knn_rounds))):
        changed = False
        assigned = stops["assigned_truck"].astype(object).to_numpy().copy()
        for idx in range(n_stops):
            if locked[idx]:
                continue
            cur_t = assigned[idx]
            nbr_t = [v for v in assigned[nbrs[idx]].tolist() if v in val_trucks]
            if not nbr_t:
                continue
            vals, counts = np.unique(np.asarray(nbr_t, dtype=str), return_counts=True)
            maj_t = str(vals[np.argmax(counts)])
            if maj_t == cur_t or int(counts.max()) < cfg.knn_k * cfg.knn_majority:
                continue
            proj = loads.get(maj_t, 0.0) + vols[idx]
            if proj > targets.get(maj_t, 0.0) + tolerance.get(maj_t, 0.0) * cfg.polish_tol_multiplier:
                continue
            if cur_t in val_trucks:
                loads[cur_t] -= vols[idx]
            loads[maj_t] = proj
            assigned[idx] = maj_t
            changed = True
        stops["assigned_truck"] = assigned
        if not changed:
            break
    return stops, loads


def swap_improve(stops: pd.DataFrame, trucks: List[str], targets: Dict[str, float], loads: Dict[str, float], tolerance: Dict[str, float], rounds: int = 3, max_pairs: int = 60) -> Tuple[pd.DataFrame, Dict[str, float]]:
    stops = stops.copy()
    loads = dict(loads)
    for _ in range(max(1, int(rounds))):
        changed = False
        centers = {}
        for t in trucks:
            grp = stops[stops["assigned_truck"] == t]
            if not grp.empty:
                w = np.maximum(grp["total_vol"].to_numpy(dtype=float), 1e-9)
                centers[t] = np.asarray([np.average(grp["x"], weights=w), np.average(grp["y"], weights=w)], dtype=float)

        for ta, tb in combinations([t for t in trucks if t in centers], 2):
            ca, cb = centers[ta], centers[tb]
            ga = stops[(stops["assigned_truck"] == ta) & (~stops["is_locked"].astype(bool))]
            gb = stops[(stops["assigned_truck"] == tb) & (~stops["is_locked"].astype(bool))]
            if ga.empty or gb.empty:
                continue
            co_a, co_b = ga[["x", "y"]].to_numpy(dtype=float), gb[["x", "y"]].to_numpy(dtype=float)
            gain_a = np.sqrt(((co_a - ca) ** 2).sum(axis=1)) - np.sqrt(((co_a - cb) ** 2).sum(axis=1))
            gain_b = np.sqrt(((co_b - cb) ** 2).sum(axis=1)) - np.sqrt(((co_b - ca) ** 2).sum(axis=1))

            c_a = ga.index[np.argsort(-gain_a)][:max_pairs]
            c_b = gb.index[np.argsort(-gain_b)][:max_pairs]
            gl_a, gl_b = dict(zip(ga.index, gain_a)), dict(zip(gb.index, gain_b))
            used_b = set()

            for ia in c_a:
                if gl_a[ia] <= 0:
                    break
                for ib in c_b:
                    if ib in used_b or gl_b[ib] <= 0 or gl_a[ia] + gl_b[ib] <= 0:
                        continue
                    va, vb = float(stops.at[ia, "total_vol"]), float(stops.at[ib, "total_vol"])
                    n_la, n_lb = loads.get(ta, 0.0) - va + vb, loads.get(tb, 0.0) - vb + va
                    if n_la > targets.get(ta, 0.0) + tolerance.get(ta, 0.0) or n_lb > targets.get(tb, 0.0) + tolerance.get(tb, 0.0):
                        continue
                    stops.at[ia, "assigned_truck"], stops.at[ib, "assigned_truck"] = tb, ta
                    loads[ta], loads[tb] = n_la, n_lb
                    used_b.add(ib)
                    changed = True
                    break
        if not changed:
            break
    return stops, loads

# =====================================================================================
#  SECTION 6 — DAILY LOAD SMOOTHING & COMPACTNESS
# =====================================================================================
def smooth_daily_loads(opt: pd.DataFrame, cfg: ZoningConfig, trucks: List[str]) -> Tuple[pd.DataFrame, np.ndarray, np.ndarray, Dict[str, np.ndarray]]:
    opt = opt.copy().reset_index(drop=True)
    trucks = list(dict.fromkeys(str(t).strip() for t in trucks))
    n_rows = len(opt)
    if n_rows == 0:
        empty_mat = np.zeros((0, WORKING_DAYS), dtype=float)
        return opt, empty_mat, empty_mat.copy(), {t: np.zeros(WORKING_DAYS, dtype=float) for t in trucks}

    if "สถานะการย้ายวัน" not in opt.columns:
        opt["สถานะการย้ายวัน"] = "-"
    if "is_vip_locked" not in opt.columns:
        opt["is_vip_locked"] = False

    m_vols = pd.to_numeric(opt[cfg.vol_col], errors="coerce").fillna(0.0).to_numpy(dtype=float)
    day_map: Dict[int, List[int]] = {}

    for idx in opt.index:
        days, status = parse_days_from_string(opt.at[idx, cfg.day_col])
        if not days:
            days = list(range(WORKING_DAYS))
        day_map[idx] = list(sorted(set(days)))
        opt.at[idx, "_day_status"] = status

    def recompute_daily():
        d_vol = {t: np.zeros(WORKING_DAYS, dtype=float) for t in trucks}
        d_stops = {t: np.zeros(WORKING_DAYS, dtype=float) for t in trucks}
        for idx in opt.index:
            t = str(opt.at[idx, "เบอร์รถใหม่"]).strip()
            if t not in d_vol:
                continue
            days = day_map[idx]
            if not days:
                continue
            v_day = m_vols[idx] / len(days) / WEEKS_PER_MONTH
            for d in days:
                if 0 <= d < WORKING_DAYS:
                    d_vol[t][d] += v_day
                    d_stops[t][d] += 1
        return d_vol, d_stops

    d_cap = max(1.0, float(cfg.daily_control_cap))
    max_s = max(1, int(cfg.max_stops_per_day))

    for _ in range(max(1, int(cfg.daily_passes))):
        d_vol, d_stops = recompute_daily()
        changed = False

        for t in trucks:
            if t not in d_vol:
                continue
            score = d_vol[t] / d_cap + d_stops[t] / max_s
            src_order = np.argsort(-score)

            for src in src_order:
                src = int(src)
                if not (d_vol[t][src] > d_cap or d_stops[t][src] > max_s):
                    continue
                dest_score = (d_vol[t] / d_cap + d_stops[t] / max_s).copy()
                dest_score[src] = np.inf
                dest_candidates = np.argsort(dest_score)
                dest = None

                for cand in dest_candidates:
                    cand = int(cand)
                    if not np.isfinite(dest_score[cand]) or d_vol[t][cand] >= d_cap or d_stops[t][cand] >= max_s:
                        continue
                    dest = cand
                    break
                if dest is None:
                    continue

                movable = []
                for idx in opt.index:
                    if str(opt.at[idx, "เบอร์รถใหม่"]).strip() != t:
                        continue
                    if not cfg.allow_vip_day_move and bool(opt.at[idx, "is_vip_locked"]):
                        continue
                    c_days = day_map[idx]
                    if src not in c_days or dest in c_days or len(c_days) > 3:
                        continue
                    movable.append(idx)
                if not movable:
                    continue

                movable.sort(key=lambda idx: -m_vols[idx] / max(1, len(day_map[idx])))
                excess_v = max(0.0, d_vol[t][src] - TARGET_DAY_CAP)
                shifted_v = 0.0

                for idx in movable:
                    c_days = day_map[idx]
                    v_day = m_vols[idx] / max(1, len(c_days)) / WEEKS_PER_MONTH
                    if d_vol[t][dest] + v_day > d_cap or d_stops[t][dest] + 1 > max_s:
                        continue
                    new_days = sorted(set(dest if d == src else d for d in c_days))
                    if len(new_days) != len(c_days):
                        continue
                    day_map[idx] = new_days
                    note = f"{DAY_SHORT[src]}→{DAY_SHORT[dest]}"
                    prev = str(opt.at[idx, "สถานะการย้ายวัน"]).strip()
                    if not prev or prev.lower() in NO_TRUCK_TOKENS:
                        opt.at[idx, "สถานะการย้ายวัน"] = note
                    else:
                        notes = [n.strip() for n in prev.split(",") if n.strip()]
                        if note not in notes:
                            notes.append(note)
                        opt.at[idx, "สถานะการย้ายวัน"] = ", ".join(notes)

                    d_vol[t][src] -= v_day
                    d_vol[t][dest] += v_day
                    d_stops[t][src] -= 1
                    d_stops[t][dest] += 1
                    shifted_v += v_day
                    changed = True
                    if d_vol[t][src] <= d_cap and d_stops[t][src] <= max_s and shifted_v >= excess_v:
                        break
        if not changed:
            break

    for idx in opt.index:
        opt.at[idx, "วันจัดส่ง(ใหม่)"] = format_days_to_string(day_map[idx])
        opt.at[idx, "วันจัดส่ง(ย่อ)"] = format_days_short(day_map[idx])

    daily_mat = np.zeros((n_rows, WORKING_DAYS), dtype=float)
    daily_s_mat = np.zeros((n_rows, WORKING_DAYS), dtype=float)
    for idx in opt.index:
        days = day_map[idx]
        if not days:
            continue
        v_day = m_vols[idx] / len(days) / WEEKS_PER_MONTH
        for d in days:
            daily_mat[idx, d] = v_day
            daily_s_mat[idx, d] = 1.0

    final_daily, _ = recompute_daily()
    return opt, daily_mat, daily_s_mat, final_daily


def compute_compactness(group: pd.DataFrame) -> float:
    if group.empty:
        return 0.0
    coords = group[["x", "y"]].to_numpy(dtype=float)
    weights = np.ones(len(group), dtype=float)
    if "total_vol" in group.columns:
        weights = np.maximum(pd.to_numeric(group["total_vol"], errors="coerce").fillna(0.0).to_numpy(dtype=float), 1e-9)
    center = np.average(coords, axis=0, weights=weights)
    return float(np.average(np.sqrt(((coords - center) ** 2).sum(axis=1)), weights=weights))


def calculate_peak_daily_loads(data: pd.DataFrame, truck_col: str, vol_col: str, day_col: str) -> Dict[str, float]:
    output = {}
    if data.empty:
        return output
    for truck, group in data.groupby(truck_col, dropna=False):
        t_id = str(truck).strip()
        if t_id.lower() in NO_TRUCK_TOKENS:
            continue
        daily = np.zeros(WORKING_DAYS, dtype=float)
        for _, row in group.iterrows():
            days, _ = parse_days_from_string(row.get(day_col))
            if not days:
                days = list(range(WORKING_DAYS))
            vol_m = float(pd.to_numeric(row.get(vol_col), errors="coerce") or 0.0)
            v_day = vol_m / len(days) / WEEKS_PER_MONTH
            for d in days:
                daily[d] += v_day
        output[t_id] = float(daily.max())
    return output

# =====================================================================================
#  SECTION 7 — MAIN ENGINE EXECUTION
# =====================================================================================
def run_multi_donor_zoning(df: pd.DataFrame, cfg: ZoningConfig, target_pcts: Dict[str, float], dissolve_trucks: Sequence[str], relieve_trucks: Sequence[str], new_trucks: Sequence[str], manual_locks: Sequence[str], road_matrix_getter=None) -> ZoningResult:
    warnings, infos = [], []
    if df is None or df.empty:
        raise ValueError("ไม่มีข้อมูลสำหรับประมวลผล")

    opt = df.copy().reset_index(drop=True)
    opt[cfg.lat_col] = pd.to_numeric(opt[cfg.lat_col], errors="coerce")
    opt[cfg.lon_col] = pd.to_numeric(opt[cfg.lon_col], errors="coerce")
    opt[cfg.vol_col] = pd.to_numeric(opt[cfg.vol_col], errors="coerce").fillna(0.0).clip(lower=0.0).astype(float)
    opt[cfg.truck_col] = opt[cfg.truck_col].astype(str).str.strip()
    opt[cfg.id_col] = opt[cfg.id_col].astype(str).str.strip()

    valid_mask = opt[cfg.lat_col].notna() & opt[cfg.lon_col].notna() & (~opt[cfg.truck_col].str.lower().isin(NO_TRUCK_TOKENS))
    opt = opt[valid_mask].reset_index(drop=True)

    all_orig_trucks = clean_truck_ids(opt[cfg.truck_col].unique())
    dissolve = [t for t in all_orig_trucks if t in set(dissolve_trucks)]
    kept = [t for t in all_orig_trucks if t not in set(dissolve_trucks)]
    norm_new = [t.strip() for t in new_trucks if t.strip() and t.strip() not in kept and t.strip().lower() not in NO_TRUCK_TOKENS]
    norm_new = list(dict.fromkeys(norm_new))
    active = kept + norm_new

    if not active:
        raise ValueError("ไม่เหลือรถที่สามารถรับการจัดสรรงานได้")

    targets = {t: max(0.0, cfg.monthly_capacity * float(target_pcts.get(t, 0.0)) / 100.0) for t in active}
    tolerance = {t: _tolerance_for(t, targets, cfg) for t in active}

    locked_ids = {str(v).strip() for v in manual_locks if str(v).strip()}
    vip_status = opt["VIP_Status"].astype(str).str.upper().str.strip() if "VIP_Status" in opt.columns else pd.Series(["ปกติ"] * len(opt))
    opt["is_vip_locked"] = vip_status.eq("VIP") | opt[cfg.id_col].isin(locked_ids)
    opt["สถานะการย้ายวัน"] = "-"
    opt["coord_key"] = opt[cfg.lat_col].round(5).astype(str) + "," + opt[cfg.lon_col].round(5).astype(str)

    px, py, lat_ref = project_xy(opt[cfg.lat_col].to_numpy(dtype=float), opt[cfg.lon_col].to_numpy(dtype=float))
    opt["x"], opt["y"] = px, py
    stops = build_stops(opt, cfg)

    vol_by_orig = stops.groupby("orig_truck")["total_vol"].sum().to_dict()
    ratio_override = {}
    for t in relieve_trucks:
        c_vol = float(vol_by_orig.get(t, 0.0))
        if c_vol > 0 and t in targets:
            ratio_override[t] = max(0.0, min(100.0, targets[t] / c_vol * 100.0 * 0.92))

    core_eligible = [t for t in kept if t not in set(dissolve)]
    seeds: Dict[str, Tuple[float, float]] = {}
    for t in kept:
        grp = stops[stops["orig_truck"] == t]
        if not grp.empty:
            w = np.maximum(grp["total_vol"].to_numpy(dtype=float), 1e-9)
            seeds[t] = (float(np.average(grp["x"], weights=w)), float(np.average(grp["y"], weights=w)))

    gw = np.maximum(stops["total_vol"].to_numpy(dtype=float), 1e-9)
    gx, gy = float(np.average(stops["x"], weights=gw)), float(np.average(stops["y"], weights=gw))

    if norm_new:
        init_cores = compute_core_keys(stops, cfg.core_ratio, core_eligible, ratio_override)
        spool = stops[~stops["coord_key"].isin(init_cores)]
        if spool.empty:
            spool = stops
        new_centers = kmeans_seeds(spool[["x", "y"]].to_numpy(dtype=float), spool["total_vol"].to_numpy(dtype=float), len(norm_new))
        if len(new_centers) == 0:
            new_centers = np.asarray([[gx, gy]], dtype=float)
        for idx, t in enumerate(norm_new):
            c_idx = min(idx, len(new_centers) - 1)
            seeds[t] = (float(new_centers[c_idx, 0]), float(new_centers[c_idx, 1]))

    def run_single_pass(core_ratio: float):
        c_stops = stops.copy()
        c_keys = compute_core_keys(c_stops, core_ratio, core_eligible, ratio_override)
        c_stops["is_core_locked"] = c_stops["coord_key"].isin(c_keys)
        c_stops["is_locked"] = c_stops["has_vip_lock"].astype(bool) | c_stops["is_core_locked"].astype(bool)
        c_stops["assigned_truck"] = None

        for s_idx, row in c_stops.iterrows():
            ot = str(row["orig_truck"]).strip()
            if bool(row["is_locked"]) and ot in active:
                c_stops.at[s_idx, "assigned_truck"] = ot

        assignment, pass_loads = _assign_capacitated(c_stops, active, targets, tolerance, seeds, None)
        c_stops["assigned_truck"] = [active[ti] if ti >= 0 else OVERFLOW_LABEL for ti in assignment]
        c_stops.loc[c_stops["is_locked"] & (~c_stops["orig_truck"].isin(active)), "is_locked"] = False
        return c_stops, pass_loads

    cur_ratio = max(0.0, min(100.0, float(cfg.core_ratio)))
    min_ratio = max(0.0, min(cur_ratio, float(cfg.core_floor)))
    c_step = max(1.0, float(cfg.core_step))
    best_result = None

    while True:
        c_stops, c_loads = run_single_pass(cur_ratio)
        tot_viol = sum(max(0.0, abs(c_loads.get(t, 0.0) - targets.get(t, 0.0)) - tolerance.get(t, 0.0)) for t in active if targets.get(t, 0.0) > 0)
        over_v = float(c_stops.loc[c_stops["assigned_truck"] == OVERFLOW_LABEL, "total_vol"].sum())
        score = tot_viol + over_v * 2.0

        if best_result is None or score < best_result[3]:
            best_result = (c_stops, c_loads, cur_ratio, score)
        if score <= 1e-6 or cur_ratio <= min_ratio:
            break
        cur_ratio = max(min_ratio, cur_ratio - c_step)

    assigned_stops, loads, ratio_used, _ = best_result

    # รวมเวิ้งงานโดดเดี่ยวไม่ให้ผ่าครึ่ง
    assigned_stops, loads = consolidate_satellite_pockets(assigned_stops, active, targets, loads, tolerance, pocket_radius_m=450.0)

    if cfg.enable_stray_cleanup:
        assigned_stops, loads = cleanup_stray_points(assigned_stops, active, targets, loads, tolerance, cfg.polish_tol_multiplier)
    if cfg.enable_majority_vote:
        assigned_stops, loads = majority_vote_smoothing(assigned_stops, active, targets, loads, tolerance, cfg)
    if cfg.enable_swap:
        assigned_stops, loads = swap_improve(assigned_stops, active, targets, loads, tolerance, cfg.swap_rounds)

    assigned_stops, loads = consolidate_satellite_pockets(assigned_stops, active, targets, loads, tolerance, pocket_radius_m=450.0)

    truck_mapping = dict(zip(assigned_stops["coord_key"], assigned_stops["assigned_truck"]))
    core_mapping = dict(zip(assigned_stops["coord_key"], assigned_stops["is_core_locked"]))

    opt["เบอร์รถใหม่"] = opt["coord_key"].map(truck_mapping).fillna(OVERFLOW_LABEL).astype(str)
    opt["is_core_locked"] = opt["coord_key"].map(core_mapping).fillna(False).astype(bool)
    opt["is_locked"] = opt["is_vip_locked"].astype(bool) | opt["is_core_locked"].astype(bool)

    orig_s = opt[cfg.truck_col].astype(str).str.strip()
    new_s = opt["เบอร์รถใหม่"].astype(str).str.strip()
    same_m = orig_s == new_s

    opt["สถานะ"] = np.where(same_m, "คงเดิม", "ย้ายไปสาย " + new_s)
    opt.loc[opt["is_locked"] & same_m, "สถานะ"] = "คงเดิม 🔒"

    opt, daily_matrix, daily_stops_matrix, final_daily = smooth_daily_loads(opt, cfg, active)

    comp_before = [compute_compactness(grp) for _, grp in opt.groupby(cfg.truck_col)]
    comp_after = [compute_compactness(grp) for t, grp in opt.groupby("เบอร์รถใหม่") if t != OVERFLOW_LABEL]
    peak_before = calculate_peak_daily_loads(opt, cfg.truck_col, cfg.vol_col, cfg.day_col)
    peak_after = {t: float(v.max()) for t, v in final_daily.items()}
    moved_m = orig_s != new_s

    metrics = {
        "compact_before_km": float(np.mean(comp_before)) / 1000.0 if comp_before else 0.0,
        "compact_after_km": float(np.mean(comp_after)) / 1000.0 if comp_after else 0.0,
        "over_before": int(sum(1 for v in peak_before.values() if v > cfg.daily_control_cap)),
        "over_after": int(sum(1 for v in peak_after.values() if v > cfg.daily_control_cap)),
        "peak_before": max(peak_before.values()) if peak_before else 0.0,
        "peak_after": max(peak_after.values()) if peak_after else 0.0,
        "moved_cust": int(moved_m.sum()),
        "moved_pct": float(moved_m.sum()) / max(1, len(opt)) * 100.0,
        "moved_vol": float(opt.loc[moved_m, cfg.vol_col].sum()),
        "std_before": float(np.std(list(peak_before.values()))) if peak_before else 0.0,
        "std_after": float(np.std(list(peak_after.values()))) if peak_after else 0.0,
    }

    return ZoningResult(
        result_df=opt, stops_df=assigned_stops, daily_matrix=daily_matrix,
        daily_stops=daily_stops_matrix, final_daily=final_daily,
        targets=targets, loads=loads, core_ratio_used=float(ratio_used),
        metrics=metrics, warnings=warnings, infos=infos
    )

# =====================================================================================
#  SECTION 8 — DYNAMIC FONT SCALING & HIGH-CONTRAST THEME
# =====================================================================================

st.sidebar.markdown("### 🔤 ขนาดอักษร:")
font_size_choice = st.sidebar.radio(
    "เลือกขนาดตัวอักษรของระบบ:",
    options=["ก ปกติ", "ก ใหญ่", "ก ใหญ่พิเศษ (+)"],
    index=0,
    horizontal=True,
    label_visibility="collapsed"
)

if font_size_choice == "ก ใหญ่":
    root_font = "17.5px"
    base_font = "17px"
    h1_font = "30px"
    h2_font = "24px"
    h3_font = "20px"
    metric_val_font = "2.1rem"
    metric_lbl_font = "1.05rem"
    small_font = "15px"
elif font_size_choice == "ก ใหญ่พิเศษ (+)":
    root_font = "20.5px"
    base_font = "20px"
    h1_font = "34px"
    h2_font = "28px"
    h3_font = "23px"
    metric_val_font = "2.5rem"
    metric_lbl_font = "1.2rem"
    small_font = "17.5px"
else:
    root_font = "15px"
    base_font = "15px"
    h1_font = "26px"
    h2_font = "20px"
    h3_font = "17px"
    metric_val_font = "1.7rem"
    metric_lbl_font = "0.95rem"
    small_font = "13.5px"

st.markdown(f'''
<style>
@import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');

html {{
    font-size: {root_font} !important;
}}
html, body, [class*="css"], .stApp {{
    font-family: 'Sarabun', sans-serif !important;
}}

/* พื้นหลังหลักสีฟ้าครามประกายน้ำดื่มสปริงเคิล */
.stApp {{
    background:
        radial-gradient(circle at 15% 15%, rgba(56, 189, 248, 0.28) 0%, transparent 45%),
        radial-gradient(circle at 85% 25%, rgba(14, 165, 233, 0.22) 0%, transparent 45%),
        radial-gradient(circle at 50% 85%, rgba(2, 132, 199, 0.35) 0%, transparent 55%),
        linear-gradient(135deg, #033B60 0%, #02598B 35%, #0277B5 70%, #0284C7 100%) !important;
    background-attachment: fixed !important;
}}

/* -------------------------------------------------------------
   🔒 คืนค่าแถบเมนูด้านซ้าย (SIDEBAR) ล็อกสไตล์เดิม 100%
   ------------------------------------------------------------- */
[data-testid="stSidebar"] {{
    background: rgba(0, 13, 26, 0.65) !important;
    backdrop-filter: blur(25px);
    border-right: 1px solid rgba(255,255,255,0.15) !important;
}}
[data-testid="stSidebar"] * {{
    color: #FFFFFF !important;
    font-size: {base_font} !important;
}}
[data-testid="stSidebar"] label, [data-testid="stSidebar"] .stMarkdown p {{
    color: #F3E5AB !important;
    font-weight: 600 !important;
}}
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{
    color: #FFD700 !important;
    border-bottom: 1px solid rgba(212,175,55,0.3) !important;
    padding-bottom: 8px !important;
}}
[data-testid="stSidebar"] input,
[data-testid="stSidebar"] textarea,
[data-testid="stSidebar"] div[data-baseweb="select"] > div {{
    background: rgba(0, 30, 60, 0.5) !important;
    backdrop-filter: blur(12px) !important;
    border: 1px solid rgba(255, 255, 255, 0.25) !important;
    color: #FFFFFF !important;
    border-radius: 10px !important;
    font-weight: 500 !important;
}}
[data-testid="stSidebar"] input::placeholder,
[data-testid="stSidebar"] textarea::placeholder {{
    color: #CBD5E1 !important;
    opacity: 0.8 !important;
}}
[data-testid="stSidebar"] div[data-baseweb="select"] * {{
    color: #FFFFFF !important;
}}
[data-testid="stSidebar"] div[data-baseweb="select"] svg {{
    fill: #FFFFFF !important;
}}

/* Segmented Control ปุ่มปรับขนาดฟอนต์ใน Sidebar */
[data-testid="stSidebar"] div[data-testid="stRadio"] > div {{
    flex-direction: row !important;
    background: rgba(0, 24, 48, 0.75) !important;
    padding: 3px 5px !important;
    border-radius: 10px !important;
    border: 1px solid rgba(255, 255, 255, 0.2) !important;
    gap: 3px !important;
}}
[data-testid="stSidebar"] div[data-testid="stRadio"] label {{
    background: transparent !important;
    border-radius: 6px !important;
    padding: 4px 8px !important;
    margin: 0 !important;
    cursor: pointer !important;
}}
[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked) {{
    background: #0284C7 !important;
    color: #FFFFFF !important;
    font-weight: 700 !important;
}}
[data-testid="stSidebar"] div[data-testid="stRadio"] label:has(input:checked) * {{
    color: #FFFFFF !important;
}}
[data-testid="stSidebar"] div[data-testid="stRadio"] label:not(:has(input:checked)) * {{
    color: #E2E8F0 !important;
}}
[data-testid="stSidebar"] div[data-testid="stRadio"] input[type="radio"] {{
    display: none !important;
}}

/* กล่องเลือกสายรถบนหน้าจอหลัก */
section.main div[data-baseweb="select"] > div {{
    background: #FFFFFF !important;
    border: 1.5px solid #0284C7 !important;
    border-radius: 10px !important;
    box-shadow: 0 2px 8px rgba(0,0,0,0.1) !important;
}}
section.main div[data-baseweb="select"] * {{
    color: #0F172A !important;
    font-size: {base_font} !important;
    font-weight: 700 !important;
}}
section.main div[data-baseweb="select"] svg {{
    fill: #0F172A !important;
}}

/* ตารางข้อมูล */
.stDataFrame, .stDataFrame * {{
    font-size: {base_font} !important;
}}
.stDataFrame {{
    background: rgba(2, 45, 75, 0.65) !important;
    backdrop-filter: blur(20px);
    padding: 1rem;
    border-radius: 16px;
    border: 1.5px solid rgba(255,255,255,0.3) !important;
    border-top: 4px solid #38BDF8 !important;
    box-shadow: 0 8px 25px rgba(0,20,45,0.35);
}}
.stDataFrame td, .stDataFrame th, .stDataFrame div {{
    color: #0F172A !important;
    font-weight: 500 !important;
}}

.stButton>button {{
    background: linear-gradient(135deg, #D4AF37 0%, #AA8C2C 100%) !important;
    color: #000B18 !important;
    border: none !important;
    border-radius: 10px;
    font-size: {base_font} !important;
    font-weight: 700;
    padding: .6rem 1.4rem;
    width: 100%;
    box-shadow: 0 4px 15px rgba(212,175,55,0.4);
    transition: all .3s;
}}
.stButton>button:hover {{
    background: linear-gradient(135deg, #F3E5AB 0%, #D4AF37 100%) !important;
    box-shadow: 0 6px 20px rgba(255,215,0,0.6);
    transform: translateY(-2px);
}}
[data-testid="stDownloadButton"] > button {{
    background: linear-gradient(135deg, #0284C7 0%, #0369A1 100%) !important;
    color: #FFF !important;
    font-size: {base_font} !important;
    border-radius: 10px !important;
    padding: .8rem 2rem;
    font-weight: 700;
    box-shadow: 0 4px 15px rgba(2,132,199,0.4);
}}
</style>
''', unsafe_allow_html=True)

# ฟังก์ชันสร้างการ์ดตัวเลขสถิติแบบโฟกัสสายตาพร้อมระบบสีตามเงื่อนไข
def render_metric_card(
    label: str,
    value: str,
    delta: str = "",
    status: str = "normal",  # "good" (เขียว), "warning" (เหลือง), "danger" (แดง), "normal" (ฟ้าคราม)
) -> str:
    # กำหนดสีตัวเลขหลัก
    color_map = {
        "good": "#16A34A",       # เขียวสดใส (ปกติ/ดี)
        "warning": "#D97706",    # ส้ม/เหลืองอำพัน (ใกล้เกินเพดาน)
        "danger": "#DC2626",     # แดงชัดเจน (เกินเกณฑ์/วิกฤต)
        "normal": "#0284C7",     # ฟ้าครามสปริงเคิล
    }
    val_color = color_map.get(status, "#0284C7")

    # กำหนดสีของแถบตัวเลข Delta (ถ้ามีติดลบ '-' ให้แดงทันที)
    delta_html = ""
    if delta:
        d_str = str(delta).strip()
        if d_str.startswith("-") or "-" in d_str:
            d_bg, d_color, d_border = "#FEE2E2", "#DC2626", "#FCA5A5"  # แดงสำหรับติดลบ
        elif status == "danger":
            d_bg, d_color, d_border = "#FEE2E2", "#DC2626", "#FCA5A5"
        elif status == "warning":
            d_bg, d_color, d_border = "#FEF3C7", "#D97706", "#FCD34D"  # เหลืองใกล้เพดาน
        elif status == "good":
            d_bg, d_color, d_border = "#DCFCE7", "#16A34A", "#86EFAC"  # เขียวสำหรับปกติ/ดี
        else:
            d_bg, d_color, d_border = "#E0F2FE", "#0369A1", "#BAE6FD"  # ฟ้าครามอ่อน

        delta_html = f'''
        <div style="margin-top: 6px;">
            <span style="background:{d_bg}; color:{d_color}; border:1px solid {d_border}; padding:3px 10px; border-radius:6px; font-weight:700; font-size:calc({base_font} * 0.88); display:inline-block;">
                {delta}
            </span>
        </div>
        '''

    return f'''
    <div style="background:#FFFFFF; border-radius:14px; padding:16px 20px; border:2px solid #38BDF8; border-top:6px solid {val_color}; box-shadow:0 8px 24px rgba(0,15,35,0.25); min-height:115px; margin-bottom:12px;">
        <div style="color:#1E293B; font-size:{metric_lbl_font}; font-weight:700; margin-bottom:4px;">{label}</div>
        <div style="color:{val_color}; font-size:{metric_val_font}; font-weight:800; line-height:1.2;">{value}</div>
        {delta_html}
    </div>
    '''

# ฟังก์ชันสร้างแถบหัวข้อเสมือนเส้นแบ่งเขตสายตาพร้อมพื้นหลังขาวเด่น
def section_header(title: str, subtitle: str = "") -> str:
    sub_html = f"<div style='font-size:{small_font}; color:#475569; font-weight:600; margin-top:3px;'>{subtitle}</div>" if subtitle else ""
    return f"""
    <div style="background:#FFFFFF; border-radius:12px; padding:12px 20px; margin-top:24px; margin-bottom:14px; border-left:6px solid #FFD700; border:1.5px solid #CBD5E1; box-shadow:0 4px 14px rgba(0,15,35,0.15);">
        <div style="font-size:{h2_font}; font-weight:800; color:#024D7B; line-height:1.3;">{title}</div>
        {sub_html}
    </div>
    """

def reset_results():
    for k in ('result', 'zoning_cfg_used'):
        st.session_state.pop(k, None)

def show_loader(placeholder, msg: str):
    try:
        with open("truck.jpg", "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        html = f'<div style="text-align:center; padding:2rem; color:#FFD700; font-weight:bold; border-radius:16px; background:rgba(2,54,88,0.85); backdrop-filter:blur(20px); border:1.5px solid rgba(56,189,248,0.4);"><img src="data:image/jpeg;base64,{b64}" style="width:140px; margin-bottom:10px;"><br>{msg}</div>'
    except FileNotFoundError:
        html = f'<div style="text-align:center; padding:2rem; color:#FFD700; font-weight:bold; border-radius:16px; background:rgba(2,54,88,0.85);">{msg}</div>'
    placeholder.markdown(html, unsafe_allow_html=True)

# =====================================================================================
#  SECTION 9 — DATA IMPORT & MAPPING
# =====================================================================================
st.title("🚛 Smart Route Rebalancer — Production v3.0")
st.markdown("<div style='background:rgba(2,45,75,0.6); display:inline-block; padding:5px 16px; border-radius:12px; border:1px solid rgba(56,189,248,0.3); font-weight:600; color:#E0F2FE;'>ระบบวิเคราะห์และตัดสายส่งน้ำอัตโนมัติ (Zero-Overlap Satellite Pocket Architecture)</div>", unsafe_allow_html=True)

st.sidebar.markdown("---")
st.sidebar.markdown("### 📁 1. นำเข้าข้อมูล")
sheet_url = st.sidebar.text_input("🔗 ลิงก์ Google Sheets:", placeholder="วางลิงก์ที่นี่...", on_change=reset_results)
raw_gid = st.sidebar.text_input("แท็บชีต (GID):", value="0", on_change=reset_results)
gm = re.search(r'gid=([0-9]+)', raw_gid)
sheet_gid = gm.group(1) if gm else ("".join(filter(str.isdigit, raw_gid)) or "0")

@st.cache_data(ttl=300, show_spinner=False)
def load_sheet(url: str, gid: str):
    try:
        m = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
        if not m:
            return None, "ลิงก์ Google Sheets ไม่ถูกต้อง"
        u = f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv&gid={gid}"
        d = pd.read_csv(u, dtype=str)
        if d.empty:
            return None, "ไม่พบข้อมูลในแท็บนี้"
        return d, None
    except Exception as e:
        return None, f"เกิดข้อผิดพลาด: {e}"

df = None
if sheet_url:
    key = f"{sheet_url}::{sheet_gid}"
    if st.session_state.get('raw_key') != key:
        ph = st.empty()
        show_loader(ph, "กำลังเชื่อมต่อฐานข้อมูล... 💧")
        raw, err = load_sheet(sheet_url, sheet_gid)
        st.session_state.update({'raw_df': raw, 'raw_err': err, 'raw_key': key})
        reset_results()
        ph.empty()
    df = st.session_state.get('raw_df')
    if df is None and st.session_state.get('raw_err'):
        st.sidebar.error(f"❌ {st.session_state['raw_err']}")

if df is None or df.empty:
    st.info("👈 กรุณาวางลิงก์ Google Sheets ที่แถบเมนูด้านซ้าย เพื่อเริ่มต้นใช้งาน")
    st.stop()

df = df.copy()
cols = df.columns.tolist()

st.sidebar.markdown("---")
st.sidebar.markdown("### 🧭 2. ยืนยันคอลัมน์ข้อมูล")

def sel(label, keys, allow_none=False):
    g = guess_col(keys, cols, allow_none=allow_none)
    if allow_none:
        opts = ["-- ไม่มี --"] + cols
        i = (cols.index(g) + 1) if g in cols else 0
        v = st.sidebar.selectbox(label, opts, index=i, on_change=reset_results)
        return None if v == "-- ไม่มี --" else v
    i = cols.index(g) if g in cols else 0
    return st.sidebar.selectbox(label, cols, index=i, on_change=reset_results)

vol_col = sel("คอลัมน์ยอด (ถัง/เดือน):", ['ยอด', 'เดือน', 'volume'])
lat_col = sel("คอลัมน์ละติจูด:", ['ละติจูด', 'lat'])
lon_col = sel("คอลัมน์ลองจิจูด:", ['ลอง', 'lon', 'lng'])
truck_col = sel("คอลัมน์เบอร์รถ:", ['เบอร์รถ', 'รถ', 'truck'])
day_col = sel("📅 คอลัมน์วันจัดส่ง:", ['สัปดาห์', 'วัน', 'รอบ', 'day'])
id_col = sel("คอลัมน์รหัสลูกค้า:", ['รหัส', 'id', 'code'])
vip_col = sel("คอลัมน์ VIP/เงื่อนไขพิเศษ:", ['vip', 'เงื่อนไข'], allow_none=True)
name_col = sel("คอลัมน์ชื่อลูกค้า:", ['ชื่อ', 'name'], allow_none=True)

df[lat_col] = pd.to_numeric(df[lat_col], errors='coerce')
df[lon_col] = pd.to_numeric(df[lon_col], errors='coerce')
df[vol_col] = pd.to_numeric(df[vol_col], errors='coerce').fillna(0).round().astype(int)
df[truck_col] = df[truck_col].astype(str).str.strip()
df[id_col] = df[id_col].astype(str).str.strip()
df['VIP_Status'] = df[vip_col].astype(str).str.strip() if vip_col else 'ปกติ'

n0 = len(df)
df = df.dropna(subset=[lat_col, lon_col]).reset_index(drop=True)
df = df[~df[truck_col].str.lower().isin(NO_TRUCK_TOKENS)].reset_index(drop=True)
if n0 - len(df) > 0:
    st.sidebar.warning(f"⚠️ ตัดทิ้ง {n0-len(df)} รายการ (พิกัดว่าง/เบอร์รถว่าง)")
st.sidebar.success(f"✅ โหลดสำเร็จ: {len(df):,} รายการ")

available_trucks = clean_truck_ids(df[truck_col].unique())

# =====================================================================================
#  SECTION 10 — CAPACITY & CONTROL LIMITS
# =====================================================================================
st.sidebar.markdown("---")
st.sidebar.markdown("### 📏 3. เพดานควบคุมของบริษัท")
monthly_cap = st.sidebar.number_input("ความจุอ้างอิง (ถัง/เดือน/คัน) = 100%", 1000.0, 20000.0, DEFAULT_MONTHLY_CAPACITY, 40.0, on_change=reset_results)
daily_cap = st.sidebar.number_input("เพดานยอดส่งต่อวัน (ถัง/วัน)", 50.0, 400.0, float(DEFAULT_DAILY_CONTROL_CAP), 1.0, on_change=reset_results)
max_stops_day = st.sidebar.number_input("เพดานจุดจอดต่อวัน (จุด)", 10, 400, DEFAULT_MAX_STOPS_PER_DAY, 5, on_change=reset_results)
cap_units = daily_cap * DAYS_PER_MONTH

base_cfg = ZoningConfig(lat_col=lat_col, lon_col=lon_col, vol_col=vol_col, truck_col=truck_col,
                        id_col=id_col, day_col=day_col, name_col=name_col,
                        monthly_capacity=monthly_cap, daily_control_cap=daily_cap,
                        max_stops_per_day=int(max_stops_day))

diag = diagnose_fleet(df, base_cfg)
overloaded = diag.loc[diag['สถานะ'] == '🔴 เกินเพดาน', 'เบอร์รถ'].tolist() if not diag.empty else []

st.markdown(section_header("🩺 ผลวินิจฉัยสถานะรถปัจจุบัน (ก่อนปรับ)"), unsafe_allow_html=True)
d1, d2, d3, d4 = st.columns(4)

# 1. จำนวนรถทั้งหมด
d1.markdown(render_metric_card("จำนวนรถทั้งหมด", f"{len(diag)} คัน", status="normal"), unsafe_allow_html=True)

# 2. รถที่เกินเพดาน (ถ้าเกินเป็นแดง)
over_status = "danger" if len(overloaded) > 0 else "good"
d2.markdown(render_metric_card("รถที่เกินเพดาน", f"{len(overloaded)} คัน", delta=f"เพดาน {daily_cap:,.0f} ถัง/วัน", status=over_status), unsafe_allow_html=True)

# 3. ยอดรวมทั้งสาขา
d3.markdown(render_metric_card("ยอดรวมทั้งสาขา", f"{df[vol_col].sum():,.0f} ถัง/เดือน", status="normal"), unsafe_allow_html=True)

# 4. ยอดส่วนเกินที่ต้องย้าย (ถ้ามียอดต้องย้ายเป็นเหลือง/ส้มแจ้งเตือน)
excess_total = float(diag['ส่วนเกิน/วัน'].sum()) * DAYS_PER_MONTH if not diag.empty else 0.0
excess_status = "warning" if excess_total > 0 else "good"
d4.markdown(render_metric_card("ยอดส่วนเกินที่ต้องย้าย", f"{excess_total:,.0f} ถัง/เดือน", delta=f"≈ {math.ceil(excess_total/max(1.0,cap_units))} คันรถ", status=excess_status), unsafe_allow_html=True)

st.dataframe(diag, use_container_width=True, hide_index=True)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🚚 4. เลือกรถต้นทาง (Donors)")
dissolve_trucks = st.sidebar.multiselect("🗑️ ยุบทั้งคัน (กระจายงานออกทั้งหมด)", options=available_trucks, default=[], on_change=reset_results)
relieve_default = [t for t in overloaded if t not in dissolve_trucks]
relieve_trucks = st.sidebar.multiselect("✂️ ดึงงานออกบางส่วน (ลดให้อยู่ในเพดาน)", options=[t for t in available_trucks if t not in dissolve_trucks], default=relieve_default, on_change=reset_results)

new_trucks_raw = st.sidebar.text_input("➕ เบอร์รถคันใหม่ (คั่นด้วยจุลภาค)", value="", placeholder="เช่น 15112, 15113", on_change=reset_results)
new_trucks = [t.strip() for t in new_trucks_raw.split(',') if t.strip()]
new_trucks = [t for t in dict.fromkeys(new_trucks) if t not in available_trucks]

vol_by_truck_all = df.groupby(truck_col)[vol_col].sum().to_dict()
kept_trucks = [t for t in available_trucks if t not in dissolve_trucks]
_, leftover_probe = compute_default_targets(vol_by_truck_all, dissolve_trucks, kept_trucks, new_trucks, cap_units)
if leftover_probe > 1e-6:
    need = math.ceil(leftover_probe / cap_units)
    st.sidebar.error(f"🚨 ความจุไม่พอ ขาดอีก {leftover_probe:,.0f} ถัง/เดือน — เพิ่มรถใหม่อีก **{need} คัน**")

active_trucks = kept_trucks + new_trucks
if not active_trucks:
    st.error("❌ ไม่เหลือรถสำหรับจัดสรรงาน")
    st.stop()

# =====================================================================================
#  SECTION 11 — SLIDERS & ADVANCED PARAMETERS
# =====================================================================================
st.sidebar.markdown("---")
st.sidebar.markdown("### 🎛️ 5. เป้าหมายรายคัน (%)")
fingerprint = "|".join([sheet_url, sheet_gid, vol_col, truck_col, day_col, str(sorted(dissolve_trucks)), str(sorted(relieve_trucks)), str(new_trucks), f"{monthly_cap}", f"{daily_cap}"])

if st.sidebar.button("🔄 คำนวณเป้าหมายอัตโนมัติ"):
    st.session_state.pop('slider_fp', None)
    reset_results()

if st.session_state.get('slider_fp') != fingerprint:
    for k in [k for k in list(st.session_state.keys()) if k.startswith('slider_') or k.startswith('lock_')]:
        del st.session_state[k]
    tgt_units, _ = compute_default_targets(vol_by_truck_all, dissolve_trucks, kept_trucks, new_trucks, cap_units)
    st.session_state.truck_pcts = {t: float(round(max(0.0, min(200.0, tgt_units.get(t, 0.0) / monthly_cap * 100)), 1)) for t in active_trucks}
    for t in active_trucks:
        st.session_state[f"slider_{t}"] = st.session_state.truck_pcts[t]
    st.session_state['slider_fp'] = fingerprint

def on_slider_change(changed: str):
    new_val = max(0.0, min(200.0, st.session_state.get(f"slider_{changed}", 0.0)))
    old = st.session_state.truck_pcts.get(changed, new_val)
    diff = new_val - old
    if abs(diff) < 0.01:
        return
    free = [t for t in active_trucks if t != changed and not st.session_state.get(f"lock_{t}", False)]
    if free:
        share = diff / len(free)
        for t in free:
            v = round(max(0.0, min(200.0, st.session_state.truck_pcts.get(t, 0.0) - share)), 1)
            st.session_state.truck_pcts[t] = v
            st.session_state[f"slider_{t}"] = v
    st.session_state.truck_pcts[changed] = round(new_val, 1)
    reset_results()

target_pcts: Dict[str, float] = {}
for t in active_trucks:
    c1, c2 = st.sidebar.columns([3, 1.2])
    with c2:
        st.checkbox("🔒", key=f"lock_{t}", on_change=reset_results)
    with c1:
        v = st.slider(f"{'🆕 ' if t in new_trucks else ''}รถ {t} (%)", 0.0, 200.0, step=0.1, key=f"slider_{t}", on_change=on_slider_change, args=(t,))
        target_pcts[t] = v
        st.session_state.truck_pcts[t] = v

st.sidebar.markdown("---")
st.sidebar.markdown("### 🔒 6. ล็อก Key Account & กฎ")
manual_vips = st.sidebar.multiselect("รหัสลูกค้าที่ห้ามย้ายสาย", options=df[id_col].unique().tolist(), default=[], on_change=reset_results)
core_ratio_pct = st.sidebar.slider("สัดส่วนแกนกลางที่ล็อก (Core %)", 0, 100, 65, 5, on_change=reset_results)
tol_pct = st.sidebar.number_input("ค่าเผื่อเป้าหมาย (%)", 0.0, 50.0, 5.0, 0.5, on_change=reset_results)

cfg = ZoningConfig(lat_col=lat_col, lon_col=lon_col, vol_col=vol_col, truck_col=truck_col,
                    id_col=id_col, day_col=day_col, name_col=name_col,
                    monthly_capacity=monthly_cap, daily_control_cap=daily_cap,
                    max_stops_per_day=int(max_stops_day), core_ratio=float(core_ratio_pct),
                    tol_pct=float(tol_pct))

# =====================================================================================
#  SECTION 12 — EXECUTE ENGINE
# =====================================================================================
if st.sidebar.button("🚀 ประมวลผลจัดสายส่งใหม่", use_container_width=True):
    ph = st.empty()
    show_loader(ph, "กำลังประมวลผลจัดกลุ่มเส้นทางอัจฉริยะ (Consolidating Satellite Pockets)... 💧")
    res = run_multi_donor_zoning(df, cfg, target_pcts, dissolve_trucks, relieve_trucks, new_trucks, manual_vips)
    st.session_state['result'] = res
    st.session_state['zoning_cfg_used'] = cfg
    ph.empty()

# =====================================================================================
#  SECTION 13 — RESULTS & EXECUTIVE COMPARISON MAP
# =====================================================================================
if 'result' in st.session_state:
    res: ZoningResult = st.session_state['result']
    rdf = res.result_df

    st.markdown("---")
    st.markdown(section_header("📈 ตัวชี้วัดผลลัพธ์เพื่อการตัดสินใจของผู้บริหาร (Executive KPIs)"), unsafe_allow_html=True)
    k1, k2, k3, k4 = st.columns(4)

    # 1. รถเกินเพดาน (ถ้าเป็น 0 ถือว่าดี = เขียว, ถ้าเหลือคันเกินเพดาน = แดง)
    over_after = int(res.metrics['over_after'])
    over_diff = int(res.metrics['over_after'] - res.metrics['over_before'])
    k1_status = "good" if over_after == 0 else "danger"
    k1.markdown(render_metric_card("รถเกินเพดาน", f"{over_after} คัน", delta=f"{over_diff:+d}", status=k1_status), unsafe_allow_html=True)

    # 2. โหลดสูงสุด (ถ้าเกินเพดาน = แดง, ถ้าใกล้เพดาน 140-156 = เหลือง, ถ้าน้อยกว่านั้น = เขียว)
    peak_after = res.metrics['peak_after']
    peak_diff = res.metrics['peak_after'] - res.metrics['peak_before']
    if peak_after > cfg.daily_control_cap:
        k2_status = "danger"
    elif peak_after >= OPTIMAL_MIN:
        k2_status = "warning"
    else:
        k2_status = "good"
    k2.markdown(render_metric_card("โหลดสูงสุด", f"{peak_after:,.0f} ถัง/วัน", delta=f"{peak_diff:,.0f} ถัง", status=k2_status), unsafe_allow_html=True)

    # 3. ความกระชับของโซน
    compact_diff = res.metrics['compact_after_km'] - res.metrics['compact_before_km']
    k3.markdown(render_metric_card("ความกระชับของโซน", f"{res.metrics['compact_after_km']:.2f} กม.", delta=f"{compact_diff:+.2f} กม.", status="normal"), unsafe_allow_html=True)

    # 4. ลูกค้าที่โยกย้าย
    k4.markdown(render_metric_card("ลูกค้าที่โยกย้าย", f"{int(res.metrics['moved_cust']):,} ราย", delta=f"{res.metrics['moved_pct']:.1f}% ของสาขา", status="normal"), unsafe_allow_html=True)

    for w in res.warnings:
        st.warning(f"⚠️ {w}")

    # ---------------------------------------------------------------------------------
    # 🗺️ EXECUTIVE COMPARISON MAPS (BEFORE VS. AFTER — NO WATERMARK)
    # ---------------------------------------------------------------------------------
    st.markdown("---")
    
    # 🛑 แถบหัวข้อแผนที่พร้อมพื้นหลังขาวเด่นชัด ไม่จมหาย
    st.markdown(section_header("🗺️ แผนที่เปรียบเทียบเชิงพื้นที่ (Before vs. After Comparison)", "คลิกที่หมุดแต่ละจุดเพื่อดูรหัสสมาชิก, ชื่อลูกค้า, ยอดรับน้ำเฉลี่ย และการเปลี่ยนสายส่ง (เวิ้งโดดเดี่ยวถูกรวมเป็นคันเดียว)"), unsafe_allow_html=True)

    distinct_colors = [
        '#2563EB', '#16A34A', '#F59E0B', '#9333EA', '#0284C7',
        '#14B8A6', '#6366F1', '#84CC16', '#EC4899', '#06B6D4',
        '#D97706', '#4F46E5', '#10B981', '#F43F5E', '#8B5CF6'
    ]

    all_truck_keys = sorted(list(set(clean_truck_ids(df[truck_col].unique()) + active_trucks)))
    color_map: Dict[str, str] = {}
    palette_idx = 0

    for t in all_truck_keys:
        if t in new_trucks:
            color_map[t] = '#DC2626'
        else:
            color_map[t] = distinct_colors[palette_idx % len(distinct_colors)]
            palette_idx += 1
    color_map[OVERFLOW_LABEL] = '#64748B'

    # 🛑 กรอบควบคุมการเลือกสายรถและป้ายสีคำอธิบาย (Legend) พร้อมพื้นหลังขาวคมชัด
    col_filter1, col_filter2 = st.columns([2, 3])
    with col_filter1:
        map_view_opts = ["แสดงรถทั้งหมด (แยกสีตามเบอร์รถ)"] + active_trucks
        selected_truck_view = st.selectbox("🔍 เลือกรถที่ต้องการตรวจสอบเป็นพิเศษ:", options=map_view_opts)
    
    with col_filter2:
        # สร้างแถบคำอธิบายสีสายรถบนการ์ดขาวเด่นชัด
        legend_badges_html = "".join([
            f"<span style='display:inline-block; background:#FFFFFF; color:{color_map.get(t, '#0284C7')}; border:2px solid {color_map.get(t, '#0284C7')}; padding:5px 12px; border-radius:8px; font-weight:800; font-size:{base_font}; margin:3px 5px; box-shadow:0 2px 6px rgba(0,0,0,0.12);'>● รถ {t}</span>"
            for t in active_trucks
        ])
        st.markdown(f"""
        <div style="background:#FFFFFF; border-radius:10px; padding:8px 14px; border:1.5px solid #0284C7; box-shadow:0 2px 8px rgba(0,0,0,0.1); display:flex; flex-wrap:wrap; align-items:center; margin-top:28px;">
            <span style="font-size:{base_font}; font-weight:800; color:#0F172A; margin-right:8px;">สีสายรถ:</span>
            {legend_badges_html}
        </div>
        """, unsafe_allow_html=True)

    if selected_truck_view == "แสดงรถทั้งหมด (แยกสีตามเบอร์รถ)":
        display_df_before = df
        display_df_after = rdf[rdf['เบอร์รถใหม่'] != OVERFLOW_LABEL]
    else:
        display_df_before = df[df[truck_col] == selected_truck_view]
        display_df_after = rdf[rdf['เบอร์รถใหม่'] == selected_truck_view]

    center_lat = float(rdf[lat_col].mean()) if not rdf.empty else 13.7563
    center_lon = float(rdf[lon_col].mean()) if not rdf.empty else 100.5018

    map_col1, map_col2 = st.columns(2)

    def create_popup_html(row, is_after: bool = False) -> str:
        c_id = str(row.get(id_col, "-"))
        c_name = str(row.get(name_col, "-")) if name_col and name_col in row else "-"
        vol_m = float(pd.to_numeric(row.get(vol_col), errors="coerce") or 0.0)
        orig_t = str(row.get(truck_col, "-")).strip()
        new_t = str(row.get("เบอร์รถใหม่", orig_t)).strip() if is_after else orig_t
        orig_day = str(row.get(day_col, "-"))
        new_day = str(row.get("วันจัดส่ง(ใหม่)", orig_day)) if is_after else orig_day
        status_txt = str(row.get("สถานะ", "คงเดิม")) if is_after else "ต้นฉบับ"
        is_vip = bool(row.get("is_vip_locked", False))

        avg_day_vol = vol_m / (4.333 * max(1, len(parse_days_from_string(new_day)[0] or [1])))

        html = f"""
        <div style="font-family:'Sarabun',sans-serif; font-size:13px; color:#0F172A; line-height:1.5; min-width:200px;">
            <div style="font-size:14px; font-weight:bold; color:#002D62; border-bottom:1px solid #CBD5E1; padding-bottom:4px; margin-bottom:6px;">
                รหัสสมาชิก: {c_id} {'<span style="color:#D4AF37; font-weight:bold;">[VIP]</span>' if is_vip else ''}
            </div>
            {"<b>ชื่อ:</b> " + c_name + "<br>" if c_name != "-" else ""}
            <b>ยอดรับน้ำ:</b> <span style="color:#2563EB; font-weight:bold;">{vol_m:,.0f} ถัง/เดือน</span><br>
            <b>เฉลี่ยต่องวดส่ง:</b> ≈ {avg_day_vol:,.1f} ถัง/รอบ<br>
            <div style="background:#F1F5F9; padding:5px 8px; border-radius:6px; margin-top:6px; border:1px solid #E2E8F0;">
                <b>สายรถ:</b> <span style="color:{color_map.get(new_t if is_after else orig_t, '#000')}; font-weight:bold;">
                    {orig_t if not is_after else f"{orig_t} → {new_t}"}
                </span><br>
                <b>วันจัดส่ง:</b> {orig_day if not is_after else new_day}<br>
                <b>สถานะ:</b> {status_txt}
            </div>
        </div>
        """
        return html

    # --- 1. แผนที่ก่อนปรับ (Before) ---
    with map_col1:
        st.markdown(f"<div style='text-align:center; background:#FFFFFF; color:#024D7B; font-weight:800; font-size:{base_font}; padding:8px 12px; border-radius:8px; margin-bottom:10px; border:1.5px solid #38BDF8; box-shadow:0 2px 8px rgba(0,0,0,0.1);'>📍 โซนสายส่งเดิม (Before - ก่อนปรับปรุง)</div>", unsafe_allow_html=True)
        m_before = folium.Map(location=[center_lat, center_lon], zoom_start=12, tiles="OpenStreetMap")
        plugins.Fullscreen(position='topright').add_to(m_before)

        for _, r in display_df_before.iterrows():
            t_id = str(r[truck_col]).strip()
            color = color_map.get(t_id, "#64748B")
            is_vip = str(r.get(id_col, "")).strip() in manual_vips or str(r.get("VIP_Status", "")).upper() == "VIP"
            popup = folium.Popup(create_popup_html(r, is_after=False), max_width=300)

            folium.CircleMarker(
                location=[r[lat_col], r[lon_col]],
                radius=8 if is_vip else 5,
                color="#FFD700" if is_vip else color,
                weight=2.5 if is_vip else 1,
                fill=True,
                fillColor=color,
                fill_opacity=0.85,
                popup=popup
            ).add_to(m_before)

        components.html(m_before.get_root().render(), height=500)

    # --- 2. แผนที่หลังปรับ (After) ---
    with map_col2:
        st.markdown(f"<div style='text-align:center; background:#FFFFFF; color:#024D7B; font-weight:800; font-size:{base_font}; padding:8px 12px; border-radius:8px; margin-bottom:10px; border:1.5px solid #38BDF8; box-shadow:0 2px 8px rgba(0,0,0,0.1);'>✨ โซนสายส่งใหม่ (After - รวมเวิ้งงานโดดเดี่ยวแล้ว)</div>", unsafe_allow_html=True)
        m_after = folium.Map(location=[center_lat, center_lon], zoom_start=12, tiles="OpenStreetMap")
        plugins.Fullscreen(position='topright').add_to(m_after)

        for _, r in display_df_after.iterrows():
            t_new = str(r["เบอร์รถใหม่"]).strip()
            color = color_map.get(t_new, "#64748B")
            is_vip = bool(r.get("is_vip_locked", False))
            popup = folium.Popup(create_popup_html(r, is_after=True), max_width=300)

            folium.CircleMarker(
                location=[r[lat_col], r[lon_col]],
                radius=8 if is_vip else 5,
                color="#FFD700" if is_vip else color,
                weight=2.5 if is_vip else 1,
                fill=True,
                fillColor=color,
                fill_opacity=0.85,
                popup=popup
            ).add_to(m_after)

        components.html(m_after.get_root().render(), height=500)

    # ---------------------------------------------------------------------------------
    # 📅 ตารางสรุปโหลดรายวัน (จันทร์-เสาร์) & ตารางสรุปภาพรวม
    # ---------------------------------------------------------------------------------
    st.markdown("---")
    st.markdown(section_header("📅 ตารางวิเคราะห์โหลดรายวัน (จันทร์ - เสาร์)"), unsafe_allow_html=True)
    daily_rows = []
    for t in active_trucks:
        d_vals = res.final_daily.get(t, np.zeros(WORKING_DAYS))
        daily_rows.append({
            "เบอร์รถ": t,
            "จันทร์": int(round(d_vals[0])),
            "อังคาร": int(round(d_vals[1])),
            "พุธ": int(round(d_vals[2])),
            "พฤหัสฯ": int(round(d_vals[3])),
            "ศุกร์": int(round(d_vals[4])),
            "เสาร์": int(round(d_vals[5])),
            "โหลดสูงสุด (ถัง/วัน)": int(round(d_vals.max())),
            "สถานะ": "🟢 ผ่านเกณฑ์" if d_vals.max() <= cfg.daily_control_cap else "🔴 เกินเกณฑ์"
        })
    st.dataframe(pd.DataFrame(daily_rows), use_container_width=True, hide_index=True)

    st.markdown(section_header("📋 ตารางรายละเอียดการโยกย้ายลูกค้าทั้งหมด"), unsafe_allow_html=True)
    final_cols = [id_col]
    if name_col and name_col in rdf.columns:
        final_cols.append(name_col)
    final_cols.extend([vol_col, truck_col, "เบอร์รถใหม่", day_col, "วันจัดส่ง(ใหม่)", "สถานะการย้ายวัน", "สถานะ"])
    
    st.dataframe(rdf[final_cols].rename(columns={truck_col: "เบอร์รถเดิม"}), use_container_width=True)

    csv_data = rdf[final_cols].to_csv(index=False).encode('utf-8-sig')
    st.download_button("📥 ดาวน์โหลดผลการจัดสายส่งฉบับสมบูรณ์ (CSV เพื่อเปิดใน Excel)", csv_data, 'sprinkle_rebalance_v3_0.csv', 'text/csv', use_container_width=True)
