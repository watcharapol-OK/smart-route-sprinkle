# =====================================================================================
#  SMART ROUTE REBALANCER  —  PRODUCTION BUILD v3.0  (SINGLE FILE)
#  ระบบปรับสมดุลสายส่งน้ำหลายคันพร้อมกัน + ตัวแก้ปัญหายอดเกินเพดานเชิงต้นทุน
#  ---------------------------------------------------------------------------------
#  วิธีใช้:  streamlit run app.py
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
import html as _html
import json
import math
import re
import time
from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import folium
from folium import plugins

try:
    from scipy.spatial import cKDTree
    HAS_SCIPY = True
except Exception:
    HAS_SCIPY = False

st.set_page_config(page_title="Smart Route Rebalancer v3",
                   page_icon="🚛", layout="wide",
                   initial_sidebar_state="expanded")

# =====================================================================================
#  SECTION 1 — CONSTANTS & DESIGN TOKENS
# =====================================================================================
WORKING_DAYS = 6
WEEKS_PER_MONTH = 4.333
DAYS_PER_MONTH = WORKING_DAYS * WEEKS_PER_MONTH

DEFAULT_MONTHLY_CAPACITY = 4160.0
DEFAULT_DAILY_CONTROL_CAP = 156.0
DEFAULT_MAX_STOPS_PER_DAY = 90

OVERFLOW_LABEL = 'ส่วนเกิน (Overflow)'
NO_TRUCK_TOKENS = {'', 'nan', 'none', 'null', '-', 'ไม่ระบุ', 'na', 'n/a'}

OPTIMAL_MIN, OPTIMAL_MAX = 140, 155
AVOID_MIN, AVOID_MAX = 121, 139
TARGET_DAY_CAP = 148
ESCALATE_THRESHOLD = 160
ESCALATE_TARGET_MIN, ESCALATE_TARGET_MAX = 180, 190

EARTH_RADIUS_M = 6371008.8

DAY_NAMES = {0: 'จันทร์', 1: 'อังคาร', 2: 'พุธ', 3: 'พฤหัสบดี', 4: 'ศุกร์', 5: 'เสาร์'}
DAY_SHORT = {0: 'จ', 1: 'อ', 2: 'พ', 3: 'พฤ', 4: 'ศ', 5: 'ส'}
DAY_COLORS = {0: '#FFD166', 1: '#F472B6', 2: '#4ADE80',
              3: '#FB923C', 4: '#38BDF8', 5: '#A78BFA'}

DAY_TOKENS: List[Tuple[str, int]] = [
    ('จันทร์', 0), ('อังคาร', 1), ('พฤหัสบดี', 3), ('พฤหัสฯ', 3), ('พฤหัส', 3),
    ('พฤ', 3), ('พุธ', 2), ('ศุกร์', 4), ('เสาร์', 5),
    ('mon', 0), ('tue', 1), ('wed', 2), ('thu', 3), ('fri', 4), ('sat', 5),
    ('จ', 0), ('อ', 1), ('พ', 2), ('ศ', 4), ('ส', 5),
]
ALL_DAYS_TOKENS = ('ทุกวัน', 'จ-ส', 'จันทร์-เสาร์', 'จ.-ส.', 'ทุกวันทำการ')

# ---- Design tokens (ใช้ร่วมกันทั้ง CSS และ HTML table) ----
C_TEXT = '#E8EEF7'
C_TEXT_DIM = '#A8B8CE'
C_GOLD = '#FFD166'
C_GOLD_SOFT = '#F5DEA3'
C_BLUE = '#7DD3FC'
C_GREEN = '#4ADE80'
C_AMBER = '#FBBF24'
C_RED = '#F87171'
C_PURPLE = '#C4B5FD'

# =====================================================================================
#  SECTION 2 — PURE HELPERS
# =====================================================================================
def parse_days_from_string(val_str) -> Tuple[List[int], str]:
    """แปลงข้อความวันจัดส่ง -> (list index วัน 0-5, สถานะ 'ok'|'empty'|'unparsed')

    แก้บั๊กเดิม: regex ที่มี |1) |2) ทำให้ "สัปดาห์ 12" ถูกตีเป็นจันทร์+อังคาร
    และ typo ',ศ$' ในเงื่อนไขวันเสาร์ รวมถึงการคืน 'ทุกวัน' เงียบๆ เมื่ออ่านไม่ออก
    """
    raw = '' if val_str is None else str(val_str)
    val = raw.strip().lower().replace(' ', '')
    if val in NO_TRUCK_TOKENS:
        return [], 'empty'
    if any(tok in val for tok in ALL_DAYS_TOKENS):
        return list(range(WORKING_DAYS)), 'ok'

    days: set = set()
    for tok in re.split(r'[,\|/\+\-\s;]+', val):
        tok = tok.strip('.').strip()
        if not tok:
            continue
        if tok.isdigit():
            n = int(tok)
            if 1 <= n <= WORKING_DAYS:
                days.add(n - 1)
            continue
        for name, d in DAY_TOKENS:
            if name in tok:
                days.add(d)
                break
    if not days:
        return [], 'unparsed'
    return sorted(days), 'ok'

def format_days_to_string(days_list: Sequence[int]) -> str:
    if not days_list:
        return 'ไม่ระบุ'
    d = sorted({int(x) for x in days_list})
    if len(d) == WORKING_DAYS:
        return 'จ-ส'
    return ', '.join(DAY_NAMES[x] for x in d)

def format_days_short(days_list: Sequence[int]) -> str:
    if not days_list:
        return '-'
    d = sorted({int(x) for x in days_list})
    if len(d) == WORKING_DAYS:
        return 'จ-ส'
    return ''.join(DAY_SHORT[x] for x in d)

def project_xy(lat, lon, lat0: Optional[float] = None):
    """แปลง lat/lon -> ระนาบ x,y หน่วยเมตร (equirectangular)

    แก้บั๊กเดิม: การใช้ (dlat²+dlon²) ตรงๆ ทำให้ระยะแนวตะวันออก-ตกผิดสัดส่วน
    และผสมกับระยะทางถนนจริง (เมตร) ไม่ได้เพราะคนละหน่วย
    """
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    if lat0 is None:
        lat0 = float(np.nanmean(lat))
    k = math.cos(math.radians(lat0))
    return np.radians(lon) * EARTH_RADIUS_M * k, np.radians(lat) * EARTH_RADIUS_M, lat0

def knn_indices(xy: np.ndarray, k: int) -> np.ndarray:
    """เพื่อนบ้านใกล้สุด k ตัว — ใช้ KDTree O(n log n) แทน distance matrix O(n²)"""
    n = len(xy)
    k = int(min(k, max(0, n - 1)))
    if k <= 0:
        return np.zeros((n, 0), dtype=int)
    if HAS_SCIPY:
        tree = cKDTree(xy)
        _, idx = tree.query(xy, k=k + 1, workers=-1)
        return np.atleast_2d(idx)[:, 1:]
    out = np.zeros((n, k), dtype=int)
    CH = 512
    for s in range(0, n, CH):
        e = min(n, s + CH)
        d = ((xy[s:e, None, :] - xy[None, :, :]) ** 2).sum(axis=2)
        for i in range(e - s):
            d[i, s + i] = np.inf
        out[s:e] = np.argpartition(d, k, axis=1)[:, :k]
    return out

def kmeans_seeds(xy: np.ndarray, weights: np.ndarray, k: int,
                 iters: int = 25, seed: int = 42) -> np.ndarray:
    """k-means++ ถ่วงน้ำหนักด้วยยอด — ใช้วาง seed ของรถใหม่หลายคันให้กระจายกัน"""
    n = len(xy)
    k = max(1, min(k, n))
    rng = np.random.default_rng(seed)
    w = np.where(np.asarray(weights, dtype=float) > 0, weights, 1e-9)

    centers = [xy[rng.choice(n, p=w / w.sum())]]
    for _ in range(k - 1):
        d2 = np.min(((xy[:, None, :] - np.array(centers)[None, :, :]) ** 2).sum(2), axis=1)
        p = d2 * w
        p = p / p.sum() if p.sum() > 0 else np.full(n, 1.0 / n)
        centers.append(xy[rng.choice(n, p=p)])
    C = np.array(centers, dtype=float)

    for _ in range(iters):
        lab = ((xy[:, None, :] - C[None, :, :]) ** 2).sum(2).argmin(axis=1)
        newC = C.copy()
        for j in range(k):
            m = lab == j
            if m.any():
                newC[j] = np.average(xy[m], axis=0, weights=w[m])
        if np.allclose(newC, C, atol=1e-3):
            C = newC
            break
        C = newC
    return C

def clean_truck_ids(values: Sequence) -> List[str]:
    out = []
    for v in values:
        s = str(v).strip()
        if s.lower() not in NO_TRUCK_TOKENS:
            out.append(s)
    return sorted(set(out))

def guess_col(substrings: Sequence[str], cols: Sequence[str],
              fallback: Optional[str] = None, allow_none: bool = False) -> Optional[str]:
    """เดาคอลัมน์จากคำในชื่อ

    แก้บั๊กร้ายแรงเดิม: `return fallback if fallback is not None else cols[0]`
    ทำให้เรียกด้วย fallback=None แล้วได้ cols[0] เสมอ -> คอลัมน์ VIP/ชื่อ
    ถูกเดาเป็นคอลัมน์แรกของชีตโดยอัตโนมัติ (มักเป็น 'ลำดับ')
    """
    for c in cols:
        if any(s.lower() in str(c).lower() for s in substrings):
            return c
    if allow_none:
        return None
    return fallback if fallback is not None else (cols[0] if len(cols) else None)

# =====================================================================================
#  SECTION 3 — DATACLASSES
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
    tol_mode: str = 'target'
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
    daily_safety_buffer: float = 0.0

    use_road: bool = False
    road_provider: str = 'osrm'
    osrm_url: str = 'https://router.project-osrm.org'
    gmaps_key: str = ''

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

@dataclass
class TripEconomics:
    """แบบจำลองต้นทุนขั้นบันได — หัวใจคือ 'จำนวนเที่ยว' ไม่ใช่ 'จำนวนถัง'"""
    trip_capacity: float = 78.0
    trips_normal: int = 2
    cost_per_trip: float = 450.0
    cost_per_km: float = 8.5
    cost_per_new_stop: float = 25.0
    admin_cost_cross: float = 60.0
    admin_cost_biweekly: float = 40.0
    util_bad: float = 0.35
    util_ok: float = 0.70
    cliff_warn_gap: float = 8.0

    @property
    def soft_cap(self) -> float:
        return self.trip_capacity * self.trips_normal

    def trips_for(self, load: float) -> int:
        return max(1, int(math.ceil(load / self.trip_capacity - 1e-9))) if load > 0 else 0

    def last_trip_load(self, load: float) -> float:
        n = self.trips_for(load)
        return load - (n - 1) * self.trip_capacity if n > 0 else 0.0

    def last_trip_util(self, load: float) -> float:
        return self.last_trip_load(load) / self.trip_capacity if load > 0 else 0.0

    def cost_per_barrel_last_trip(self, load: float) -> float:
        ltl = self.last_trip_load(load)
        return self.cost_per_trip / ltl if ltl > 0 else float('inf')

@dataclass
class ResolverConfig:
    max_interval_days: int = 4
    marginal_window: float = 40.0
    overshoot_penalty: float = 12.0
    max_detour_m: float = 3500.0
    target_day_buffer: float = 2.0
    enable_shift: bool = True
    enable_split: bool = True
    enable_cross: bool = True
    enable_biweekly: bool = True
    enable_swap: bool = True
    min_split_qty: float = 3.0
    protect_vip: bool = True
    max_moves_per_day: int = 4
    candidate_pool: int = 60

@dataclass
class MoveCandidate:
    kind: str
    cust_idx: int
    cust_id: str
    cust_name: str
    from_truck: str
    from_day: int
    to_truck: str
    to_day: int
    qty: float
    detour_m: float
    cost: float
    partner_idx: Optional[int] = None
    partner_qty: float = 0.0
    note: str = ''
    risk: str = 'ต่ำ'

# =====================================================================================
#  SECTION 4 — ROAD DISTANCE PROVIDERS
# =====================================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_osrm_matrix(source_coords: tuple, dest_coords: tuple,
                      base_url: str, max_coords: int = 95):
    """OSRM /table — แบ่งก้อน source ให้ (batch + n_dest) ไม่เกิน limit ของ server

    แก้บั๊กเดิม: ยัด source+dest ทั้งหมดใน request เดียว ซึ่ง demo server
    จำกัดราว 100 พิกัด ทำให้ข้อมูลจริงหลักร้อยจุดพังทุกครั้งแล้ว fallback เงียบๆ
    """
    import requests
    src, dest = list(source_coords), list(dest_coords)
    n_dst = len(dest)
    if n_dst == 0 or not src:
        return None, 'ไม่มีพิกัดปลายทาง'
    batch = max(1, max_coords - n_dst)
    out = np.full((len(src), n_dst), np.nan, dtype=float)

    for start in range(0, len(src), batch):
        chunk = src[start:start + batch]
        all_c = chunk + dest
        coord_str = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in all_c)
        try:
            r = requests.get(
                f"{base_url.rstrip('/')}/table/v1/driving/{coord_str}",
                params={"sources": ";".join(str(i) for i in range(len(chunk))),
                        "destinations": ";".join(str(i) for i in range(len(chunk), len(all_c))),
                        "annotations": "distance"}, timeout=40)
            r.raise_for_status()
            data = r.json()
            if data.get("code") != "Ok":
                return None, f"OSRM code={data.get('code')}"
            out[start:start + len(chunk), :] = np.array(data["distances"], dtype=float)
        except Exception as e:
            return None, f"OSRM error: {e}"
        time.sleep(0.35)
    return out, ''

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_google_matrix(source_coords: tuple, dest_coords: tuple, api_key: str):
    """Google Distance Matrix — คุม elements/request ไม่เกิน 100

    แก้บั๊กเดิม: CHUNK=25 คงที่ + ส่ง dest ทั้งหมด -> รถ 5 คันขึ้นไป = 125 elements
    เกิน limit ทันที ได้ MAX_ELEMENTS_EXCEEDED แล้ว fallback เงียบๆ
    """
    import requests
    MAX_ELEMENTS, MAX_ORIGINS = 100, 25
    src, dest = list(source_coords), list(dest_coords)
    n_src, n_dst = len(src), len(dest)
    if n_src == 0 or n_dst == 0:
        return None, 'ไม่มีข้อมูลพิกัด'

    chunk = max(1, min(MAX_ORIGINS, MAX_ELEMENTS // n_dst))
    dist = np.full((n_src, n_dst), np.nan, dtype=float)
    dest_str = "|".join(f"{lat:.6f},{lon:.6f}" for lat, lon in dest)

    for start in range(0, n_src, chunk):
        part = src[start:start + chunk]
        try:
            r = requests.get(
                "https://maps.googleapis.com/maps/api/distancematrix/json",
                params={"origins": "|".join(f"{lat:.6f},{lon:.6f}" for lat, lon in part),
                        "destinations": dest_str, "key": api_key, "mode": "driving"},
                timeout=40)
            r.raise_for_status()
            data = r.json()
            if data.get("status") != "OK":
                return None, f"Google status={data.get('status')} {data.get('error_message','')}"
            for i, row in enumerate(data["rows"]):
                for j, el in enumerate(row["elements"]):
                    if el.get("status") == "OK":
                        dist[start + i, j] = el["distance"]["value"]
        except Exception as e:
            return None, f"Google error: {e}"
    return dist, ''

# =====================================================================================
#  SECTION 5 — CAPACITY PLANNING & DIAGNOSTIC
# =====================================================================================
def compute_default_targets(vol_by_truck: Dict[str, float], dissolve: Sequence[str],
                            keep: Sequence[str], new_trucks: Sequence[str],
                            cap_units: float) -> Tuple[Dict[str, float], float]:
    """ตัดยอดส่วนเกินออกจากคันที่เกินเพดาน แล้วเกลี่ยลงรถใหม่

    คืน (targets, leftover) — leftover > 0 แปลว่ารถไม่พอ ต้องเพิ่มอีก
    """
    pool = float(sum(vol_by_truck.get(t, 0.0) for t in dissolve))
    tgt: Dict[str, float] = {}
    for t in keep:
        v = float(vol_by_truck.get(t, 0.0))
        if v > cap_units:
            pool += v - cap_units
            tgt[t] = cap_units
        else:
            tgt[t] = v
    for t in new_trucks:
        tgt[t] = 0.0
    for t in new_trucks:
        if pool <= 1e-6:
            break
        take = min(cap_units, pool)
        tgt[t] += take
        pool -= take
    for _ in range(60):
        if pool <= 1e-6:
            break
        head = {t: cap_units - tgt[t] for t in tgt if cap_units - tgt[t] > 1e-6}
        if not head:
            break
        share = min(1.0, pool / sum(head.values()))
        for t, h in head.items():
            tgt[t] += h * share
            pool -= h * share
    return tgt, max(0.0, pool)

def diagnose_fleet(df: pd.DataFrame, cfg: ZoningConfig, econ: TripEconomics) -> pd.DataFrame:
    rows = []
    for t, g in df.groupby(cfg.truck_col):
        t = str(t).strip()
        if t.lower() in NO_TRUCK_TOKENS:
            continue
        daily = np.zeros(WORKING_DAYS)
        stops = np.zeros(WORKING_DAYS)
        for _, r in g.iterrows():
            days, _ = parse_days_from_string(r[cfg.day_col])
            days = days or list(range(WORKING_DAYS))
            per = float(r[cfg.vol_col]) / len(days) / WEEKS_PER_MONTH
            for d in days:
                daily[d] += per
                stops[d] += 1
        peak = float(daily.max())
        extra_trips = sum(max(0, econ.trips_for(v) - econ.trips_normal) for v in daily)
        rows.append({
            'เบอร์รถ': t,
            'ลูกค้า': int(len(g)),
            'ยอด/เดือน': int(g[cfg.vol_col].sum()),
            'ภาระงาน(%)': round(g[cfg.vol_col].sum() / cfg.monthly_capacity * 100, 1),
            'โหลดสูงสุด/วัน': int(round(peak)),
            'จุดจอดสูงสุด/วัน': int(stops.max()),
            'เที่ยวพิเศษ/สัปดาห์': int(extra_trips),
            'ส่วนเกิน/วัน': int(round(max(0.0, peak - cfg.daily_control_cap))),
            'สถานะ': ('🔴 เกินเพดาน' if peak > cfg.daily_control_cap
                      else ('🟢 เหมาะสม' if peak >= OPTIMAL_MIN
                            else ('🟡 ควรเลี่ยง' if peak >= AVOID_MIN else '⚪ เบาเกิน'))),
        })
    out = pd.DataFrame(rows)
    return out.sort_values('โหลดสูงสุด/วัน', ascending=False).reset_index(drop=True) \
        if not out.empty else out

# =====================================================================================
#  SECTION 6 — ZONING ENGINE
# =====================================================================================
def _tolerance_for(t: str, targets: Dict[str, float], cfg: ZoningConfig) -> float:
    """ค่าเผื่อรายคัน

    แก้บั๊กเดิม: ใช้ % ของความจุเต็มเสมอ -> รถที่ตั้งเป้า 30% ได้ค่าเผื่อกว้างถึง
    ±16.7% ของเป้าตัวเอง ทำให้รับงานเกินได้เยอะโดยระบบยังบอกว่า 'อยู่ในค่าเผื่อ'
    """
    if cfg.tol_mode == 'target':
        return max(40.0, (cfg.tol_pct / 100.0) * targets.get(t, 0.0))
    return (cfg.tol_pct / 100.0) * cfg.monthly_capacity

def build_stops(df: pd.DataFrame, cfg: ZoningConfig) -> pd.DataFrame:
    return df.groupby('coord_key').agg(
        lat=(cfg.lat_col, 'first'), lon=(cfg.lon_col, 'first'),
        x=('x', 'first'), y=('y', 'first'),
        total_vol=(cfg.vol_col, 'sum'), n_cust=(cfg.id_col, 'count'),
        orig_truck=(cfg.truck_col, 'first'), has_vip_lock=('is_vip_locked', 'any'),
    ).reset_index()

def compute_core_keys(stops: pd.DataFrame, ratio: float, eligible: Sequence[str],
                      override: Optional[Dict[str, float]] = None) -> set:
    keys: set = set()
    if ratio <= 0:
        return keys
    override = override or {}
    for t in eligible:
        r = min(ratio, override.get(t, 100.0))
        if r <= 0:
            continue
        g = stops[stops['orig_truck'] == t]
        if g.empty:
            continue
        cx, cy = g['x'].mean(), g['y'].mean()
        g = g.assign(_d=(g['x'] - cx) ** 2 + (g['y'] - cy) ** 2).sort_values('_d')
        cum = g['total_vol'].cumsum()
        total = max(1e-6, float(g['total_vol'].sum()))
        mask = (cum / total) <= (r / 100.0)
        if not mask.any() and len(g):
            mask.iloc[0] = True
        keys.update(g.loc[mask, 'coord_key'].tolist())
    return keys

def _assign_capacitated(stops: pd.DataFrame, trucks: List[str], targets: Dict[str, float],
                        tol: Dict[str, float], seeds: Dict[str, Tuple[float, float]],
                        road: Optional[np.ndarray], max_rounds: int = 80):
    """Capacitated Voronoi แบบ vectorized + global greedy (จัดคู่ใกล้สุดก่อน)"""
    xy = stops[['x', 'y']].to_numpy(dtype=float)
    vol = stops['total_vol'].to_numpy(dtype=float)
    tidx = {t: i for i, t in enumerate(trucks)}

    assigned = np.array([tidx.get(a, -1) if isinstance(a, str) else -1
                         for a in stops['assigned_truck'].tolist()], dtype=int)
    loads = {t: 0.0 for t in trucks}
    for i in np.where(assigned >= 0)[0]:
        loads[trucks[assigned[i]]] += vol[i]

    for _ in range(max_rounds):
        elig = [t for t in trucks if loads[t] < targets.get(t, 0.0) - 1e-9]
        cand = np.where(assigned < 0)[0]
        if not elig or cand.size == 0:
            break
        cols = [tidx[t] for t in elig]

        if road is not None:
            D = np.where(np.isnan(road[np.ix_(cand, cols)]), np.inf,
                         road[np.ix_(cand, cols)]).astype(float)
        else:
            cen = []
            for t in elig:
                m = assigned == tidx[t]
                cen.append(xy[m].mean(axis=0) if m.any()
                           else np.array(seeds.get(t, (xy[:, 0].mean(), xy[:, 1].mean()))))
            cen = np.array(cen, dtype=float)
            D = np.sqrt(((xy[cand][:, None, :] - cen[None, :, :]) ** 2).sum(axis=2))

        cap = np.array([targets.get(t, 0.0) + tol.get(t, 0.0) for t in elig])
        cur = np.array([loads[t] for t in elig])
        D = np.where((cur[None, :] + vol[cand][:, None]) <= cap[None, :], D, np.inf)

        bj = D.argmin(axis=1)
        bd = D[np.arange(len(cand)), bj]
        ok = np.isfinite(bd)
        if not ok.any():
            break

        placed = False
        for p in np.argsort(bd[ok]):
            i, t = cand[ok][p], elig[bj[ok][p]]
            if assigned[i] >= 0 or loads[t] + vol[i] > targets.get(t, 0.0) + tol.get(t, 0.0):
                continue
            assigned[i] = tidx[t]
            loads[t] += vol[i]
            placed = True
        if not placed:
            break

    for i in np.where(assigned < 0)[0]:
        pool = [t for t in trucks if targets.get(t, 0.0) > 0]
        if not pool:
            continue
        t = max(pool, key=lambda z: targets[z] - loads[z])
        if targets[t] - loads[t] > -0.15 * max(1.0, targets[t]):
            assigned[i] = tidx[t]
            loads[t] += vol[i]
    return assigned, loads

def cleanup_stray_points(stops, trucks, targets, loads, tol, mult, rounds=3):
    """ย้าย 'เกาะเดี่ยว' ที่หลุดไกลจากกลุ่มก้อนตัวเอง ไปอยู่กับคันที่ใกล้กว่าจริง"""
    stops = stops.copy()
    for _ in range(rounds):
        changed = False
        cent = {t: (g['x'].mean(), g['y'].mean())
                for t, g in stops.groupby('assigned_truck') if t in trucks and not g.empty}
        for t in trucks:
            m = (stops['assigned_truck'] == t) & (~stops['is_locked'])
            g = stops[m]
            if len(g) < 3 or t not in cent:
                continue
            cx, cy = cent[t]
            d = np.sqrt((g['x'] - cx) ** 2 + (g['y'] - cy) ** 2)
            radius = float(d.median()) * 3.0 + 1.0
            for idx in g.index[d > radius]:
                s = stops.loc[idx]
                own = (s['x'] - cx) ** 2 + (s['y'] - cy) ** 2
                best_t, best_d = None, float('inf')
                for ot, (ox, oy) in cent.items():
                    if ot == t or ot not in trucks:
                        continue
                    dd = (s['x'] - ox) ** 2 + (s['y'] - oy) ** 2
                    if dd < best_d:
                        best_d, best_t = dd, ot
                if best_t is None:
                    continue
                room = loads.get(best_t, 0.0) + s['total_vol'] <= \
                    targets.get(best_t, 0.0) + tol.get(best_t, 0.0) * mult
                if best_d < own * 0.6 and room:
                    stops.at[idx, 'assigned_truck'] = best_t
                    loads[t] -= s['total_vol']
                    loads[best_t] = loads.get(best_t, 0.0) + s['total_vol']
                    changed = True
        if not changed:
            break
    return stops, loads

def majority_vote_smoothing(stops, trucks, targets, loads, tol, cfg: ZoningConfig):
    """ขัดผิวรอยต่อโซน (แก้ checkerboard) ด้วย k-NN majority filter บน KDTree"""
    stops = stops.reset_index(drop=True)
    n = len(stops)
    if n < cfg.knn_k + 2:
        return stops, loads
    nb = knn_indices(stops[['x', 'y']].to_numpy(dtype=float), cfg.knn_k)
    locked = stops['is_locked'].to_numpy()
    vol = stops['total_vol'].to_numpy(dtype=float)

    for _ in range(cfg.knn_rounds):
        changed = False
        assigned = stops['assigned_truck'].to_numpy(dtype=object).copy()
        for i in range(n):
            if locked[i]:
                continue
            cur = assigned[i]
            vals, counts = np.unique(assigned[nb[i]], return_counts=True)
            maj = vals[np.argmax(counts)]
            if maj == cur or maj == OVERFLOW_LABEL or maj is None:
                continue
            if counts.max() < cfg.knn_k * cfg.knn_majority:
                continue
            if loads.get(maj, 0.0) + vol[i] <= targets.get(maj, 0.0) + \
                    tol.get(maj, 0.0) * cfg.polish_tol_multiplier:
                loads[cur] = loads.get(cur, 0.0) - vol[i]
                loads[maj] = loads.get(maj, 0.0) + vol[i]
                assigned[i] = maj
                changed = True
        stops['assigned_truck'] = assigned
        if not changed:
            break
    return stops, loads

def swap_improve(stops, trucks, targets, loads, tol, rounds=3, max_pairs=60):
    """Local search แบบสลับคู่ข้ามคัน — แก้เคสที่ 2 คันต่างมีจุดที่ควรอยู่กับอีกคัน
    พร้อมกัน ซึ่งย้ายเดี่ยวไม่ได้เพราะติดเพดานความจุ"""
    stops = stops.copy()
    for _ in range(rounds):
        changed = False
        cent = {t: np.array([g['x'].mean(), g['y'].mean()])
                for t, g in stops.groupby('assigned_truck') if t in trucks and not g.empty}
        for a, b in combinations([t for t in trucks if t in cent], 2):
            ca, cb = cent[a], cent[b]
            A = stops[(stops['assigned_truck'] == a) & (~stops['is_locked'])]
            B = stops[(stops['assigned_truck'] == b) & (~stops['is_locked'])]
            if A.empty or B.empty:
                continue
            PA, PB = A[['x', 'y']].to_numpy(), B[['x', 'y']].to_numpy()
            gA = np.sqrt(((PA - ca) ** 2).sum(1)) - np.sqrt(((PA - cb) ** 2).sum(1))
            gB = np.sqrt(((PB - cb) ** 2).sum(1)) - np.sqrt(((PB - ca) ** 2).sum(1))
            ia = A.index[np.argsort(-gA)][:max_pairs]
            ib = B.index[np.argsort(-gB)][:max_pairs]
            ga, gb = dict(zip(A.index, gA)), dict(zip(B.index, gB))
            used = set()
            for i in ia:
                if ga[i] <= 0:
                    break
                for j in ib:
                    if j in used or gb[j] <= 0 or ga[i] + gb[j] <= 0:
                        continue
                    va, vb = stops.at[i, 'total_vol'], stops.at[j, 'total_vol']
                    la, lb = loads[a] - va + vb, loads[b] - vb + va
                    if la > targets.get(a, 0.0) + tol.get(a, 0.0):
                        continue
                    if lb > targets.get(b, 0.0) + tol.get(b, 0.0):
                        continue
                    stops.at[i, 'assigned_truck'] = b
                    stops.at[j, 'assigned_truck'] = a
                    loads[a], loads[b] = la, lb
                    used.add(j)
                    changed = True
                    break
        if not changed:
            break
    return stops, loads

def smooth_daily_loads(opt: pd.DataFrame, cfg: ZoningConfig, trucks: List[str]):
    """PRIORITY 3 — เกลี่ยวันจัดส่งภายในคันเดียวกัน (คุมทั้งปริมาตรและจำนวนจุดจอด)"""
    idx_list = opt.index.tolist()
    pos = {ix: p for p, ix in enumerate(idx_list)}
    vols = opt[cfg.vol_col].to_numpy(dtype=float)

    day_map: Dict[int, List[int]] = {}
    for ix in idx_list:
        d, status = parse_days_from_string(opt.at[ix, cfg.day_col])
        day_map[ix] = d or list(range(WORKING_DAYS))
        opt.at[ix, '_day_status'] = status

    def recompute():
        vd = {t: np.zeros(WORKING_DAYS) for t in trucks}
        cd = {t: np.zeros(WORKING_DAYS) for t in trucks}
        for ix in idx_list:
            t = opt.at[ix, 'เบอร์รถใหม่']
            if t not in vd:
                continue
            dl = day_map[ix]
            per = vols[pos[ix]] / max(1, len(dl)) / WEEKS_PER_MONTH
            for d in dl:
                vd[t][d] += per
                cd[t][d] += 1
        return vd, cd

    cap = max(1.0, cfg.daily_control_cap - cfg.daily_safety_buffer)
    for _ in range(cfg.daily_passes):
        vd, cd = recompute()
        changed = False
        for t in trucks:
            for d in np.argsort(-vd[t]):
                over_v = vd[t][d] > cap
                over_c = cd[t][d] > cfg.max_stops_per_day
                if not (over_v or over_c):
                    continue
                score = vd[t] / cap + cd[t] / max(1, cfg.max_stops_per_day)
                td = int(np.argmin(score))
                if td == d:
                    continue
                if vd[t][td] >= cap - 5 and cd[t][td] >= cfg.max_stops_per_day - 2:
                    continue
                movable = [ix for ix in idx_list
                           if opt.at[ix, 'เบอร์รถใหม่'] == t
                           and (cfg.allow_vip_day_move or not opt.at[ix, 'is_vip_locked'])
                           and d in day_map[ix] and len(day_map[ix]) <= 3
                           and td not in day_map[ix]]
                if not movable:
                    continue
                movable.sort(key=lambda ix: -vols[pos[ix]] / max(1, len(day_map[ix])))
                excess = max(0.0, vd[t][d] - min(TARGET_DAY_CAP, cap))
                shifted = 0.0
                for ix in movable:
                    if shifted >= excess and not over_c:
                        break
                    dl = day_map[ix]
                    v = vols[pos[ix]] / max(1, len(dl)) / WEEKS_PER_MONTH
                    if vd[t][td] + v > cap:
                        continue
                    if cd[t][td] + 1 > cfg.max_stops_per_day:
                        break
                    day_map[ix] = [td if z == d else z for z in dl]
                    note = f"{DAY_SHORT[d]}→{DAY_SHORT[td]}"
                    prev = str(opt.at[ix, 'สถานะการย้ายวัน'])
                    opt.at[ix, 'สถานะการย้ายวัน'] = note if prev in ('-', 'nan') else f"{prev}, {note}"
                    vd[t][d] -= v
                    vd[t][td] += v
                    cd[t][d] -= 1
                    cd[t][td] += 1
                    shifted += v
                    changed = True
                    over_c = cd[t][d] > cfg.max_stops_per_day
        if not changed:
            break

    for ix in idx_list:
        opt.at[ix, 'วันจัดส่ง(ใหม่)'] = format_days_to_string(day_map[ix])
        opt.at[ix, 'วันจัดส่ง(ย่อ)'] = format_days_short(day_map[ix])

    n = len(opt)
    dm = np.zeros((n, WORKING_DAYS))
    ds = np.zeros((n, WORKING_DAYS))
    for ix in idx_list:
        dl = day_map[ix]
        per = vols[pos[ix]] / max(1, len(dl)) / WEEKS_PER_MONTH
        for d in dl:
            dm[pos[ix], d] = per
            ds[pos[ix], d] = 1
    final_daily, _ = recompute()
    return opt, dm, ds, final_daily

def compute_compactness(g: pd.DataFrame) -> float:
    if g.empty:
        return 0.0
    cx, cy = g['x'].mean(), g['y'].mean()
    return float(np.sqrt((g['x'] - cx) ** 2 + (g['y'] - cy) ** 2).mean())

def run_multi_donor_zoning(df: pd.DataFrame, cfg: ZoningConfig, econ: TripEconomics,
                           target_pcts: Dict[str, float], dissolve_trucks: Sequence[str],
                           relieve_trucks: Sequence[str], new_trucks: Sequence[str],
                           manual_locks: Sequence[str], road_getter=None) -> ZoningResult:
    warns, infos = [], []
    opt = df.copy()

    all_orig = clean_truck_ids(opt[cfg.truck_col].unique())
    dissolve = [t for t in dissolve_trucks if t in all_orig]
    kept = [t for t in all_orig if t not in dissolve]
    active = kept + [t for t in new_trucks if t not in kept]

    targets = {t: cfg.monthly_capacity * (float(target_pcts.get(t, 0.0)) / 100.0) for t in active}
    tol = {t: _tolerance_for(t, targets, cfg) for t in active}

    locked_ids = {str(x).strip() for x in manual_locks}
    opt['is_vip_locked'] = (
        opt['VIP_Status'].astype(str).str.upper().str.strip().eq('VIP') |
        opt[cfg.id_col].astype(str).str.strip().isin(locked_ids))
    opt['สถานะการย้ายวัน'] = '-'
    opt['coord_key'] = (opt[cfg.lat_col].round(5).astype(str) + "," +
                        opt[cfg.lon_col].round(5).astype(str))
    x, y, _ = project_xy(opt[cfg.lat_col].to_numpy(), opt[cfg.lon_col].to_numpy())
    opt['x'], opt['y'] = x, y

    stops = build_stops(opt, cfg)
    if not stops.empty:
        biggest = float(stops['total_vol'].max())
        max_tgt = max(targets.values()) if targets else 0.0
        if max_tgt > 0 and biggest > max_tgt:
            warns.append(f"พบจุดพิกัดเดียวที่มียอดรวม {biggest:,.0f} ถัง/เดือน "
                         f"(ลูกค้าหลายรายพิกัดชนกัน) มากกว่าเป้าสูงสุดต่อคัน ({max_tgt:,.0f}) "
                         f"จุดนี้จะตกเป็น '{OVERFLOW_LABEL}' เสมอ ควรตรวจสอบพิกัด GPS")

    vol_by_truck = stops.groupby('orig_truck')['total_vol'].sum().to_dict()
    ratio_override = {}
    for t in relieve_trucks:
        cur = float(vol_by_truck.get(t, 0.0))
        if cur > 0 and t in targets:
            ratio_override[t] = max(0.0, targets[t] / cur * 100.0 * 0.92)
    core_eligible = [t for t in kept if t not in dissolve]

    seeds = {}
    for t in kept:
        g = stops[stops['orig_truck'] == t]
        if not g.empty:
            seeds[t] = (float(g['x'].mean()), float(g['y'].mean()))
    bx, by = float(stops['x'].mean()), float(stops['y'].mean())

    if new_trucks:
        ck = compute_core_keys(stops, cfg.core_ratio, core_eligible, ratio_override)
        pool = stops[~stops['coord_key'].isin(ck)]
        pool = pool if not pool.empty else stops
        C = kmeans_seeds(pool[['x', 'y']].to_numpy(dtype=float),
                         pool['total_vol'].to_numpy(dtype=float), len(new_trucks))
        for i, t in enumerate(new_trucks):
            seeds[t] = (float(C[i][0]), float(C[i][1]))

    road = None
    if cfg.use_road and road_getter is not None and active and not stops.empty:
        lat0 = float(opt[cfg.lat_col].mean())
        k = math.cos(math.radians(lat0))
        dest_ll = []
        for t in active:
            sx, sy = seeds.get(t, (bx, by))
            dest_ll.append((math.degrees(sy / EARTH_RADIUS_M),
                            math.degrees(sx / (EARTH_RADIUS_M * k))))
        road, err = road_getter(tuple(zip(stops['lat'].tolist(), stops['lon'].tolist())),
                                tuple(dest_ll))
        if road is None:
            warns.append(f"เรียก API ระยะทางถนนจริงไม่สำเร็จ ({err}) รอบนี้ใช้ระยะทางเส้นตรงแทน")

    def one_pass(ratio: float):
        s = stops.copy()
        ck = compute_core_keys(s, ratio, core_eligible, ratio_override)
        s['is_core_locked'] = s['coord_key'].isin(ck)
        s['is_locked'] = s['has_vip_lock'] | s['is_core_locked']
        s['assigned_truck'] = None
        for i, r in s.iterrows():
            if r['is_locked'] and r['orig_truck'] in active:
                s.at[i, 'assigned_truck'] = r['orig_truck']
        a, ld = _assign_capacitated(s, active, targets, tol, seeds, road)
        s['assigned_truck'] = [active[k] if k >= 0 else OVERFLOW_LABEL for k in a]
        s.loc[s['is_locked'] & ~s['orig_truck'].isin(active), 'is_locked'] = False
        return s, ld

    ratio = cfg.core_ratio
    best = None
    while True:
        s_try, l_try = one_pass(ratio)
        viol = sum(max(0.0, abs(l_try.get(t, 0.0) - targets[t]) - tol[t])
                   for t in active if targets.get(t, 0.0) > 0)
        if best is None or viol < best[3]:
            best = (s_try, l_try, ratio, viol)
        if viol <= 1e-6 or ratio <= cfg.core_floor:
            break
        ratio = max(cfg.core_floor, ratio - cfg.core_step)

    stops_a, loads, ratio_used, _ = best
    if ratio_used < cfg.core_ratio:
        infos.append(f"ระบบลดสัดส่วนแกนกลางที่ล็อก (Core %) จาก {cfg.core_ratio:.0f}% "
                     f"เหลือ {ratio_used:.0f}% อัตโนมัติ เพื่อให้ยอดจริงเข้าใกล้เป้าหมายมากขึ้น")

    if cfg.enable_stray_cleanup:
        stops_a, loads = cleanup_stray_points(stops_a, active, targets, loads, tol,
                                              cfg.polish_tol_multiplier)
    if cfg.enable_majority_vote:
        stops_a, loads = majority_vote_smoothing(stops_a, active, targets, loads, tol, cfg)
    if cfg.enable_swap:
        stops_a, loads = swap_improve(stops_a, active, targets, loads, tol, cfg.swap_rounds)

    m_truck = dict(zip(stops_a['coord_key'], stops_a['assigned_truck']))
    m_core = dict(zip(stops_a['coord_key'], stops_a['is_core_locked']))
    opt['เบอร์รถใหม่'] = opt['coord_key'].map(m_truck).fillna(OVERFLOW_LABEL)
    opt['is_core_locked'] = opt['coord_key'].map(m_core).fillna(False)
    opt['is_locked'] = opt['is_vip_locked'] | opt['is_core_locked']
    opt['สถานะ'] = np.where(opt[cfg.truck_col] == opt['เบอร์รถใหม่'],
                            'คงเดิม', 'ย้ายไปสาย ' + opt['เบอร์รถใหม่'].astype(str))
    opt.loc[opt['is_locked'] & (opt[cfg.truck_col] == opt['เบอร์รถใหม่']), 'สถานะ'] = 'คงเดิม 🔒'

    opt, dm, ds, final_daily = smooth_daily_loads(opt, cfg, active)

    before = opt.groupby(cfg.truck_col)
    after = opt.groupby('เบอร์รถใหม่')
    comp_b = np.mean([compute_compactness(g) for _, g in before]) if len(before) else 0.0
    comp_a = np.mean([compute_compactness(g) for t, g in after if t != OVERFLOW_LABEL]) \
        if len(after) else 0.0

    peak_b, trips_b = {}, 0
    for t, g in before:
        d = np.zeros(WORKING_DAYS)
        for _, r in g.iterrows():
            dl, _ = parse_days_from_string(r[cfg.day_col])
            dl = dl or list(range(WORKING_DAYS))
            per = float(r[cfg.vol_col]) / len(dl) / WEEKS_PER_MONTH
            for k2 in dl:
                d[k2] += per
        peak_b[str(t).strip()] = float(d.max())
        trips_b += sum(max(0, econ.trips_for(v) - econ.trips_normal) for v in d)
    peak_a = {t: float(v.max()) for t, v in final_daily.items()}
    trips_a = sum(sum(max(0, econ.trips_for(v) - econ.trips_normal) for v in arr)
                  for arr in final_daily.values())

    moved = int((opt[cfg.truck_col] != opt['เบอร์รถใหม่']).sum())
    metrics = {
        'compact_before_km': comp_b / 1000.0, 'compact_after_km': comp_a / 1000.0,
        'over_before': sum(1 for v in peak_b.values() if v > cfg.daily_control_cap),
        'over_after': sum(1 for v in peak_a.values() if v > cfg.daily_control_cap),
        'peak_before': max(peak_b.values()) if peak_b else 0.0,
        'peak_after': max(peak_a.values()) if peak_a else 0.0,
        'trips_before': trips_b, 'trips_after': trips_a,
        'moved_cust': moved, 'moved_pct': moved / max(1, len(opt)) * 100.0,
        'moved_vol': float(opt.loc[opt[cfg.truck_col] != opt['เบอร์รถใหม่'], cfg.vol_col].sum()),
        'std_before': float(np.std(list(peak_b.values()))) if peak_b else 0.0,
        'std_after': float(np.std(list(peak_a.values()))) if peak_a else 0.0,
    }

    bad = int((opt['_day_status'] != 'ok').sum()) if '_day_status' in opt.columns else 0
    if bad:
        warns.append(f"อ่านค่า 'วันจัดส่ง' ไม่ออก {bad} รายการ ระบบถือว่าเป็น 'จ-ส' "
                     f"ซึ่งจะทำให้โหลดรายวันดูสูงเกินจริง กรุณาตรวจสอบข้อมูลต้นทาง")

    return ZoningResult(opt, stops_a, dm, ds, final_daily, targets, loads,
                        ratio_used, metrics, warns, infos)

# =====================================================================================
#  SECTION 7 — MARGINAL OVERFLOW RESOLVER
# =====================================================================================
def max_delivery_gap(days: List[int], cycle: int = 7) -> int:
    """ช่องว่างสูงสุดระหว่างรอบส่ง (วัน) — กันลูกค้าน้ำหมดก่อนรอบถัดไป"""
    if not days:
        return cycle
    d = sorted(set(days))
    if len(d) == 1:
        return cycle
    gaps = [d[i + 1] - d[i] for i in range(len(d) - 1)]
    gaps.append(d[0] + cycle - d[-1])
    return max(gaps)

def insertion_cost_m(x, y, pts) -> float:
    if pts is None or len(pts) == 0:
        return 999_999.0
    return float(2.0 * np.sqrt(((pts - np.array([x, y])) ** 2).sum(axis=1)).min())

def removal_saving_m(x, y, pts) -> float:
    if pts is None or len(pts) <= 1:
        return 0.0
    d = np.sort(np.sqrt(((pts - np.array([x, y])) ** 2).sum(axis=1)))[1:]
    return float(2.0 * d[0]) if len(d) else 0.0

def build_visit_table(res: ZoningResult, cfg: ZoningConfig) -> pd.DataFrame:
    """แตกข้อมูลจากระดับ 'ลูกค้า' -> ระดับ 'การเข้าส่ง 1 ครั้ง' (visit)"""
    rdf = res.result_df.reset_index(drop=True)
    dm = res.daily_matrix
    rows = []
    for i in range(len(rdf)):
        days = np.where(dm[i] > 1e-9)[0]
        for d in days:
            rows.append({
                'cust_idx': i, 'cust_id': str(rdf.at[i, cfg.id_col]),
                'cust_name': str(rdf.at[i, cfg.name_col]) if cfg.name_col else '',
                'truck': str(rdf.at[i, 'เบอร์รถใหม่']), 'day': int(d),
                'qty': float(dm[i, d]), 'x': float(rdf.at[i, 'x']), 'y': float(rdf.at[i, 'y']),
                'lat': float(rdf.at[i, cfg.lat_col]), 'lon': float(rdf.at[i, cfg.lon_col]),
                'is_vip': bool(rdf.at[i, 'is_vip_locked']),
                'is_locked': bool(rdf.at[i, 'is_locked']),
                'days_set': tuple(int(z) for z in days),
                'month_vol': float(rdf.at[i, cfg.vol_col]),
            })
    return pd.DataFrame(rows)

def cliff_report(visits: pd.DataFrame, econ: TripEconomics) -> pd.DataFrame:
    """วิเคราะห์ทุกคู่ (รถ, วัน) ว่าอยู่ตรงไหนของขั้นบันไดต้นทุน

    แยกให้เห็นชัดว่า 'รอบพิเศษที่คุ้มค่า' (ขนเต็ม) ต่างจาก 'รอบพิเศษที่เสียเปล่า'
    (ขนไม่กี่ถังแต่จ่ายค่าเที่ยวเต็มราคา) อย่างไร
    """
    rows = []
    for (t, d), g in visits.groupby(['truck', 'day']):
        load = float(g['qty'].sum())
        trips = econ.trips_for(load)
        util = econ.last_trip_util(load)
        room = econ.trip_capacity * max(trips, 1) - load
        if trips <= econ.trips_normal:
            room = econ.soft_cap - load
            status = ('⚠️ เสี่ยงตกหน้าผา' if room <= econ.cliff_warn_gap
                      else ('🟢 เหมาะสม' if load >= OPTIMAL_MIN else '⚪ ยังรับได้อีก'))
            waste = 0.0
        elif util < econ.util_bad:
            status, waste = '🚨 รอบพิเศษไม่คุ้ม', econ.cost_per_trip
        elif util < econ.util_ok:
            status, waste = '🟡 รอบพิเศษพอรับได้', econ.cost_per_trip * (1 - util)
        else:
            status, waste = '🟢 รอบพิเศษคุ้มค่า', 0.0
        rows.append({
            'เบอร์รถ': t, 'วัน': DAY_NAMES[d], '_day': d, '_truck': t,
            'ยอด(ถัง)': int(round(load)), 'เที่ยว': trips,
            'ยอดเที่ยวสุดท้าย': int(round(econ.last_trip_load(load))),
            'ใช้ความจุ': f"{util*100:,.0f}%",
            'ต้นทุน/ถัง': (f"{econ.cost_per_barrel_last_trip(load):,.0f} ฿"
                            if trips > econ.trips_normal else '-'),
            'เติมได้อีก': int(round(max(0.0, room))),
            'สูญเปล่า(฿/สัปดาห์)': int(round(waste)), 'สถานะ': status,
        })
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    return out.sort_values(['สูญเปล่า(฿/สัปดาห์)', 'ยอด(ถัง)'],
                           ascending=[False, False]).reset_index(drop=True)

def _day_points(v, t, d):
    g = v[(v['truck'] == t) & (v['day'] == d)]
    return g[['x', 'y']].to_numpy(dtype=float) if not g.empty else np.empty((0, 2))

def _day_load(v, t, d):
    return float(v[(v['truck'] == t) & (v['day'] == d)]['qty'].sum())

def generate_candidates(visits, truck, day, excess, rcfg: ResolverConfig,
                        econ: TripEconomics) -> List[MoveCandidate]:
    out: List[MoveCandidate] = []
    src = visits[(visits['truck'] == truck) & (visits['day'] == day)]
    if src.empty:
        return out
    src_pts = _day_points(visits, truck, day)

    dest_info = {}
    for t2 in sorted(visits['truck'].unique()):
        for d2 in range(WORKING_DAYS):
            if t2 == truck and d2 == day:
                continue
            ld = _day_load(visits, t2, d2)
            room = (econ.soft_cap - ld if econ.trips_for(ld) < econ.trips_normal
                    else econ.trip_capacity * econ.trips_for(max(ld, 1.0)) - ld)
            dest_info[(t2, d2)] = {'room': max(0.0, room - rcfg.target_day_buffer),
                                   'pts': _day_points(visits, t2, d2)}

    for _, v in src.iterrows():
        if rcfg.protect_vip and v['is_vip']:
            continue
        qty = float(v['qty'])
        rem = removal_saving_m(v['x'], v['y'], src_pts)
        cur_days = list(v['days_set'])

        for (t2, d2), info in dest_info.items():
            same = (t2 == truck)
            if info['room'] <= 0.5:
                continue
            ins = insertion_cost_m(v['x'], v['y'], info['pts'])
            if ins > rcfg.max_detour_m:
                continue
            detour = ins - rem
            base = max(0.0, detour) / 1000.0 * econ.cost_per_km

            # A) ย้ายวันทั้งราย
            if rcfg.enable_shift and same and d2 not in cur_days and info['room'] >= qty:
                nd = sorted(set([d2 if z == day else z for z in cur_days]))
                gap = max_delivery_gap(nd)
                if gap <= rcfg.max_interval_days:
                    out.append(MoveCandidate(
                        'shift', int(v['cust_idx']), v['cust_id'], v['cust_name'],
                        truck, day, t2, d2, qty, detour, base,
                        note=f"ย้ายทั้งราย {DAY_NAMES[day]}→{DAY_NAMES[d2]} "
                             f"(ช่องว่างรอบส่ง {gap} วัน)",
                        risk='ต่ำ' if gap <= rcfg.max_interval_days - 1 else 'ปานกลาง'))

            # C) โอนข้ามคัน วันเดียวกัน
            if (rcfg.enable_cross and not same and d2 == day
                    and info['room'] >= qty and not v['is_locked']):
                out.append(MoveCandidate(
                    'cross', int(v['cust_idx']), v['cust_id'], v['cust_name'],
                    truck, day, t2, d2, qty, detour, base + econ.admin_cost_cross,
                    note=f"โอนให้รถ {t2} รับแทนใน{DAY_NAMES[day]} "
                         f"(ห่างเส้นทางเดิม {ins/1000:,.1f} กม.)", risk='ปานกลาง'))

            # B) ซอยยอดส่ง 2 วัน
            if (rcfg.enable_split and same and d2 not in cur_days
                    and qty >= rcfg.min_split_qty * 2):
                take = math.floor(min(excess, qty - rcfg.min_split_qty, info['room']))
                if take >= rcfg.min_split_qty:
                    nd = sorted(set(cur_days + [d2]))
                    if max_delivery_gap(nd) <= rcfg.max_interval_days:
                        out.append(MoveCandidate(
                            'split', int(v['cust_idx']), v['cust_id'], v['cust_name'],
                            truck, day, t2, d2, float(take), detour,
                            base + econ.cost_per_new_stop,
                            note=f"ซอยยอด {DAY_NAMES[day]} {qty:,.0f}→{qty-take:,.0f} ถัง "
                                 f"| เพิ่ม {DAY_NAMES[d2]} {take:,.0f} ถัง", risk='ต่ำ'))

            # D) สัปดาห์คู่/คี่
            if (rcfg.enable_biweekly and same and d2 not in cur_days
                    and qty >= rcfg.min_split_qty * 2 and info['room'] >= qty / 2):
                nd = sorted(set(cur_days + [d2]))
                if max_delivery_gap(nd) <= rcfg.max_interval_days:
                    out.append(MoveCandidate(
                        'biweekly', int(v['cust_idx']), v['cust_id'], v['cust_name'],
                        truck, day, t2, d2, qty / 2.0, detour,
                        base + econ.admin_cost_biweekly,
                        note=f"สัปดาห์คู่ส่ง{DAY_NAMES[day]} / สัปดาห์คี่ส่ง{DAY_NAMES[d2]} "
                             f"(เฉลี่ยลด {qty/2:,.1f} ถัง)", risk='ปานกลาง'))

    # E) สลับคู่ข้ามวัน (ใช้เมื่อวันปลายทางเต็ม)
    if rcfg.enable_swap:
        for d2 in range(WORKING_DAYS):
            if d2 == day:
                continue
            tgt = visits[(visits['truck'] == truck) & (visits['day'] == d2)]
            if tgt.empty:
                continue
            tgt_pts = _day_points(visits, truck, d2)
            for _, a in src.iterrows():
                if (rcfg.protect_vip and a['is_vip']) or d2 in a['days_set']:
                    continue
                for _, b in tgt.iterrows():
                    if (rcfg.protect_vip and b['is_vip']) or day in b['days_set']:
                        continue
                    delta = float(a['qty']) - float(b['qty'])
                    if delta < 1.0 or delta > excess + 6:
                        continue
                    ga = max_delivery_gap(sorted(set([d2 if z == day else z for z in a['days_set']])))
                    gb = max_delivery_gap(sorted(set([day if z == d2 else z for z in b['days_set']])))
                    if max(ga, gb) > rcfg.max_interval_days:
                        continue
                    det = (insertion_cost_m(a['x'], a['y'], tgt_pts) +
                           insertion_cost_m(b['x'], b['y'], src_pts) -
                           removal_saving_m(a['x'], a['y'], src_pts) -
                           removal_saving_m(b['x'], b['y'], tgt_pts))
                    if det > rcfg.max_detour_m:
                        continue
                    out.append(MoveCandidate(
                        'swap', int(a['cust_idx']), a['cust_id'], a['cust_name'],
                        truck, day, truck, d2, delta, det,
                        max(0.0, det) / 1000.0 * econ.cost_per_km + 15.0,
                        partner_idx=int(b['cust_idx']), partner_qty=float(b['qty']),
                        note=f"สลับคู่ {a['cust_id']}({a['qty']:,.0f}) ↔ "
                             f"{b['cust_id']}({b['qty']:,.0f}) ระหว่าง"
                             f"{DAY_NAMES[day]}-{DAY_NAMES[d2]} ลดได้ {delta:,.0f} ถัง",
                        risk='ปานกลาง'))

    out.sort(key=lambda c: c.cost / max(1.0, min(c.qty, excess)))
    return out[:rcfg.candidate_pool]

def select_best_plan(cands: List[MoveCandidate], excess: float, rcfg: ResolverConfig):
    """หาชุดการย้ายที่ 'พอดี' ที่สุด — ลดยอดให้ครบโดยย้ายน้อยและเกินน้อยที่สุด

    การย้ายเกินจำเป็นจะทำให้วันเดิมกลายเป็น 'เบาเกิน' และไปทำวันปลายทางพังแทน
    """
    if not cands or excess <= 0:
        return [], 0.0

    def score(sel):
        tot = sum(c.qty for c in sel)
        if tot < excess - 1e-6:
            return float('inf')
        return sum(c.cost for c in sel) + (tot - excess) * rcfg.overshoot_penalty + len(sel) * 20.0

    best, best_s = None, float('inf')
    for c in cands:
        s = score([c])
        if s < best_s:
            best, best_s = [c], s
    for a, b in combinations(cands[:28], 2):
        if a.cust_idx == b.cust_idx:
            continue
        s = score([a, b])
        if s < best_s:
            best, best_s = [a, b], s

    if best is None:
        sel, tot, used = [], 0.0, set()
        for c in cands:
            if c.cust_idx in used or len(sel) >= rcfg.max_moves_per_day:
                continue
            sel.append(c)
            used.add(c.cust_idx)
            tot += c.qty
            if tot >= excess:
                break
        best = sel
        best_s = score(best) if best else float('inf')
    return best or [], (best_s if math.isfinite(best_s) else 0.0)

KIND_LABEL = {'shift': '🔄 ย้ายวัน', 'split': '✂️ ซอยยอด', 'cross': '🚚 โอนข้ามคัน',
              'biweekly': '📅 สัปดาห์คู่/คี่', 'swap': '🔁 สลับคู่'}

def resolve_marginal_overflow(res: ZoningResult, zcfg: ZoningConfig,
                              rcfg: ResolverConfig, econ: TripEconomics):
    visits = build_visit_table(res, zcfg)
    if visits.empty:
        return pd.DataFrame(), pd.DataFrame(), {}

    report = cliff_report(visits, econ)
    work = visits.copy()
    plan_rows, total_saved, total_cost, fixed = [], 0.0, 0.0, 0

    problems = []
    for (t, d), g in visits.groupby(['truck', 'day']):
        load = float(g['qty'].sum())
        if econ.trips_for(load) <= econ.trips_normal:
            continue
        util = econ.last_trip_util(load)
        excess = load - econ.soft_cap
        if util >= econ.util_ok or excess > rcfg.marginal_window:
            continue
        problems.append((util, t, d, load, excess))
    problems.sort()

    for util, t, d, load, excess in problems:
        cands = generate_candidates(work, t, d, excess, rcfg, econ)
        sel, _ = select_best_plan(cands, excess, rcfg)
        moved = sum(c.qty for c in sel)
        if not sel or moved < excess - 1e-6:
            plan_rows.append({
                'ลำดับ': len(plan_rows) + 1, 'เบอร์รถ': t, 'วันที่มีปัญหา': DAY_NAMES[d],
                'ยอดเดิม': int(round(load)), 'ต้องลด': int(round(excess)),
                'กลยุทธ์': '⛔ ไม่พบทางแก้', 'รหัสลูกค้า': '-', 'ชื่อลูกค้า': '-',
                'ย้ายไป': '-', 'ถังที่ย้าย': 0, 'ยอดใหม่': int(round(load)),
                'ประหยัด(฿/สัปดาห์)': 0, 'ต้นทุนย้าย(฿)': 0, 'สุทธิ(฿)': 0,
                'ความเสี่ยง': 'สูง',
                'รายละเอียด': 'ไม่มีวันปลายทางว่างพอ/ติดข้อจำกัดระยะห่างรอบส่ง '
                              '— ควรพิจารณาเพิ่มรถ หรือผ่อนปรนเงื่อนไข'})
            continue

        saved = econ.cost_per_trip
        cost = sum(c.cost for c in sel)
        total_saved += saved
        total_cost += cost
        fixed += 1
        new_load = load - moved

        for k, c in enumerate(sel):
            m = ((work['cust_idx'] == c.cust_idx) & (work['truck'] == c.from_truck) &
                 (work['day'] == c.from_day))
            if c.kind in ('shift', 'cross'):
                work.loc[m, ['truck', 'day']] = [c.to_truck, c.to_day]
            elif c.kind in ('split', 'biweekly'):
                work.loc[m, 'qty'] = work.loc[m, 'qty'] - c.qty
                if m.any():
                    row = work[m].iloc[0].to_dict()
                    row.update({'truck': c.to_truck, 'day': c.to_day, 'qty': c.qty})
                    work = pd.concat([work, pd.DataFrame([row])], ignore_index=True)
            elif c.kind == 'swap' and c.partner_idx is not None:
                pm = (work['cust_idx'] == c.partner_idx) & (work['day'] == c.to_day)
                work.loc[m, 'day'] = c.to_day
                work.loc[pm, 'day'] = c.from_day

            plan_rows.append({
                'ลำดับ': len(plan_rows) + 1, 'เบอร์รถ': t, 'วันที่มีปัญหา': DAY_NAMES[d],
                'ยอดเดิม': int(round(load)), 'ต้องลด': int(round(excess)),
                'กลยุทธ์': KIND_LABEL[c.kind], 'รหัสลูกค้า': c.cust_id,
                'ชื่อลูกค้า': c.cust_name,
                'ย้ายไป': f"{c.to_truck} / {DAY_NAMES[c.to_day]}",
                'ถังที่ย้าย': int(round(c.qty)), 'ยอดใหม่': int(round(new_load)),
                'ประหยัด(฿/สัปดาห์)': int(round(saved)) if k == 0 else 0,
                'ต้นทุนย้าย(฿)': int(round(c.cost)),
                'สุทธิ(฿)': int(round(saved - cost)) if k == 0 else 0,
                'ความเสี่ยง': c.risk, 'รายละเอียด': c.note})

    summary = {
        'fixed': fixed,
        'unfixed': sum(1 for r in plan_rows if r['กลยุทธ์'] == '⛔ ไม่พบทางแก้'),
        'saved': total_saved, 'cost': total_cost,
        'net_week': total_saved - total_cost, 'net_year': (total_saved - total_cost) * 52,
        'n_moves': sum(1 for r in plan_rows if r['ถังที่ย้าย'] > 0)}
    return pd.DataFrame(plan_rows), report, summary

def apply_plan(res: ZoningResult, zcfg: ZoningConfig,
               plan_df: pd.DataFrame, approved: List[int]) -> ZoningResult:
    rdf = res.result_df.reset_index(drop=True).copy()
    dm = res.daily_matrix.copy()
    rev = {v: k for k, v in DAY_NAMES.items()}

    for _, r in plan_df[plan_df['ลำดับ'].isin(approved)].iterrows():
        if r['ถังที่ย้าย'] <= 0:
            continue
        hit = rdf.index[rdf[zcfg.id_col].astype(str) == str(r['รหัสลูกค้า'])]
        if len(hit) == 0:
            continue
        i = hit[0]
        d_from = rev.get(str(r['วันที่มีปัญหา']))
        parts = [s.strip() for s in str(r['ย้ายไป']).split('/')]
        if len(parts) < 2:
            continue
        t_to, d_to = parts[0], rev.get(parts[1])
        if d_from is None or d_to is None:
            continue
        q = float(r['ถังที่ย้าย'])
        dm[i, d_from] = max(0.0, dm[i, d_from] - q)
        dm[i, d_to] += q
        if r['กลยุทธ์'] == KIND_LABEL['cross']:
            rdf.at[i, 'เบอร์รถใหม่'] = t_to
            rdf.at[i, 'สถานะ'] = f"ย้ายไปสาย {t_to} (แก้รอบพิเศษ)"
        days = sorted(np.where(dm[i] > 1e-9)[0].tolist())
        rdf.at[i, 'วันจัดส่ง(ใหม่)'] = format_days_to_string(days)
        rdf.at[i, 'วันจัดส่ง(ย่อ)'] = format_days_short(days)
        prev = str(rdf.at[i, 'สถานะการย้ายวัน'])
        note = f"{DAY_SHORT[d_from]}→{DAY_SHORT[d_to]}({int(q)})"
        rdf.at[i, 'สถานะการย้ายวัน'] = note if prev in ('-', 'nan') else f"{prev}, {note}"

    res.result_df = rdf
    res.daily_matrix = dm
    res.final_daily = {t: dm[(rdf['เบอร์รถใหม่'] == t).to_numpy()].sum(axis=0)
                       for t in rdf['เบอร์รถใหม่'].unique() if t != OVERFLOW_LABEL}
    return res

# =====================================================================================
#  SECTION 8 — UI THEME & COMPONENTS
# =====================================================================================
st.markdown(f'''
<style>
@import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');

/* ---------- ฐานตัวอักษร: ขนาด 15.5px อ่านสบาย ไม่เล็กไม่ใหญ่เกิน ---------- */
html, body, [class*="css"], p, span, label, div, small, li, a, td, th, input, button {{
    font-family:'Sarabun', -apple-system, sans-serif !important;
    font-size: 15.5px;
    line-height: 1.7;
    color: {C_TEXT};
    letter-spacing: 0.1px;
}}

/* ---------- พื้นหลังไล่เฉดลึก + จุดแสงนวล ---------- */
.stApp {{
    background:
      radial-gradient(1100px 700px at 12% -8%, rgba(125,211,252,0.10), transparent 60%),
      radial-gradient(900px 600px at 88% 5%, rgba(255,209,102,0.09), transparent 55%),
      linear-gradient(160deg, #050B18 0%, #0A1A33 45%, #0F2A4A 100%) !important;
    background-attachment: fixed;
}}
.block-container {{ padding-top: 2.2rem; padding-bottom: 3rem; max-width: 1500px; }}

/* ---------- หัวข้อ: ทองนวล ไม่แสบตา ---------- */
h1 {{ font-size: 30px !important; }}
h2 {{ font-size: 24px !important; }}
h3 {{ font-size: 20px !important; }}
h4, h5, h6 {{ font-size: 17px !important; }}
h1,h2,h3,h4,h5,h6 {{
    color: {C_GOLD} !important; font-weight: 700 !important;
    letter-spacing: 0.3px; text-shadow: 0 2px 12px rgba(0,0,0,0.5);
    margin-bottom: 0.5rem !important;
}}
[data-testid="stCaptionContainer"], .stCaption, .stCaption p {{
    color: {C_TEXT_DIM} !important; font-size: 13.5px !important; line-height: 1.6;
}}

/* ---------- Sidebar: กระจกโปร่ง ---------- */
[data-testid="stSidebar"] {{
    background: rgba(6, 16, 34, 0.42) !important;
    backdrop-filter: blur(30px) saturate(150%);
    -webkit-backdrop-filter: blur(30px) saturate(150%);
    border-right: 1px solid rgba(255,255,255,0.10);
}}
[data-testid="stSidebar"] * {{ color: {C_TEXT} !important; }}
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] .stMarkdown p {{
    color: {C_GOLD_SOFT} !important; font-weight: 600 !important; font-size: 14.5px !important;
}}
[data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3 {{
    color: {C_GOLD} !important; font-size: 16.5px !important;
    border-bottom: 1px solid rgba(255,209,102,0.22); padding-bottom: 8px; margin-top: 6px;
}}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{ font-size: 12.8px !important; }}

/* ---------- ช่องกรอก ---------- */
div[data-baseweb="select"] > div, input, textarea {{
    background: rgba(255,255,255,0.055) !important;
    border: 1px solid rgba(255,255,255,0.16) !important;
    color: {C_TEXT} !important; border-radius: 12px !important;
    font-weight: 500; font-size: 14.5px !important;
}}
div[data-baseweb="select"] * {{ color: {C_TEXT} !important; }}
div[data-baseweb="select"] [class*="placeholder"], input::placeholder {{
    color: {C_TEXT_DIM} !important; opacity: 1 !important;
}}
input:focus, div[data-baseweb="select"] > div:focus-within {{
    border-color: {C_GOLD} !important; box-shadow: 0 0 0 3px rgba(255,209,102,0.18) !important;
}}
div[data-baseweb="tag"] {{
    background: rgba(255,209,102,0.20) !important;
    border: 1px solid rgba(255,209,102,0.55) !important; border-radius: 8px !important;
}}
div[data-baseweb="tag"] * {{ color: {C_GOLD_SOFT} !important; font-size: 13.5px !important; }}

/* ---------- Dropdown: พื้นเข้ม อ่านง่าย ---------- */
div[role="listbox"], ul[role="listbox"], div[data-baseweb="menu"],
[data-baseweb="select-dropdown"], [data-baseweb="popover"] div[role="listbox"] {{
    background: rgba(10, 22, 42, 0.97) !important;
    backdrop-filter: blur(24px);
    border: 1px solid rgba(255,209,102,0.35) !important;
    border-radius: 12px !important; box-shadow: 0 16px 40px rgba(0,0,0,0.55) !important;
}}
div[role="option"], ul[role="listbox"] > li {{
    color: {C_TEXT} !important; font-size: 14.5px !important; font-weight: 500 !important;
    padding: 9px 15px !important; border-bottom: 1px solid rgba(255,255,255,0.06) !important;
}}
div[role="option"] * {{ color: {C_TEXT} !important; }}
div[role="option"]:hover {{ background: rgba(255,209,102,0.14) !important; }}
div[role="option"][aria-selected="true"] {{ background: rgba(255,209,102,0.26) !important; }}
div[role="option"][aria-selected="true"] * {{ color: {C_GOLD} !important; font-weight: 700 !important; }}

/* ---------- ปุ่ม ---------- */
.stButton>button {{
    background: linear-gradient(135deg, rgba(255,209,102,0.95), rgba(214,164,60,0.95)) !important;
    color: #0A1220 !important; border: none !important; border-radius: 11px;
    font-weight: 700 !important; font-size: 14.8px !important; padding: 0.58rem 1.3rem;
    width: 100%; box-shadow: 0 6px 18px rgba(255,209,102,0.22); transition: all .25s ease;
}}
.stButton>button:hover {{
    background: linear-gradient(135deg, #FFE0A0, #FFD166) !important;
    box-shadow: 0 10px 26px rgba(255,209,102,0.38); transform: translateY(-2px);
}}
[data-testid="stDownloadButton"] > button {{
    background: linear-gradient(135deg, rgba(74,222,128,0.92), rgba(34,150,84,0.92)) !important;
    color: #04140A !important; border-radius: 11px !important; font-weight: 700 !important;
    box-shadow: 0 6px 18px rgba(74,222,128,0.25);
}}

/* ---------- Slider / Checkbox ---------- */
[data-testid="stSlider"] label {{ font-size: 14px !important; }}
[data-testid="stTickBar"] {{ background: rgba(255,255,255,0.10) !important; }}
.stCheckbox label p {{ font-size: 14px !important; }}

/* ---------- Tabs ---------- */
.stTabs [data-baseweb="tab-list"] {{
    gap: 6px; background: rgba(255,255,255,0.045); padding: 6px;
    border-radius: 14px; border: 1px solid rgba(255,255,255,0.09);
}}
.stTabs [data-baseweb="tab"] {{
    border-radius: 10px; padding: 9px 18px; font-size: 14.8px !important;
    font-weight: 600 !important; color: {C_TEXT_DIM} !important; background: transparent;
}}
.stTabs [aria-selected="true"] {{
    background: rgba(255,209,102,0.16) !important; color: {C_GOLD} !important;
    border: 1px solid rgba(255,209,102,0.32);
}}

/* ---------- Expander ---------- */
[data-testid="stExpander"] {{
    background: rgba(255,255,255,0.045) !important;
    border: 1px solid rgba(255,255,255,0.10) !important;
    border-radius: 14px !important; backdrop-filter: blur(18px);
}}
[data-testid="stExpander"] summary p {{ font-size: 15px !important; font-weight: 600 !important; }}

/* ---------- การ์ดกระจก ---------- */
.glass-card {{
    background: rgba(255,255,255,0.055);
    backdrop-filter: blur(26px) saturate(140%);
    -webkit-backdrop-filter: blur(26px) saturate(140%);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 18px; padding: 18px 20px; margin-bottom: 16px;
    box-shadow: 0 10px 34px rgba(0,0,0,0.28), inset 0 1px 0 rgba(255,255,255,0.08);
}}
.section-head {{
    display:flex; align-items:center; gap:11px; margin: 26px 0 12px 0;
    padding: 12px 18px; border-radius: 14px;
    background: linear-gradient(90deg, rgba(255,209,102,0.13), rgba(255,209,102,0.02));
    border-left: 4px solid {C_GOLD};
    backdrop-filter: blur(14px);
}}
.section-head .t {{ font-size: 19px; font-weight: 700; color: {C_GOLD}; }}
.section-head .s {{ font-size: 13.5px; color: {C_TEXT_DIM}; margin-left: 6px; }}

/* ---------- KPI ---------- */
.kpi-grid {{ display:grid; grid-template-columns: repeat(auto-fit,minmax(210px,1fr)); gap:14px; }}
.kpi {{
    background: rgba(255,255,255,0.05); backdrop-filter: blur(24px);
    border: 1px solid rgba(255,255,255,0.11); border-radius: 16px;
    padding: 15px 17px; position: relative; overflow: hidden;
    box-shadow: 0 8px 26px rgba(0,0,0,0.24);
}}
.kpi::before {{ content:""; position:absolute; left:0; top:0; bottom:0; width:3px; }}
.kpi.good::before {{ background:{C_GREEN}; }}
.kpi.warn::before {{ background:{C_AMBER}; }}
.kpi.bad::before  {{ background:{C_RED}; }}
.kpi.info::before {{ background:{C_BLUE}; }}
.kpi.gold::before {{ background:{C_GOLD}; }}
.kpi .lb {{ font-size:13px; color:{C_TEXT_DIM}; font-weight:500; letter-spacing:.2px; }}
.kpi .vl {{ font-size:27px; font-weight:700; color:{C_TEXT}; line-height:1.25; margin:3px 0; }}
.kpi .dl {{ font-size:12.8px; font-weight:600; }}
.kpi .dl.up {{ color:{C_GREEN}; }} .kpi .dl.dn {{ color:{C_RED}; }} .kpi .dl.nu {{ color:{C_TEXT_DIM}; }}

/* ---------- ตาราง HTML คุมสีเอง ---------- */
.gt-wrap {{
    background: rgba(255,255,255,0.042); backdrop-filter: blur(24px);
    border: 1px solid rgba(255,255,255,0.11); border-radius: 16px;
    padding: 4px; overflow: auto; box-shadow: 0 8px 28px rgba(0,0,0,0.26); margin-bottom: 14px;
}}
table.gt {{ width:100%; border-collapse: collapse; font-size: 14.2px; }}
table.gt thead th {{
    position: sticky; top: 0; z-index: 2;
    background: rgba(10,22,42,0.96); color: {C_GOLD} !important;
    font-weight: 700; font-size: 13.5px; text-align: left;
    padding: 12px 13px; border-bottom: 2px solid rgba(255,209,102,0.30); white-space: nowrap;
}}
table.gt tbody td {{
    padding: 10px 13px; color: {C_TEXT} !important;
    border-bottom: 1px solid rgba(255,255,255,0.055); white-space: nowrap;
}}
table.gt tbody tr:nth-child(even) {{ background: rgba(255,255,255,0.022); }}
table.gt tbody tr:hover {{ background: rgba(255,209,102,0.085); }}
table.gt td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
table.gt td.hi {{ color:{C_GOLD} !important; font-weight:700; }}
table.gt td.g  {{ color:{C_GREEN} !important; font-weight:600; }}
table.gt td.a  {{ color:{C_AMBER} !important; font-weight:600; }}
table.gt td.r  {{ color:{C_RED} !important; font-weight:700; }}
table.gt td.b  {{ color:{C_BLUE} !important; font-weight:600; }}
table.gt td.d  {{ color:{C_TEXT_DIM} !important; }}

/* ---------- กล่องแจ้งเตือนของเราเอง ---------- */
.al {{
    display:flex; gap:12px; align-items:flex-start; padding:13px 17px; border-radius:13px;
    margin: 9px 0; backdrop-filter: blur(20px); font-size:14.5px; line-height:1.65;
    border: 1px solid rgba(255,255,255,0.10);
}}
.al .ic {{ font-size:18px; line-height:1.4; }}
.al.i {{ background: rgba(125,211,252,0.11); border-left:4px solid {C_BLUE}; color:{C_TEXT}; }}
.al.s {{ background: rgba(74,222,128,0.11); border-left:4px solid {C_GREEN}; color:{C_TEXT}; }}
.al.w {{ background: rgba(251,191,36,0.11); border-left:4px solid {C_AMBER}; color:{C_TEXT}; }}
.al.e {{ background: rgba(248,113,113,0.12); border-left:4px solid {C_RED}; color:{C_TEXT}; }}

/* ---------- Legend ---------- */
.lg {{ display:flex; flex-wrap:wrap; gap:9px; margin:10px 0 14px 0; }}
.lg span {{
    background: rgba(255,255,255,0.055); border:1px solid rgba(255,255,255,0.11);
    border-radius: 20px; padding: 5px 13px; font-size: 13px; color:{C_TEXT_DIM};
}}

/* ---------- Loader ---------- */
@keyframes moveRoad {{ 0%{{background-position:0 0}} 100%{{background-position:-120px 0}} }}
@keyframes truckV {{ 0%{{transform:translateY(0)}} 50%{{transform:translateY(-3px)}} 100%{{transform:translateY(0)}} }}
.loader {{
    text-align:center; padding:2.4rem; color:{C_GOLD}; font-weight:600; font-size:16px;
    border-radius:18px; background: rgba(255,255,255,0.05); backdrop-filter: blur(26px);
    border:1px solid rgba(255,255,255,0.12); margin-bottom:18px; position:relative; overflow:hidden;
}}
.loader::after {{
    content:""; position:absolute; bottom:10px; left:0; width:100%; height:4px;
    background: repeating-linear-gradient(90deg,{C_GOLD},{C_GOLD} 35px,transparent 35px,transparent 70px);
    animation: moveRoad 1s linear infinite; opacity:.75;
}}
.loader img {{ width:145px; animation: truckV .4s ease-in-out infinite; margin-bottom:10px; }}
.stSpinner > div > div {{ display:none !important; }}

/* ---------- ตารางเนทีฟ (สำหรับตารางรายละเอียดขนาดใหญ่) ---------- */
[data-testid="stDataFrame"] {{
    border-radius: 14px; overflow: hidden; border: 1px solid rgba(255,255,255,0.11);
}}
hr {{ border-color: rgba(255,255,255,0.09) !important; margin: 1.6rem 0 !important; }}
#MainMenu, footer {{ visibility: hidden; }}
</style>
''', unsafe_allow_html=True)

def section(title: str, sub: str = ''):
    st.markdown(f'<div class="section-head"><span class="t">{title}</span>'
                f'<span class="s">{sub}</span></div>', unsafe_allow_html=True)

def alert(msg: str, kind: str = 'i', icon: str = ''):
    ic = icon or {'i': 'ℹ️', 's': '✅', 'w': '⚠️', 'e': '🚨'}.get(kind, 'ℹ️')
    st.markdown(f'<div class="al {kind}"><span class="ic">{ic}</span><span>{msg}</span></div>',
                unsafe_allow_html=True)

def kpi_row(items: List[dict]):
    """items: [{label, value, delta, tone('good'|'warn'|'bad'|'info'|'gold'),
                dir('up'|'dn'|'nu')}]"""
    cells = []
    for it in items:
        d = it.get('delta', '')
        dh = (f'<div class="dl {it.get("dir","nu")}">{_html.escape(str(d))}</div>' if d else '')
        cells.append(
            f'<div class="kpi {it.get("tone","info")}">'
            f'<div class="lb">{_html.escape(str(it["label"]))}</div>'
            f'<div class="vl">{_html.escape(str(it["value"]))}</div>{dh}</div>')
    st.markdown(f'<div class="kpi-grid">{"".join(cells)}</div>', unsafe_allow_html=True)

def _cell_class(col: str, val) -> str:
    s = str(val)
    if any(k in s for k in ('🔴', '🚨', '⛔', '🆘')):
        return 'r'
    if any(k in s for k in ('🟡', '⚠️', '🚚')):
        return 'a'
    if any(k in s for k in ('🟢', '✅')):
        return 'g'
    if any(k in s for k in ('⚪', '🆕', '🔒', '📅')):
        return 'b'
    if isinstance(val, (int, float, np.integer, np.floating)) and not isinstance(val, bool):
        return 'num'
    return ''

def glass_table(df: pd.DataFrame, max_h: int = 460, highlight: Optional[str] = None):
    """ตาราง HTML ที่คุมสี/ขนาดเองทั้งหมด — อ่านง่ายกว่า dataframe เนทีฟบนพื้นเข้ม"""
    if df is None or df.empty:
        alert('ไม่มีข้อมูลสำหรับแสดงผล', 'i')
        return
    cols = [c for c in df.columns if not str(c).startswith('_')]
    th = ''.join(f'<th>{_html.escape(str(c))}</th>' for c in cols)
    rows = []
    for _, r in df.iterrows():
        tds = []
        for c in cols:
            v = r[c]
            if v is None or (isinstance(v, float) and math.isnan(v)):
                txt, cls = '-', 'd'
            else:
                txt = f"{v:,}" if isinstance(v, (int, np.integer)) and not isinstance(v, bool) \
                    else (f"{v:,.1f}" if isinstance(v, (float, np.floating)) else str(v))
                cls = _cell_class(str(c), v)
            if highlight and str(c) == highlight:
                cls = (cls + ' hi').strip()
            tds.append(f'<td class="{cls}">{_html.escape(txt)}</td>')
        rows.append(f'<tr>{"".join(tds)}</tr>')
    st.markdown(
        f'<div class="gt-wrap" style="max-height:{max_h}px"><table class="gt">'
        f'<thead><tr>{th}</tr></thead><tbody>{"".join(rows)}</tbody></table></div>',
        unsafe_allow_html=True)

def legend(items: List[str]):
    st.markdown('<div class="lg">' + ''.join(f'<span>{i}</span>' for i in items) + '</div>',
                unsafe_allow_html=True)

def show_loader(ph, msg: str):
    try:
        with open("truck.jpg", "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        html = f'<div class="loader"><img src="data:image/jpeg;base64,{b64}"><br>{msg}</div>'
    except FileNotFoundError:
        html = f'<div class="loader">🚛<br>{msg}</div>'
    ph.markdown(html, unsafe_allow_html=True)

def reset_results():
    for k in ('result', 'cfg_used', 'mor_plan', 'mor_rep', 'mor_summ'):
        st.session_state.pop(k, None)

def do_rerun():
    try:
        st.rerun()
    except Exception:
        try:
            st.experimental_rerun()
        except Exception:
            pass

# =====================================================================================
#  SECTION 9 — HEADER & DATA LOADING
# =====================================================================================
st.markdown(f'''
<div class="glass-card" style="text-align:center;padding:26px 20px;">
  <div style="font-size:33px;font-weight:700;color:{C_GOLD};letter-spacing:.4px;">
     🚛 Smart Route Rebalancer
  </div>
  <div style="font-size:15px;color:{C_TEXT_DIM};margin-top:7px;">
     ระบบปรับสมดุลสายส่งหลายคันพร้อมกัน &nbsp;·&nbsp; วิเคราะห์ต้นทุนเชิงเที่ยว &nbsp;·&nbsp;
     <span style="color:{C_BLUE}">Production v3.0</span>
  </div>
</div>''', unsafe_allow_html=True)

if not HAS_SCIPY:
    alert('ไม่พบไลบรารี <b>scipy</b> — ระบบจะใช้โหมดคำนวณสำรองซึ่งช้ากว่ามาก'
          'เมื่อข้อมูลเกิน 5,000 จุด แนะนำติดตั้งด้วย <code>pip install scipy</code>', 'w')

st.sidebar.markdown("### 📁 1. นำเข้าข้อมูล")
sheet_url = st.sidebar.text_input("🔗 ลิงก์ Google Sheets", placeholder="วางลิงก์ที่นี่...",
                                  on_change=reset_results)
raw_gid = st.sidebar.text_input("แท็บชีต (GID)", value="0", on_change=reset_results)
_gm = re.search(r'gid=([0-9]+)', raw_gid)
sheet_gid = _gm.group(1) if _gm else ("".join(filter(str.isdigit, raw_gid)) or "0")

@st.cache_data(ttl=300, show_spinner=False)
def load_sheet(url: str, gid: str):
    try:
        m = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
        if not m:
            return None, "ลิงก์ Google Sheets ไม่ถูกต้อง"
        d = pd.read_csv(
            f"https://docs.google.com/spreadsheets/d/{m.group(1)}/export?format=csv&gid={gid}",
            dtype=str)
        return (None, "ไม่พบข้อมูลในแท็บนี้") if d.empty else (d, None)
    except Exception as e:
        return None, f"เกิดข้อผิดพลาด: {e}"

df = None
if sheet_url:
    key = f"{sheet_url}::{sheet_gid}"
    if st.session_state.get('raw_key') != key:
        _ph = st.empty()
        show_loader(_ph, "กำลังเชื่อมต่อฐานข้อมูล... 💧")
        _raw, _err = load_sheet(sheet_url, sheet_gid)
        st.session_state.update({'raw_df': _raw, 'raw_err': _err, 'raw_key': key})
        reset_results()
        _ph.empty()
    df = st.session_state.get('raw_df')
    if df is None and st.session_state.get('raw_err'):
        st.sidebar.error(f"❌ {st.session_state['raw_err']}")

if df is None or df.empty:
    alert('กรุณาวางลิงก์ <b>Google Sheets</b> ที่แถบเมนูด้านซ้าย เพื่อเริ่มต้นใช้งาน '
          '(ต้องตั้งค่าการแชร์เป็น "ทุกคนที่มีลิงก์สามารถดูได้")', 'i', '👈')
    st.stop()

df = df.copy()
cols = df.columns.tolist()

# =====================================================================================
#  SECTION 10 — COLUMN MAPPING
# =====================================================================================
st.sidebar.markdown("---")
st.sidebar.markdown("### 🧭 2. ยืนยันคอลัมน์ข้อมูล")

def sel(label, keys, allow_none=False):
    g = guess_col(keys, cols, allow_none=allow_none)
    if allow_none:
        opts = ["-- ไม่มี --"] + cols
        i = (cols.index(g) + 1) if g in cols else 0
        v = st.sidebar.selectbox(label, opts, index=i, on_change=reset_results)
        return None if v == "-- ไม่มี --" else v
    return st.sidebar.selectbox(label, cols, index=cols.index(g) if g in cols else 0,
                                on_change=reset_results)

vol_col = sel("ยอด (ถัง/เดือน)", ['ยอด', 'เดือน', 'volume'])
lat_col = sel("ละติจูด", ['ละติจูด', 'lat'])
lon_col = sel("ลองจิจูด", ['ลอง', 'lon', 'lng'])
truck_col = sel("เบอร์รถ", ['เบอร์รถ', 'รถ', 'truck'])
day_col = sel("📅 วันจัดส่ง", ['สัปดาห์', 'วัน', 'รอบ', 'day'])
id_col = sel("รหัสลูกค้า", ['รหัส', 'id', 'code'])
vip_col = sel("VIP / เงื่อนไขพิเศษ", ['vip', 'เงื่อนไข'], allow_none=True)
name_col = sel("ชื่อลูกค้า", ['ชื่อ', 'name'], allow_none=True)

df[lat_col] = pd.to_numeric(df[lat_col], errors='coerce')
df[lon_col] = pd.to_numeric(df[lon_col], errors='coerce')
df[vol_col] = pd.to_numeric(df[vol_col], errors='coerce').fillna(0).round().astype(int)
df[truck_col] = df[truck_col].astype(str).str.strip()
df[id_col] = df[id_col].astype(str).str.strip()
df['VIP_Status'] = df[vip_col].astype(str).str.strip() if vip_col else 'ปกติ'

_n0 = len(df)
df = df.dropna(subset=[lat_col, lon_col]).reset_index(drop=True)
df = df[~df[truck_col].str.lower().isin(NO_TRUCK_TOKENS)].reset_index(drop=True)
if _n0 - len(df) > 0:
    st.sidebar.warning(f"⚠️ ตัดทิ้ง {_n0-len(df)} รายการ (พิกัดว่าง/เบอร์รถว่าง)")
st.sidebar.success(f"✅ โหลดสำเร็จ {len(df):,} รายการ")

available_trucks = clean_truck_ids(df[truck_col].unique())

# =====================================================================================
#  SECTION 11 — CONTROL LIMITS & TRIP ECONOMICS
# =====================================================================================
st.sidebar.markdown("---")
st.sidebar.markdown("### 📏 3. เพดานควบคุม & ต้นทุน")
monthly_cap = st.sidebar.number_input("ความจุอ้างอิง (ถัง/เดือน/คัน) = 100%",
                                      1000.0, 30000.0, DEFAULT_MONTHLY_CAPACITY, 40.0,
                                      on_change=reset_results)
trip_cap = st.sidebar.number_input("ความจุรถต่อเที่ยว (ถัง)", 20.0, 300.0, 78.0, 1.0,
                                   help="ใช้คำนวณว่าวันนั้นต้องวิ่งกี่เที่ยว",
                                   on_change=reset_results)
trips_norm = st.sidebar.number_input("เที่ยวปกติต่อวัน", 1, 4, 2, on_change=reset_results)
daily_cap = st.sidebar.number_input("เพดานยอดส่งต่อวัน (ถัง)", 30.0, 600.0,
                                    float(trip_cap * trips_norm), 1.0,
                                    on_change=reset_results)
max_stops_day = st.sidebar.number_input("เพดานจุดจอดต่อวัน", 10, 400,
                                        DEFAULT_MAX_STOPS_PER_DAY, 5,
                                        help="เวลาคนขับถูกจำกัดด้วยจำนวนจุดจอด ไม่ใช่แค่จำนวนถัง",
                                        on_change=reset_results)
cost_trip = st.sidebar.number_input("ต้นทุนเบิกน้ำ 1 เที่ยว (฿)", 50.0, 5000.0, 450.0, 10.0,
                                    on_change=reset_results)
cost_km = st.sidebar.number_input("ต้นทุนต่อกิโลเมตร (฿)", 1.0, 100.0, 8.5, 0.5,
                                  on_change=reset_results)
safety_buf = st.sidebar.number_input("กันบัฟเฟอร์ต่อวัน (ถัง)", 0.0, 30.0, 4.0, 1.0,
                                     help="กันที่ว่างไว้ไม่ให้อัดเต็มเพดานพอดี "
                                          "ป้องกันลูกค้าสั่งเพิ่มแล้วต้องเบิกรอบพิเศษ",
                                     on_change=reset_results)

cap_units = daily_cap * DAYS_PER_MONTH
st.sidebar.caption(f"เพดาน {daily_cap:,.0f} ถัง/วัน × {DAYS_PER_MONTH:.1f} วัน "
                   f"≈ **{cap_units:,.0f} ถัง/เดือน** ({cap_units/monthly_cap*100:,.0f}% ของความจุ)")

econ = TripEconomics(trip_capacity=trip_cap, trips_normal=int(trips_norm),
                     cost_per_trip=cost_trip, cost_per_km=cost_km)
probe_cfg = ZoningConfig(lat_col=lat_col, lon_col=lon_col, vol_col=vol_col,
                         truck_col=truck_col, id_col=id_col, day_col=day_col,
                         name_col=name_col, monthly_capacity=monthly_cap,
                         daily_control_cap=daily_cap, max_stops_per_day=int(max_stops_day))

# =====================================================================================
#  SECTION 12 — FLEET DIAGNOSTIC
# =====================================================================================
diag = diagnose_fleet(df, probe_cfg, econ)
overloaded = diag.loc[diag['สถานะ'] == '🔴 เกินเพดาน', 'เบอร์รถ'].tolist() if not diag.empty else []
excess_total = float(diag['ส่วนเกิน/วัน'].sum()) * DAYS_PER_MONTH if not diag.empty else 0.0
extra_trips_now = int(diag['เที่ยวพิเศษ/สัปดาห์'].sum()) if not diag.empty else 0

section("🩺 ผลวินิจฉัยสถานะรถปัจจุบัน", "ก่อนปรับโครงสร้าง")
kpi_row([
    {'label': 'จำนวนรถทั้งหมด', 'value': f"{len(diag)} คัน", 'tone': 'info'},
    {'label': 'รถที่เกินเพดาน', 'value': f"{len(overloaded)} คัน",
     'delta': f"เพดาน {daily_cap:,.0f} ถัง/วัน", 'dir': 'nu',
     'tone': 'bad' if overloaded else 'good'},
    {'label': 'ยอดรวมทั้งสาขา', 'value': f"{df[vol_col].sum():,.0f}",
     'delta': 'ถัง/เดือน', 'dir': 'nu', 'tone': 'gold'},
    {'label': 'ยอดส่วนเกินที่ต้องย้าย', 'value': f"{excess_total:,.0f}",
     'delta': f"≈ {math.ceil(excess_total/max(1.0,cap_units))} คันรถ", 'dir': 'nu',
     'tone': 'warn' if excess_total > 0 else 'good'},
    {'label': 'เที่ยวพิเศษที่ต้องวิ่ง', 'value': f"{extra_trips_now} เที่ยว/สัปดาห์",
     'delta': f"≈ {extra_trips_now*cost_trip*52:,.0f} ฿/ปี", 'dir': 'dn',
     'tone': 'bad' if extra_trips_now else 'good'},
])
glass_table(diag, max_h=340, highlight='เบอร์รถ')

# =====================================================================================
#  SECTION 13 — DONOR SELECTION
# =====================================================================================
st.sidebar.markdown("---")
st.sidebar.markdown("### 🚚 4. เลือกรถต้นทาง (Donors)")
st.sidebar.caption("รองรับหลายคันพร้อมกัน — ระบบเลือกคันที่เกินเพดานให้อัตโนมัติ")

dissolve_trucks = st.sidebar.multiselect("🗑️ ยุบทั้งคัน (กระจายงานออกทั้งหมด)",
                                         available_trucks, [], on_change=reset_results)
relieve_trucks = st.sidebar.multiselect(
    "✂️ ดึงงานออกบางส่วน (ลดให้อยู่ในเพดาน)",
    [t for t in available_trucks if t not in dissolve_trucks],
    [t for t in overloaded if t not in dissolve_trucks], on_change=reset_results)
new_raw = st.sidebar.text_input("➕ เบอร์รถคันใหม่ (คั่นด้วยจุลภาค)", "",
                                placeholder="เช่น 15112, 15113", on_change=reset_results)
new_trucks = [t.strip() for t in new_raw.split(',') if t.strip()]
new_trucks = [t for t in dict.fromkeys(new_trucks) if t not in available_trucks]

vol_by_truck_all = df.groupby(truck_col)[vol_col].sum().to_dict()
kept_trucks = [t for t in available_trucks if t not in dissolve_trucks]
_, leftover = compute_default_targets(vol_by_truck_all, dissolve_trucks,
                                      kept_trucks, new_trucks, cap_units)
if leftover > 1e-6:
    st.sidebar.error(f"🚨 ความจุไม่พอ ขาดอีก {leftover:,.0f} ถัง/เดือน — "
                     f"ควรเพิ่มรถใหม่อีกอย่างน้อย **{math.ceil(leftover/cap_units)} คัน**")
elif new_trucks:
    st.sidebar.success(f"✅ ความจุเพียงพอ (รถใหม่ {len(new_trucks)} คัน)")

active_trucks = kept_trucks + new_trucks
if not active_trucks:
    alert('ไม่เหลือรถสำหรับจัดสรรงาน กรุณาตรวจสอบการเลือกรถที่ยุบ', 'e')
    st.stop()

# =====================================================================================
#  SECTION 14 — TARGET SLIDERS
# =====================================================================================
st.sidebar.markdown("---")
st.sidebar.markdown("### 🎛️ 5. เป้าหมายรายคัน (%)")

fp = "|".join([sheet_url, sheet_gid, vol_col, truck_col, day_col, str(sorted(dissolve_trucks)),
               str(sorted(relieve_trucks)), str(new_trucks), f"{monthly_cap}", f"{daily_cap}"])
if st.sidebar.button("🔄 คำนวณเป้าหมายอัตโนมัติ"):
    st.session_state.pop('slider_fp', None)
    reset_results()

if st.session_state.get('slider_fp') != fp:
    for k in [k for k in list(st.session_state.keys())
              if k.startswith('slider_') or k.startswith('lock_')]:
        del st.session_state[k]
    tg, _ = compute_default_targets(vol_by_truck_all, dissolve_trucks,
                                    kept_trucks, new_trucks, cap_units)
    st.session_state.truck_pcts = {
        t: float(round(max(0.0, min(200.0, tg.get(t, 0.0) / monthly_cap * 100)), 1))
        for t in active_trucks}
    for t in active_trucks:
        st.session_state[f"slider_{t}"] = st.session_state.truck_pcts[t]
    st.session_state['slider_fp'] = fp

def on_slider_change(changed: str):
    nv = max(0.0, min(200.0, st.session_state.get(f"slider_{changed}", 0.0)))
    diff = nv - st.session_state.truck_pcts.get(changed, nv)
    if abs(diff) < 0.01:
        return
    free = [t for t in active_trucks
            if t != changed and not st.session_state.get(f"lock_{t}", False)]
    if free:
        share = diff / len(free)
        ok = all(0.0 <= st.session_state.truck_pcts.get(t, 0.0) - share <= 200.0 for t in free)
        for t in free:
            v = (st.session_state.truck_pcts[t] - share) if ok else (0.0 if share > 0 else 200.0)
            v = round(max(0.0, min(200.0, v)), 1)
            st.session_state.truck_pcts[t] = v
            st.session_state[f"slider_{t}"] = v
    st.session_state.truck_pcts[changed] = round(nv, 1)
    reset_results()

target_pcts: Dict[str, float] = {}
for t in active_trucks:
    c1, c2 = st.sidebar.columns([3, 1.1])
    with c2:
        st.markdown("<div style='margin-top:30px'></div>", unsafe_allow_html=True)
        st.checkbox("🔒", key=f"lock_{t}", on_change=reset_results)
    with c1:
        tag = "🆕 " if t in new_trucks else ("✂️ " if t in relieve_trucks else "")
        st.session_state.setdefault(f"slider_{t}", st.session_state.truck_pcts.get(t, 0.0))
        v = st.slider(f"{tag}รถ {t} (%)", 0.0, 200.0, step=0.1,
                      key=f"slider_{t}", on_change=on_slider_change, args=(t,))
        target_pcts[t] = max(0.0, min(200.0, v))
        st.session_state.truck_pcts[t] = target_pcts[t]

sys_pct = float(df[vol_col].sum()) / monthly_cap * 100
tot_pct = sum(target_pcts.values())
st.sidebar.info(f"💧 ต้องจัดสรรจริง {sys_pct:,.1f}% | ตั้งเป้ารวม {tot_pct:,.1f}%")
if sys_pct > 0 and abs(tot_pct - sys_pct) / sys_pct > 0.05:
    st.sidebar.warning("⚠️ ผลรวมเป้าหมายต่างจากยอดจริงเกิน 5% — เสี่ยงเกิด Overflow")

# =====================================================================================
#  SECTION 15 — RULES / ADVANCED / ROAD
# =====================================================================================
st.sidebar.markdown("---")
st.sidebar.markdown("### 🔒 6. ล็อก Key Account")
manual_vips = st.sidebar.multiselect("รหัสสมาชิกที่ห้ามย้ายสาย",
                                     df[id_col].unique().tolist(), [], on_change=reset_results)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🎯 7. กฎลำดับความสำคัญ")
st.sidebar.caption("1) VIP Lock → 2) Core Lock → 3) Daily Threshold → 4) Target Matching")
core_ratio_pct = st.sidebar.slider("สัดส่วนแกนกลางที่ล็อก (Core %)", 0, 100, 65, 5,
                                   on_change=reset_results)
tol_mode_label = st.sidebar.radio("ฐานการคิดค่าเผื่อ",
                                  ["% ของเป้าหมายรถคันนั้น", "% ของความจุเต็ม"], 0,
                                  on_change=reset_results)
tolerance_pct = st.sidebar.number_input("ค่าเผื่อเป้าหมาย (%)", 0.0, 50.0, 5.0, 0.5,
                                        on_change=reset_results)
allow_vip_day = st.sidebar.checkbox("อนุญาตให้ย้ายวันของลูกค้า VIP", False,
                                    on_change=reset_results)

with st.sidebar.expander("⚙️ 8. ตั้งค่าขั้นสูง (Optimizer)"):
    en_stray = st.checkbox("ล้างเกาะเดี่ยว (Stray Cleanup)", True, on_change=reset_results)
    en_major = st.checkbox("ขัดผิวรอยต่อ (Majority Vote)", True, on_change=reset_results)
    en_swap = st.checkbox("สลับคู่ข้ามคัน (2-opt Swap)", True, on_change=reset_results)
    knn_k = st.slider("จำนวนเพื่อนบ้าน (k)", 4, 20, 8, on_change=reset_results)
    swap_rounds = st.slider("รอบการสลับคู่", 1, 8, 3, on_change=reset_results)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🛣️ 9. ระยะทางถนนจริง")
use_road = st.sidebar.checkbox("ใช้ระยะทางถนนจริง (เรียก API)", False, on_change=reset_results)
road_provider, osrm_url, gkey = 'osrm', 'https://router.project-osrm.org', ''
if use_road:
    road_provider = st.sidebar.radio("ผู้ให้บริการ", ["osrm", "google"],
                                     format_func=lambda x: "OSRM (ฟรี)" if x == "osrm"
                                     else "Google Distance Matrix", on_change=reset_results)
    n_stop_est = df.groupby([lat_col, lon_col]).ngroups
    if road_provider == 'osrm':
        osrm_url = st.sidebar.text_input("OSRM Server URL", "https://router.project-osrm.org",
                                         on_change=reset_results)
        st.sidebar.caption(f"⚠️ demo server จำกัดโควตา — ข้อมูลนี้ ~{n_stop_est:,} จุด "
                           f"จะถูกแบ่งเป็นหลาย request")
    else:
        gkey = st.sidebar.text_input("Google Maps API Key", "", type="password",
                                     on_change=reset_results)
        el = n_stop_est * len(active_trucks)
        st.sidebar.caption(f"💰 ประมาณ {el:,} elements ≈ ${el/1000*5:,.2f} (เรต &#36;5/1k)")
        if not gkey:
            st.sidebar.warning("⚠️ ยังไม่ใส่ API Key — ระบบจะใช้ระยะทางเส้นตรงแทน")

cfg = ZoningConfig(
    lat_col=lat_col, lon_col=lon_col, vol_col=vol_col, truck_col=truck_col, id_col=id_col,
    day_col=day_col, name_col=name_col, monthly_capacity=monthly_cap,
    daily_control_cap=daily_cap, max_stops_per_day=int(max_stops_day),
    core_ratio=float(core_ratio_pct), tol_pct=float(tolerance_pct),
    tol_mode='target' if tol_mode_label.startswith('% ของเป้า') else 'capacity',
    knn_k=int(knn_k), enable_stray_cleanup=en_stray, enable_majority_vote=en_major,
    enable_swap=en_swap, swap_rounds=int(swap_rounds), allow_vip_day_move=allow_vip_day,
    daily_safety_buffer=float(safety_buf), use_road=use_road, road_provider=road_provider,
    osrm_url=osrm_url, gmaps_key=gkey)

with st.sidebar.expander("💾 10. บันทึก / เรียกคืนสถานการณ์"):
    scen = {'pcts': st.session_state.get('truck_pcts', {}), 'dissolve': dissolve_trucks,
            'relieve': relieve_trucks, 'new': new_trucks, 'core': core_ratio_pct,
            'tol': tolerance_pct, 'daily_cap': daily_cap, 'vips': manual_vips}
    st.download_button("⬇️ ดาวน์โหลด scenario.json",
                       json.dumps(scen, ensure_ascii=False, indent=2).encode('utf-8'),
                       "scenario.json", "application/json", use_container_width=True)
    up = st.file_uploader("⬆️ อัปโหลด scenario.json", type=['json'])
    if up is not None:
        try:
            s = json.load(up)
            for t, v in s.get('pcts', {}).items():
                if t in active_trucks:
                    st.session_state[f"slider_{t}"] = float(v)
                    st.session_state.truck_pcts[t] = float(v)
            st.success("โหลดสถานการณ์สำเร็จ")
        except Exception as e:
            st.error(f"ไฟล์ไม่ถูกต้อง: {e}")

# =====================================================================================
#  SECTION 16 — RUN
# =====================================================================================
st.sidebar.markdown("---")
if st.sidebar.button("🚀 ประมวลผลจัดสายส่งใหม่", use_container_width=True):
    if not new_trucks and not dissolve_trucks and not relieve_trucks:
        st.sidebar.error("❌ กรุณาเลือกรถต้นทาง หรือระบุเบอร์รถคันใหม่อย่างน้อย 1 คัน")
        st.stop()
    ph = st.empty()
    msg = "กำลังจัดสรรเส้นทาง (Multi-Donor Zoning)... 💧"
    if use_road:
        msg += "<br><span style='font-size:14px'>กำลังเรียก API ระยะทางถนนจริง อาจใช้เวลาสักครู่</span>"
    show_loader(ph, msg)

    def getter(src, dst):
        if cfg.road_provider == 'osrm':
            return fetch_osrm_matrix(src, dst, cfg.osrm_url)
        return fetch_google_matrix(src, dst, cfg.gmaps_key) if cfg.gmaps_key \
            else (None, 'ไม่ได้ระบุ Google API Key')

    try:
        st.session_state['result'] = run_multi_donor_zoning(
            df, cfg, econ, target_pcts, dissolve_trucks, relieve_trucks,
            new_trucks, manual_vips, getter if use_road else None)
        st.session_state['cfg_used'] = cfg
        st.session_state.pop('mor_plan', None)
        st.session_state.pop('mor_rep', None)
    except Exception as e:
        ph.empty()
        st.exception(e)
        st.stop()
    ph.empty()

if 'result' not in st.session_state:
    alert('ตรวจผลวินิจฉัยด้านบน เลือกรถต้นทาง / รถใหม่ '
          'แล้วกดปุ่ม <b>🚀 ประมวลผลจัดสายส่งใหม่</b> ที่แถบเมนูด้านซ้าย', 'i', '👈')
    st.stop()

res: ZoningResult = st.session_state['result']
ucfg: ZoningConfig = st.session_state['cfg_used']
rdf = res.result_df

for w in res.warnings:
    alert(w, 'w')
for i in res.infos:
    alert(i, 'i')

ov = rdf[rdf['เบอร์รถใหม่'] == OVERFLOW_LABEL]
if not ov.empty:
    need = math.ceil(ov[ucfg.vol_col].sum() / max(1.0, cap_units))
    alert(f"ลูกค้า <b>{len(ov):,} ราย</b> ({ov[ucfg.vol_col].sum():,.0f} ถัง/เดือน) "
          f"จัดสรรไม่ได้ — ควรเพิ่มรถอีกประมาณ <b>{need} คัน</b> หรือเพิ่ม % เป้าหมาย", 'e')

# =====================================================================================
#  SECTION 17 — RESULT TABS
# =====================================================================================
tab_sum, tab_map, tab_daily, tab_mor, tab_detail = st.tabs(
    ["📈 สรุปผล", "🗺️ แผนที่โซน", "📅 โหลดรายวัน", "🧗 แก้ยอดเกินเพดาน", "📋 รายละเอียด"])

# ---------------------------------------------------------------- TAB 1: SUMMARY
with tab_sum:
    m = res.metrics
    section("📈 ตัวชี้วัดผลลัพธ์", "เปรียบเทียบก่อน → หลัง")
    kpi_row([
        {'label': 'รถที่เกินเพดาน', 'value': f"{int(m['over_after'])} คัน",
         'delta': f"{int(m['over_after']-m['over_before']):+d} คัน",
         'dir': 'up' if m['over_after'] <= m['over_before'] else 'dn',
         'tone': 'good' if m['over_after'] == 0 else 'bad'},
        {'label': 'โหลดสูงสุดในฝูง', 'value': f"{m['peak_after']:,.0f} ถัง/วัน",
         'delta': f"{m['peak_after']-m['peak_before']:+,.0f}",
         'dir': 'up' if m['peak_after'] <= m['peak_before'] else 'dn',
         'tone': 'good' if m['peak_after'] <= ucfg.daily_control_cap else 'warn'},
        {'label': 'เที่ยวพิเศษต่อสัปดาห์', 'value': f"{int(m['trips_after'])} เที่ยว",
         'delta': f"{int(m['trips_after']-m['trips_before']):+d} "
                  f"({(m['trips_after']-m['trips_before'])*cost_trip*52:+,.0f} ฿/ปี)",
         'dir': 'up' if m['trips_after'] <= m['trips_before'] else 'dn',
         'tone': 'good' if m['trips_after'] <= m['trips_before'] else 'bad'},
        {'label': 'ความกระชับโซนเฉลี่ย', 'value': f"{m['compact_after_km']:.2f} กม.",
         'delta': f"{m['compact_after_km']-m['compact_before_km']:+.2f} กม.",
         'dir': 'up' if m['compact_after_km'] <= m['compact_before_km'] else 'dn',
         'tone': 'info'},
        {'label': 'ลูกค้าที่ต้องย้ายสาย', 'value': f"{int(m['moved_cust']):,} ราย",
         'delta': f"{m['moved_pct']:.1f}% ของทั้งหมด", 'dir': 'nu', 'tone': 'gold'},
    ])
    st.caption(f"ส่วนเบี่ยงเบนโหลดระหว่างคัน {m['std_before']:.1f} → **{m['std_after']:.1f}** "
               f"(ยิ่งต่ำยิ่งสมดุล) · ยอดที่ย้าย {m['moved_vol']:,.0f} ถัง/เดือน "
               f"· Core % ที่ใช้จริง {res.core_ratio_used:.0f}%")

    section("🎯 เทียบเป้าหมาย vs ผลจริง", "Priority 4: Strict Target Matching")
    rows = []
    for t, tg in res.targets.items():
        if tg <= 0:
            continue
        act = float(rdf.loc[rdf['เบอร์รถใหม่'] == t, ucfg.vol_col].sum())
        tolu = _tolerance_for(t, res.targets, ucfg)
        rows.append({'เบอร์รถ': t,
                     'ประเภท': '🆕 ใหม่' if t in new_trucks else
                               ('✂️ ดึงงานออก' if t in relieve_trucks else 'คงเดิม'),
                     'เป้าหมาย(%)': round(tg / ucfg.monthly_capacity * 100, 1),
                     'ทำได้จริง(%)': round(act / ucfg.monthly_capacity * 100, 1),
                     'ส่วนต่าง(ถัง)': int(round(act - tg)),
                     'ค่าเผื่อ(±ถัง)': int(round(tolu)),
                     'สถานะ': '✅ ในเกณฑ์' if abs(act - tg) <= tolu else '⚠️ เกินค่าเผื่อ'})
    glass_table(pd.DataFrame(rows), 400, 'เบอร์รถ')

    cA, cB = st.columns(2)
    with cA:
        st.markdown("##### ก่อนปรับ")
        sb = df.groupby(truck_col).agg(ลูกค้า=(truck_col, 'count'),
                                       **{'ยอด(ถัง/เดือน)': (vol_col, 'sum')}).reset_index()
        sb = sb.rename(columns={truck_col: 'เบอร์รถ'})
        glass_table(sb, 340)
    with cB:
        st.markdown("##### หลังปรับ")
        sa = rdf.groupby('เบอร์รถใหม่').agg(
            ลูกค้า=('เบอร์รถใหม่', 'count'),
            **{'ยอด(ถัง/เดือน)': (vol_col, 'sum')}).reset_index()
        sa['ภาระงาน(%)'] = np.where(
            sa['เบอร์รถใหม่'] == OVERFLOW_LABEL, '-',
            (sa['ยอด(ถัง/เดือน)'] / ucfg.monthly_capacity * 100).round(1).astype(str) + '%')
        glass_table(sa, 340)

# ---------------------------------------------------------------- TAB 2: MAPS
with tab_map:
    section("🗺️ แผนที่เปรียบเทียบการกระจายตัว", "ซ้าย = เดิม | ขวา = หลังปรับ")
    truck_list = [t for t in sorted(rdf['เบอร์รถใหม่'].dropna().unique()) if t != OVERFLOW_LABEL]
    view = st.selectbox("🔍 รูปแบบการแสดงผล",
                        ["แสดงทั้งหมด (แยกสีตามเบอร์รถ)"] + truck_list)

    palette = ['#38BDF8', '#4ADE80', '#FB923C', '#A78BFA', '#2DD4BF',
               '#F472B6', '#FACC15', '#34D399', '#818CF8', '#FB7185']
    color_map = {t: ('#F87171' if t in new_trucks else palette[i % len(palette)])
                 for i, t in enumerate(truck_list)}

    if view.startswith("แสดงทั้งหมด"):
        mb, ma, mode = df, rdf[rdf['เบอร์รถใหม่'] != OVERFLOW_LABEL], 'truck'
        legend([f'<span style="color:{c}">●</span> รถ {t}' for t, c in list(color_map.items())[:12]])
    else:
        mb = df[df[truck_col] == view] if view in available_trucks else df.iloc[0:0]
        ma, mode = rdf[rdf['เบอร์รถใหม่'] == view], 'day'
        legend([f'<span style="color:{DAY_COLORS[d]}">●</span> {DAY_NAMES[d]}'
                for d in range(WORKING_DAYS)])

    cy_ = ma[lat_col].mean() if not ma.empty else df[lat_col].mean()
    cx_ = ma[lon_col].mean() if not ma.empty else df[lon_col].mean()

    def day_color(txt: str) -> str:
        d, _ = parse_days_from_string(txt)
        return DAY_COLORS.get(d[0], '#94A3B8') if d else '#94A3B8'

    def draw(box, data, title, tfield, dfield):
        with box:
            st.markdown(f"<div style='text-align:center;color:{C_GOLD};font-weight:600;"
                        f"font-size:15px;margin-bottom:9px'>{title}</div>",
                        unsafe_allow_html=True)
            fm = folium.Map(location=[cy_, cx_], zoom_start=12 if mode == 'truck' else 14,
                            tiles='CartoDB positron', prefer_canvas=True)
            plugins.Fullscreen(position='topright').add_to(fm)
            layer = plugins.MarkerCluster().add_to(fm) if len(data) > 1500 else fm
            for _, r in data.iterrows():
                tid = str(r[tfield])
                vip = (str(r.get('VIP_Status', '')).upper() == 'VIP'
                       or str(r[id_col]) in manual_vips)
                col = color_map.get(tid, '#94A3B8') if mode == 'truck' \
                    else day_color(str(r.get(dfield, '')))
                nm = str(r[name_col]) if name_col else 'ไม่ระบุ'
                pop = (f"<div style='font-family:Sarabun;font-size:13px;line-height:1.7'>"
                       f"<b>รหัส:</b> {r[id_col]}<br><b>ชื่อ:</b> {nm}<br>"
                       f"<b>ยอด:</b> {int(r[vol_col])} ถัง<br><b>รถ:</b> {tid}<br>"
                       f"<b>วัน:</b> {r.get(dfield,'-')}</div>")
                folium.CircleMarker([r[lat_col], r[lon_col]], radius=8 if vip else 5,
                                    color='#FFD166' if vip else col, weight=2.5 if vip else 1,
                                    fill=True, fill_color=col, fill_opacity=.88,
                                    popup=folium.Popup(pop, max_width=300)).add_to(layer)
            components.html(fm.get_root().render(), height=470)

    m1, m2 = st.columns(2)
    draw(m1, mb, "โซนเดิม (Before)", truck_col, day_col)
    draw(m2, ma, "โซนใหม่ (After — วันจัดส่งที่ปรับแล้ว)", 'เบอร์รถใหม่', 'วันจัดส่ง(ใหม่)')

# ---------------------------------------------------------------- TAB 3: DAILY
with tab_daily:
    section("📅 ตารางวิเคราะห์โหลดรายวัน", "จันทร์ – เสาร์")
    legend([f'🟢 เหมาะสม {OPTIMAL_MIN}-{OPTIMAL_MAX}', f'🟡 ควรเลี่ยง {AVOID_MIN}-{AVOID_MAX}',
            f'⚪ เบาเกิน &lt;{AVOID_MIN}', f'🔴 เกินเพดาน &gt;{ucfg.daily_control_cap:.0f}',
            f'🚚 รอบ3 {ESCALATE_TARGET_MIN}-{ESCALATE_TARGET_MAX}', f'🆘 &gt;{ESCALATE_TARGET_MAX}'])

    def day_status(v: float, cap: float) -> str:
        if v > ESCALATE_TARGET_MAX:
            return "🆘 เกินรอบ3"
        if v > ESCALATE_THRESHOLD:
            return "🚚 รอบ3"
        if v > cap:
            return "🔴 เกินเพดาน"
        if OPTIMAL_MIN <= v <= OPTIMAL_MAX:
            return "🟢 เหมาะสม"
        if AVOID_MIN <= v <= AVOID_MAX:
            return "🟡 เลี่ยง"
        return "⚪ เบาเกิน"

    tl = [t for t in sorted(rdf['เบอร์รถใหม่'].dropna().unique()) if t != OVERFLOW_LABEL]
    ds_rows = []
    for t in tl:
        mask = (rdf['เบอร์รถใหม่'] == t).to_numpy()
        dv = res.daily_matrix[mask].sum(axis=0) if mask.any() else np.zeros(WORKING_DAYS)
        dc = res.daily_stops[mask].sum(axis=0) if mask.any() else np.zeros(WORKING_DAYS)
        row = {'เบอร์รถ': t}
        row.update({DAY_NAMES[d]: int(round(dv[d])) for d in range(WORKING_DAYS)})
        row['จุดจอดสูงสุด'] = int(dc.max())
        row['โหลดสูงสุด'] = int(round(dv.max()))
        row['เที่ยวพิเศษ'] = int(sum(max(0, econ.trips_for(v) - econ.trips_normal) for v in dv))
        row['สถานะ'] = day_status(float(dv.max()), ucfg.daily_control_cap)
        ds_rows.append(row)
    glass_table(pd.DataFrame(ds_rows), 480, 'เบอร์รถ')

# ---------------------------------------------------------------- TAB 4: MOR
with tab_mor:
    section("🧗 ระบบแก้ปัญหายอดเกินเพดานเล็กน้อย",
            "Marginal Overflow Resolver — วิเคราะห์ต้นทุนแบบขั้นบันได")
    st.markdown(f'''<div class="glass-card" style="font-size:14.5px;line-height:1.85">
    <b style="color:{C_GOLD}">แนวคิด:</b> ต้นทุนการเดินรถไม่ได้เพิ่มขึ้นทีละถัง
    แต่กระโดดเป็น <b>ขั้นบันไดตามจำนวนเที่ยว</b> —
    ยอด {int(trip_cap*trips_norm)} ถัง วิ่ง {int(trips_norm)} เที่ยวพอดี
    แต่ยอด {int(trip_cap*trips_norm)+1} ถัง ต้องวิ่ง {int(trips_norm)+1} เที่ยวทันที
    โดยเที่ยวสุดท้ายขนแค่ <b>1 ถัง</b><br>
    ระบบจะแยกให้เห็นชัดว่า <span style="color:{C_GREEN}">รอบพิเศษที่คุ้มค่า</span> (ขนเต็ม)
    ต่างจาก <span style="color:{C_RED}">รอบพิเศษที่เสียเปล่า</span> (ขนไม่กี่ถัง) อย่างไร
    แล้วเสนอทางแก้ที่ <b>ประหยัดที่สุด</b> โดยเลือกลูกค้าที่มียอด "พอดี" กับส่วนที่เกิน
    </div>''', unsafe_allow_html=True)

    r1, r2, r3, r4 = st.columns(4)
    max_gap = r1.number_input("ระยะห่างรอบส่งสูงสุด (วัน)", 2, 7, 4,
                              help="กันลูกค้าน้ำหมดก่อนรอบถัดไป")
    max_detour = r2.number_input("ระยะเบี่ยงสูงสุด (กม.)", 0.5, 20.0, 3.5, 0.5)
    marg_win = r3.number_input("ขอบเขต 'เกินเล็กน้อย' (ถัง)", 5.0, 120.0, 40.0, 5.0)
    protect_vip = r4.checkbox("ห้ามแตะลูกค้า VIP", True)

    s1, s2, s3, s4, s5 = st.columns(5)
    en_shift = s1.checkbox("🔄 ย้ายวัน", True)
    en_split = s2.checkbox("✂️ ซอยยอด", True)
    en_cross = s3.checkbox("🚚 ข้ามคัน", True)
    en_bi = s4.checkbox("📅 คู่/คี่", True)
    en_swp = s5.checkbox("🔁 สลับคู่", True)

    rcfg = ResolverConfig(max_interval_days=int(max_gap), max_detour_m=max_detour * 1000,
                          protect_vip=protect_vip, marginal_window=marg_win,
                          enable_shift=en_shift, enable_split=en_split, enable_cross=en_cross,
                          enable_biweekly=en_bi, enable_swap=en_swp)

    if st.button("🔍 วิเคราะห์และเสนอทางแก้", use_container_width=True):
        with st.spinner(""):
            _ph2 = st.empty()
            show_loader(_ph2, "กำลังวิเคราะห์ต้นทุนขั้นบันได... 🧮")
            plan, rep, summ = resolve_marginal_overflow(res, ucfg, rcfg, econ)
            _ph2.empty()
        st.session_state.update({'mor_plan': plan, 'mor_rep': rep, 'mor_summ': summ})

    if 'mor_rep' in st.session_state:
        rep = st.session_state['mor_rep']
        plan = st.session_state['mor_plan']
        summ = st.session_state['mor_summ']

        section("📉 รายงานระยะห่างจากหน้าผาต้นทุน", "Cost Cliff Report")
        waste = int(rep['สูญเปล่า(฿/สัปดาห์)'].sum()) if not rep.empty else 0
        n_bad = int((rep['สถานะ'] == '🚨 รอบพิเศษไม่คุ้ม').sum()) if not rep.empty else 0
        n_risk = int((rep['สถานะ'] == '⚠️ เสี่ยงตกหน้าผา').sum()) if not rep.empty else 0
        n_good = int((rep['สถานะ'] == '🟢 รอบพิเศษคุ้มค่า').sum()) if not rep.empty else 0
        kpi_row([
            {'label': 'วันที่เบิกรอบพิเศษแบบไม่คุ้ม', 'value': f"{n_bad} วัน",
             'tone': 'bad' if n_bad else 'good'},
            {'label': 'ต้นทุนสูญเปล่า', 'value': f"{waste:,} ฿/สัปดาห์",
             'delta': f"{waste*52:,} ฿/ปี", 'dir': 'dn', 'tone': 'bad' if waste else 'good'},
            {'label': 'วันที่เสี่ยงตกหน้าผา', 'value': f"{n_risk} วัน",
             'delta': 'ลูกค้าสั่งเพิ่มนิดเดียวต้องเบิกรอบพิเศษ', 'dir': 'nu', 'tone': 'warn'},
            {'label': 'รอบพิเศษที่คุ้มค่าอยู่แล้ว', 'value': f"{n_good} วัน",
             'delta': 'ไม่ต้องแก้ไข', 'dir': 'nu', 'tone': 'good'},
        ])
        only_prob = st.checkbox("แสดงเฉพาะวันที่มีปัญหา", True)
        show = rep[rep['สถานะ'].isin(['🚨 รอบพิเศษไม่คุ้ม', '🟡 รอบพิเศษพอรับได้',
                                       '⚠️ เสี่ยงตกหน้าผา'])] if only_prob else rep
        glass_table(show, 420, 'เบอร์รถ')

        section("🛠️ แผนการแก้ไขที่ระบบแนะนำ", "เลือกลูกค้าที่ยอด 'พอดี' กับส่วนเกิน")
        if plan.empty:
            alert('ไม่พบวันที่ต้องแก้ไข — ทุกรอบพิเศษคุ้มค่าอยู่แล้ว 🎉', 's')
        else:
            kpi_row([
                {'label': 'แก้ได้', 'value': f"{summ['fixed']} วัน",
                 'delta': f"แก้ไม่ได้ {summ['unfixed']} วัน", 'dir': 'nu',
                 'tone': 'good' if summ['fixed'] else 'warn'},
                {'label': 'ผลประหยัดสุทธิ', 'value': f"{summ['net_week']:,.0f} ฿/สัปดาห์",
                 'delta': f"{summ['net_year']:,.0f} ฿/ปี", 'dir': 'up', 'tone': 'good'},
                {'label': 'ต้นทุนการย้าย', 'value': f"{summ['cost']:,.0f} ฿",
                 'delta': f"เทียบกับที่ประหยัดได้ {summ['saved']:,.0f} ฿", 'dir': 'nu',
                 'tone': 'info'},
                {'label': 'ลูกค้าที่ต้องปรับ', 'value': f"{summ['n_moves']} ราย",
                 'delta': 'กระทบน้อยที่สุดเท่าที่เป็นไปได้', 'dir': 'nu', 'tone': 'gold'},
            ])
            glass_table(plan, 480, 'รหัสลูกค้า')

            st.markdown("##### ✅ เลือกรายการที่ต้องการนำไปใช้จริง")
            opts = plan.loc[plan['ถังที่ย้าย'] > 0, 'ลำดับ'].tolist()
            if opts:
                approved = st.multiselect(
                    "รายการที่อนุมัติ", opts, default=opts,
                    format_func=lambda i: (
                        f"#{i} {plan.loc[plan['ลำดับ']==i,'กลยุทธ์'].iloc[0]} · "
                        f"{plan.loc[plan['ลำดับ']==i,'รหัสลูกค้า'].iloc[0]} → "
                        f"{plan.loc[plan['ลำดับ']==i,'ย้ายไป'].iloc[0]}"))
                a1, a2 = st.columns(2)
                if a1.button("✅ นำแผนที่เลือกไปใช้", use_container_width=True):
                    st.session_state['result'] = apply_plan(res, ucfg, plan, approved)
                    st.session_state.pop('mor_plan', None)
                    st.session_state.pop('mor_rep', None)
                    do_rerun()
                a2.download_button("📥 ดาวน์โหลดแผนการแก้ไข (CSV)",
                                   plan.to_csv(index=False).encode('utf-8-sig'),
                                   'marginal_fix_plan.csv', 'text/csv',
                                   use_container_width=True)
            else:
                alert('ไม่มีรายการที่สามารถนำไปใช้ได้ — ลองผ่อนปรนเงื่อนไข '
                      '(เพิ่มระยะห่างรอบส่ง หรือระยะเบี่ยง) แล้ววิเคราะห์ใหม่', 'w')

# ---------------------------------------------------------------- TAB 5: DETAIL
with tab_detail:
    section("📋 รายละเอียดการโยกย้าย
