# =====================================================================================
#  SMART ROUTE REBALANCER — PRODUCTION BUILD v2.0
#  Multi-Donor Fleet Rebalancing Engine
#  ---------------------------------------------------------------------------------
#  requirements.txt:
#     streamlit>=1.31  pandas>=2.0  numpy>=1.24  folium>=0.15
#     scipy>=1.10      requests>=2.31
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

st.set_page_config(page_title="Smart Route Rebalancer v2", layout="wide",
                   initial_sidebar_state="expanded")

# =====================================================================================
#  SECTION 1 — CONSTANTS & DOMAIN MODEL
# =====================================================================================
WORKING_DAYS = 6                      # จันทร์-เสาร์
WEEKS_PER_MONTH = 4.333               # 52 / 12
DAYS_PER_MONTH = WORKING_DAYS * WEEKS_PER_MONTH   # ≈ 26 วันทำงาน/เดือน

DEFAULT_MONTHLY_CAPACITY = 4160.0     # ถัง/เดือน/คัน  (= 160 ถัง/วัน × 26 วัน)
DEFAULT_DAILY_CONTROL_CAP = 156       # เพดานควบคุมของบริษัท (ถัง/วัน)
DEFAULT_MAX_STOPS_PER_DAY = 90        # เพดานจำนวนจุดจอด/วัน (ข้อจำกัดด้านเวลาคนขับ)

OVERFLOW_LABEL = 'ส่วนเกิน (Overflow)'
NO_TRUCK_TOKENS = {'', 'nan', 'none', 'null', '-', 'ไม่ระบุ', 'na', 'n/a'}

# โซนโหลดรายวัน (ถัง/วัน)
OPTIMAL_MIN, OPTIMAL_MAX = 140, 155
AVOID_MIN, AVOID_MAX = 121, 139
TARGET_DAY_CAP = 148                  # เป้าที่ smoothing พยายามดันลงมา
ESCALATE_THRESHOLD = 160              # เกินนี้ = smoothing เอาไม่อยู่
ESCALATE_TARGET_MIN, ESCALATE_TARGET_MAX = 180, 190   # ช่วงที่ยอมรับเป็น "รอบ 3"

EARTH_RADIUS_M = 6371008.8

# ---- Single Source of Truth สำหรับชื่อวัน (แก้ปัญหา 'พฤหัสฯ' vs 'พฤหัสบดี') ----
DAY_NAMES = {0: 'จันทร์', 1: 'อังคาร', 2: 'พุธ', 3: 'พฤหัสบดี', 4: 'ศุกร์', 5: 'เสาร์'}
DAY_SHORT = {0: 'จ', 1: 'อ', 2: 'พ', 3: 'พฤ', 4: 'ศ', 5: 'ส'}
DAY_COLORS = {0: '#FFD700', 1: '#FF69B4', 2: '#28A745',
              3: '#FD7E14', 4: '#00BFFF', 5: '#6F42C1'}

# token เรียงจากยาว→สั้น สำคัญมาก: ไม่งั้น 'พ' จะกิน 'พฤหัสบดี'
DAY_TOKENS: List[Tuple[str, int]] = [
    ('จันทร์', 0), ('อังคาร', 1), ('พฤหัสบดี', 3), ('พฤหัส', 3), ('พฤหัสฯ', 3),
    ('พฤ', 3), ('พุธ', 2), ('ศุกร์', 4), ('เสาร์', 5),
    ('mon', 0), ('tue', 1), ('wed', 2), ('thu', 3), ('fri', 4), ('sat', 5),
    ('จ', 0), ('อ', 1), ('พ', 2), ('ศ', 4), ('ส', 5),
]
ALL_DAYS_TOKENS = ('ทุกวัน', 'จ-ส', 'จันทร์-เสาร์', 'จ.-ส.', 'ทุกวันทำการ')


# =====================================================================================
#  SECTION 2 — PURE HELPERS (testable, ไม่แตะ Streamlit)
# =====================================================================================
def parse_days_from_string(val_str) -> Tuple[List[int], str]:
    """แปลงข้อความวันจัดส่ง -> (list ของ index วัน 0-5, สถานะ)

    สถานะ: 'ok' | 'empty' | 'unparsed'
    แก้บั๊ก v1:
      - regex เดิมมี |1) |2) ทำให้ "สัปดาห์ 12" ถูกตีเป็น จันทร์+อังคาร
      - typo ',ศ

---

## 📋 ตารางสรุปการแก้ไขทั้งหมด

| ประเด็นเดิม | สถานะ | วิธีแก้ใน v2 |
|---|---|---|
| `guess_col` คืน `cols[0]` | ✅ | เพิ่มพารามิเตอร์ `allow_none=True` |
| regex วันจัดส่ง (ตัวเลขลอย + typo `,ศ$`) | ✅ | เปลี่ยนเป็น token-based + คืนสถานะ `unparsed` มาเตือน |
| Google API เกิน 100 elements | ✅ | `chunk = 100 // n_dest` แบบไดนามิก + ประเมินค่าใช้จ่าย |
| OSRM เกิน limit พิกัด | ✅ | แบ่ง batch ให้ `batch + n_dest ≤ 95` + `sleep(0.35)` |
| ระยะทางเป็นองศา² | ✅ | `project_xy()` → เมตรทั้งระบบ ตรงหน่วยกับ road distance |
| slider ไม่ reset เมื่อเปลี่ยนชีต | ✅ | fingerprint ครอบคลุม url/gid/คอลัมน์/donor/รถใหม่ + ล้าง widget key |
| O(n²) จำกัด 4,000 จุด | ✅ | `cKDTree` + fallback แบบแบ่งก้อน ลบข้อจำกัด `max_n` |
| tolerance เป็นค่าสัมบูรณ์ | ✅ | เลือกโหมด `target` / `capacity` ได้ |
| `พฤหัสฯ` vs `พฤหัสบดี` | ✅ | `DAY_NAMES` ชุดเดียวใช้ร่วมทั้งไฟล์ |
| แผนที่ After โชว์วันเดิม | ✅ | เปลี่ยนไปอ่าน `วันจัดส่ง(ใหม่)` |
| `สถานะการย้ายวัน` ถูกเขียนทับ | ✅ | สะสมเป็น `จ→พ, ศ→อ` |
| เบอร์รถขยะ (`nan`, `-`) | ✅ | `clean_truck_ids()` + กรองตอนโหลด |
| ไม่มี KPI วัดผล | ✅ | 4 metric cards + compactness + std |
| ไม่คิดจำนวนจุดจอด/วัน | ✅ | `max_stops_per_day` เข้าไปในการเกลี่ยวัน |
| ติด local optimum | ✅ | เพิ่ม `swap_improve()` (2-opt exchange) |
| engine ผูก global | ✅ | `ZoningConfig` / `ZoningResult` dataclass |
| ไม่มี scenario save | ✅ | export/import JSON |
| แผนที่หน่วงตอนหมุดเยอะ | ✅ | `prefer_canvas` + `MarkerCluster` เมื่อ >1,500 |

---

## 🎯 ฟีเจอร์ใหม่ที่ตอบโจทย์ "หลายคันเกินพร้อมกัน" โดยตรง

1. **ตารางวินิจฉัยฝูงรถ** — เปิดแอปปุ๊บเห็นทันทีว่าคันไหนเกินเพดาน เกินกี่ถัง/วัน และต้องเพิ่มรถกี่คัน
2. **แยกโหมด Donor 2 แบบ** — "ยุบทั้งคัน" กับ "ดึงงานออกบางส่วน" ซึ่งแบบหลังจะ**คลาย Core Lock ให้พอดีกับเป้าใหม่อัตโนมัติ** (`ratio_override`) แก้ปัญหาที่แกนกลางล็อกไว้เยอะจนเกินเป้าตั้งแต่ยังไม่เริ่มจัด
3. **รถใหม่หลายคัน** — seed แยกกันด้วย k-means++ ถ่วงน้ำหนักยอด บนพื้นที่รอบนอกที่ว่างจริง
4. **คำนวณเป้าหมายอัตโนมัติ** — กดปุ่มเดียว ระบบกดทุกคันลงมาที่เพดาน แล้วเกลี่ยส่วนเกินลงรถใหม่ให้เอง

---

ลองรันกับข้อมูลจริงของสาขาที่หนักที่สุดก่อนได้เลยครับ — อยากให้ผมช่วยเพิ่ม **ชุดเทส pytest** สำหรับ engine (เช่น เคส "ยอดรวมพอดีความจุต้องไม่มี Overflow", "รถที่ล็อก % ต้องไม่ถูกเปลี่ยน") หรืออยากให้ทำ **โหมดเปรียบเทียบหลายสถานการณ์พร้อมกัน** (เช่น เพิ่มรถ 1 คัน vs 2 คัน แล้วเทียบ KPI ข้างกัน) เพื่อใช้เสนอผู้บริหารดีครับ? ในเงื่อนไขวันเสาร์
      - parse ไม่ได้แล้วคืน 'ทุกวัน' เงียบๆ ทำให้โหลดรายวันสูงเกินจริง
    """
    raw = str(val_str) if val_str is not None else ''
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
        if tok.isdigit():                       # ยอมรับเลขเฉพาะ token ที่เป็นเลขล้วน
            n = int(tok)
            if 1 <= n <= WORKING_DAYS:
                days.add(n - 1)
            continue
        for name, d in DAY_TOKENS:              # จับตัวที่ยาวสุดตัวเดียวพอ
            if name in tok:
                days.add(d)
                break
    if not days:
        return [], 'unparsed'
    return sorted(days), 'ok'


def format_days_to_string(days_list: Sequence[int]) -> str:
    if not days_list:
        return 'ไม่ระบุ'
    d = sorted(set(int(x) for x in days_list))
    if len(d) == WORKING_DAYS:
        return 'จ-ส'
    return ', '.join(DAY_NAMES[x] for x in d)


def format_days_short(days_list: Sequence[int]) -> str:
    if not days_list:
        return '-'
    d = sorted(set(int(x) for x in days_list))
    if len(d) == WORKING_DAYS:
        return 'จ-ส'
    return ''.join(DAY_SHORT[x] for x in d)


def project_xy(lat, lon, lat0: Optional[float] = None) -> Tuple[np.ndarray, np.ndarray, float]:
    """แปลง lat/lon -> ระนาบ x,y หน่วยเมตร (equirectangular ที่ lat อ้างอิง)

    แก้บั๊ก v1: การใช้ (dlat² + dlon²) ตรงๆ ทำให้ระยะแนวตะวันออก-ตกผิดสัดส่วน
    และทำให้ผสมกับ road distance (เมตร) ไม่ได้เพราะคนละหน่วย
    """
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    if lat0 is None:
        lat0 = float(np.nanmean(lat))
    k = math.cos(math.radians(lat0))
    x = np.radians(lon) * EARTH_RADIUS_M * k
    y = np.radians(lat) * EARTH_RADIUS_M
    return x, y, lat0


def knn_indices(xy: np.ndarray, k: int) -> np.ndarray:
    """หา index ของเพื่อนบ้านใกล้สุด k ตัว (ไม่รวมตัวเอง)

    แก้บั๊ก v1: เดิมสร้าง distance matrix เต็ม O(n²) — ที่ 4,000 จุดกิน ~380MB
    จนต้องตั้ง max_n ข้ามไป ตอนนี้ใช้ KDTree -> O(n log n), memory O(n·k)
    """
    n = len(xy)
    k = int(min(k, max(0, n - 1)))
    if k <= 0:
        return np.zeros((n, 0), dtype=int)
    if HAS_SCIPY:
        tree = cKDTree(xy)
        _, idx = tree.query(xy, k=k + 1, workers=-1)
        idx = np.atleast_2d(idx)
        return idx[:, 1:]
    out = np.zeros((n, k), dtype=int)           # fallback: brute force แบบแบ่งก้อน
    CH = 512
    for s in range(0, n, CH):
        e = min(n, s + CH)
        d = ((xy[s:e, None, :] - xy[None, :, :]) ** 2).sum(axis=2)
        for i in range(e - s):
            d[i, s + i] = np.inf
        out[s:e] = np.argpartition(d, k, axis=1)[:, :k]
    return out


def kmeans_seeds(xy: np.ndarray, weights: np.ndarray, k: int,
                 iters: int = 20, seed: int = 42) -> np.ndarray:
    """k-means++ แบบถ่วงน้ำหนักด้วยยอด — ใช้หา seed ของ 'รถใหม่หลายคัน' ให้กระจายกัน

    แก้บั๊ก v1: seed รถใหม่ = ค่าเฉลี่ยของ seed ทุกคัน -> ตกกลางแผนที่ แย่งพื้นที่รถเดิม
    และถ้ามีรถใหม่ >1 คันจะได้ seed ซ้ำที่เดิมทั้งหมด
    """
    n = len(xy)
    k = max(1, min(k, n))
    rng = np.random.default_rng(seed)
    w = np.asarray(weights, dtype=float)
    w = np.where(w > 0, w, 1e-9)

    centers = [xy[rng.choice(n, p=w / w.sum())]]
    for _ in range(k - 1):
        d2 = np.min(((xy[:, None, :] - np.array(centers)[None, :, :]) ** 2).sum(2), axis=1)
        p = d2 * w
        p = p / p.sum() if p.sum() > 0 else np.full(n, 1.0 / n)
        centers.append(xy[rng.choice(n, p=p)])
    C = np.array(centers, dtype=float)

    for _ in range(iters):
        d2 = ((xy[:, None, :] - C[None, :, :]) ** 2).sum(2)
        lab = d2.argmin(axis=1)
        newC = C.copy()
        for j in range(k):
            m = lab == j
            if m.any():
                ww = w[m]
                newC[j] = np.average(xy[m], axis=0, weights=ww)
        if np.allclose(newC, C, atol=1e-3):
            C = newC
            break
        C = newC
    return C


def clean_truck_ids(values: Sequence) -> List[str]:
    """กรอง 'รถผี' (ค่าว่าง/nan/-) ออกจากรายการเบอร์รถ"""
    out = []
    for v in values:
        s = str(v).strip()
        if s.lower() in NO_TRUCK_TOKENS:
            continue
        out.append(s)
    return sorted(set(out))


def guess_col(substrings: Sequence[str], cols: Sequence[str],
              fallback: Optional[str] = None, allow_none: bool = False) -> Optional[str]:
    """เดาคอลัมน์จากคำในชื่อ

    แก้บั๊ก v1 (ร้ายแรงที่สุด): เดิม `return fallback if fallback is not None else cols[0]`
    ทำให้เรียกด้วย fallback=None แล้วได้ cols[0] เสมอ -> คอลัมน์ VIP/ชื่อ ถูกเดาเป็น
    คอลัมน์แรกของชีตโดยอัตโนมัติ (มัก = 'ลำดับ') ผู้ใช้เข้าใจว่าล็อก VIP แล้วแต่จริงๆ ไม่ล็อก
    """
    for c in cols:
        if any(s.lower() in str(c).lower() for s in substrings):
            return c
    if allow_none:
        return None
    return fallback if fallback is not None else (cols[0] if len(cols) else None)


# =====================================================================================
#  SECTION 3 — CONFIG / RESULT DATACLASS
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
    tol_mode: str = 'target'           # 'target' = % ของเป้าคันนั้น | 'capacity' = % ของความจุเต็ม
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


# =====================================================================================
#  SECTION 4 — ROAD DISTANCE PROVIDERS (แก้ปัญหา API limit)
# =====================================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_osrm_matrix(source_coords: tuple, dest_coords: tuple,
                      base_url: str, max_coords: int = 95) -> Tuple[Optional[np.ndarray], str]:
    """OSRM /table — แบ่งก้อน source ให้ (batch + n_dest) ไม่เกิน limit ของ server

    แก้บั๊ก v1: เดิมยัด source+dest ทั้งหมดใน request เดียว — public demo server
    จำกัดราว 100 พิกัด ข้อมูลจริง 300-800 จุดจึงพังทุกครั้งแล้ว fallback เงียบๆ
    """
    import requests
    dest = list(dest_coords)
    src = list(source_coords)
    n_dst = len(dest)
    if n_dst == 0 or not src:
        return None, 'ไม่มีปลายทาง'
    batch = max(1, max_coords - n_dst)
    out = np.full((len(src), n_dst), np.nan, dtype=float)

    for start in range(0, len(src), batch):
        chunk = src[start:start + batch]
        all_c = chunk + dest
        coord_str = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in all_c)
        url = f"{base_url.rstrip('/')}/table/v1/driving/{coord_str}"
        params = {
            "sources": ";".join(str(i) for i in range(len(chunk))),
            "destinations": ";".join(str(i) for i in range(len(chunk), len(all_c))),
            "annotations": "distance",
        }
        try:
            r = requests.get(url, params=params, timeout=40)
            r.raise_for_status()
            data = r.json()
            if data.get("code") != "Ok":
                return None, f"OSRM ตอบกลับ code={data.get('code')}"
            out[start:start + len(chunk), :] = np.array(data["distances"], dtype=float)
        except Exception as e:
            return None, f"OSRM error: {e}"
        time.sleep(0.35)                        # กัน rate-limit ของ demo server
    return out, ''


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_google_matrix(source_coords: tuple, dest_coords: tuple,
                        api_key: str) -> Tuple[Optional[np.ndarray], str]:
    """Google Distance Matrix — คุม elements/request ไม่เกิน 100

    แก้บั๊ก v1: เดิม CHUNK=25 คงที่ + ส่ง dest ทั้งหมด -> รถ 5 คันขึ้นไป = 125 elements
    เกิน limit ทันที ได้ MAX_ELEMENTS_EXCEEDED แล้ว fallback เส้นตรงเงียบๆ
    (ผู้ใช้จ่ายค่า API แต่ไม่ได้ผลลัพธ์)
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
        origin_str = "|".join(f"{lat:.6f},{lon:.6f}" for lat, lon in part)
        try:
            r = requests.get(
                "https://maps.googleapis.com/maps/api/distancematrix/json",
                params={"origins": origin_str, "destinations": dest_str,
                        "key": api_key, "mode": "driving"}, timeout=40)
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
#  SECTION 5 — CAPACITY PLANNING (Multi-Donor)
# =====================================================================================
def compute_default_targets(vol_by_truck: Dict[str, float],
                            dissolve: Sequence[str],
                            keep: Sequence[str],
                            new_trucks: Sequence[str],
                            cap_units: float) -> Tuple[Dict[str, float], float]:
    """คำนวณเป้าหมายเริ่มต้นแบบ 'ตัดยอดส่วนเกินออกจากคันที่เกินเพดาน แล้วเกลี่ยลงคันใหม่'

    นี่คือหัวใจของโจทย์จริง: รถที่ยอด/วันเกินเพดานควบคุมจะถูกกดลงมาที่เพดานพอดี
    ส่วนเกิน + ยอดของรถที่ยุบทั้งคัน = pool ที่ต้องหาบ้านใหม่
    คืนค่า: (targets, leftover) โดย leftover > 0 แปลว่า 'รถไม่พอ ต้องเพิ่มอีก'
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

    for t in new_trucks:                        # เติมรถใหม่ก่อน (เต็มคันต่อคัน)
        if pool <= 1e-6:
            break
        take = min(cap_units, pool)
        tgt[t] += take
        pool -= take

    for _ in range(60):                         # ที่เหลือเกลี่ยตาม headroom
        if pool <= 1e-6:
            break
        head = {t: cap_units - tgt[t] for t in tgt if cap_units - tgt[t] > 1e-6}
        if not head:
            break
        total_head = sum(head.values())
        share = min(1.0, pool / total_head)
        for t, h in head.items():
            add = h * share
            tgt[t] += add
            pool -= add
    return tgt, max(0.0, pool)


def diagnose_fleet(df: pd.DataFrame, cfg: ZoningConfig) -> pd.DataFrame:
    """ตารางวินิจฉัยสถานะรถปัจจุบัน: ยอด/เดือน, โหลดสูงสุด/วัน, จุดจอด/วัน, เกินเพดานไหม"""
    rows = []
    for t, g in df.groupby(cfg.truck_col):
        t = str(t).strip()
        if t.lower() in NO_TRUCK_TOKENS:
            continue
        daily = np.zeros(WORKING_DAYS)
        stops = np.zeros(WORKING_DAYS)
        for _, r in g.iterrows():
            days, _ = parse_days_from_string(r[cfg.day_col])
            if not days:
                days = list(range(WORKING_DAYS))
            per = float(r[cfg.vol_col]) / len(days) / WEEKS_PER_MONTH
            for d in days:
                daily[d] += per
                stops[d] += 1
        peak = float(daily.max())
        rows.append({
            'เบอร์รถ': t,
            'จำนวนลูกค้า': int(len(g)),
            'ยอด/เดือน': int(g[cfg.vol_col].sum()),
            'ภาระงาน(%)': round(g[cfg.vol_col].sum() / cfg.monthly_capacity * 100, 1),
            'โหลดสูงสุด/วัน': int(round(peak)),
            'จุดจอดสูงสุด/วัน': int(stops.max()),
            'ส่วนเกิน/วัน': int(round(max(0.0, peak - cfg.daily_control_cap))),
            'สถานะ': ('🔴 เกินเพดาน' if peak > cfg.daily_control_cap
                      else ('🟢 เหมาะสม' if peak >= OPTIMAL_MIN
                            else ('🟡 ควรเลี่ยง' if peak >= AVOID_MIN else '⚪ เบาเกิน'))),
        })
    out = pd.DataFrame(rows)
    return out.sort_values('โหลดสูงสุด/วัน', ascending=False).reset_index(drop=True) \
        if not out.empty else out


# =====================================================================================
#  SECTION 6 — ZONING ENGINE (pure)
# =====================================================================================
def _tolerance_for(t: str, targets: Dict[str, float], cfg: ZoningConfig) -> float:
    """ค่าเผื่อรายคัน

    แก้บั๊ก v1: เดิมใช้ % ของความจุเต็มเสมอ -> รถที่ตั้งเป้า 30% ได้ค่าเผื่อกว้างถึง ±16.7%
    ของเป้าตัวเอง ทำให้รับงานเกินได้เยอะโดยระบบยังบอกว่า 'อยู่ในค่าเผื่อ'
    """
    if cfg.tol_mode == 'target':
        return max(40.0, (cfg.tol_pct / 100.0) * targets.get(t, 0.0))
    return (cfg.tol_pct / 100.0) * cfg.monthly_capacity


def build_stops(df: pd.DataFrame, cfg: ZoningConfig) -> pd.DataFrame:
    """ยุบลูกค้าที่พิกัดเดียวกันเป็น 'จุดจอด' (ก้อนที่แบ่งแยกไม่ได้)"""
    stops = df.groupby('coord_key').agg(
        lat=(cfg.lat_col, 'first'),
        lon=(cfg.lon_col, 'first'),
        x=('x', 'first'),
        y=('y', 'first'),
        total_vol=(cfg.vol_col, 'sum'),
        n_cust=(cfg.id_col, 'count'),
        orig_truck=(cfg.truck_col, 'first'),
        has_vip_lock=('is_vip_locked', 'any'),
    ).reset_index()
    return stops


def compute_core_keys(stops: pd.DataFrame, ratio: float,
                      eligible_trucks: Sequence[str],
                      ratio_override: Optional[Dict[str, float]] = None) -> set:
    """ล็อกลูกค้าแกนกลาง (เกาะกลุ่มใกล้ centroid ของรถเดิม) ตามสัดส่วนยอด"""
    keys: set = set()
    if ratio <= 0:
        return keys
    ratio_override = ratio_override or {}
    for t in eligible_trucks:
        r = min(ratio, ratio_override.get(t, 100.0))
        if r <= 0:
            continue
        g = stops[stops['orig_truck'] == t]
        if g.empty:
            continue
        cx, cy = g['x'].mean(), g['y'].mean()
        d = (g['x'] - cx) ** 2 + (g['y'] - cy) ** 2
        g = g.assign(_d=d).sort_values('_d')
        cum = g['total_vol'].cumsum()
        total = max(1e-6, float(g['total_vol'].sum()))
        mask = (cum / total) <= (r / 100.0)
        if not mask.any() and len(g):
            mask.iloc[0] = True
        keys.update(g.loc[mask, 'coord_key'].tolist())
    return keys


def _assign_capacitated(stops: pd.DataFrame, trucks: List[str],
                        targets: Dict[str, float], tol: Dict[str, float],
                        seeds: Dict[str, Tuple[float, float]],
                        road: Optional[np.ndarray],
                        max_rounds: int = 80) -> Tuple[np.ndarray, Dict[str, float]]:
    """Capacitated Voronoi แบบ vectorized + global greedy (คู่ใกล้สุดก่อน)

    ปรับจาก v1: เดิมวนลูป python n×T ทุกรอบ ตอนนี้คำนวณเป็น matrix เดียว
    และระยะทางเป็น 'เมตร' ทั้งโหมดเส้นตรงและ road (หน่วยเดียวกัน)
    """
    n = len(stops)
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
        if not elig:
            break
        cand = np.where(assigned < 0)[0]
        if cand.size == 0:
            break

        cols = [tidx[t] for t in elig]
        if road is not None:
            D = road[np.ix_(cand, cols)].astype(float)
            D = np.where(np.isnan(D), np.inf, D)
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
        feasible = (cur[None, :] + vol[cand][:, None]) <= cap[None, :]
        D = np.where(feasible, D, np.inf)

        best_j = D.argmin(axis=1)
        best_d = D[np.arange(len(cand)), best_j]
        ok = np.isfinite(best_d)
        if not ok.any():
            break

        order = np.argsort(best_d[ok])
        cand_ok, j_ok = cand[ok], best_j[ok]
        placed = False
        for p in order:
            i = cand_ok[p]
            t = elig[j_ok[p]]
            if assigned[i] >= 0:
                continue
            if loads[t] + vol[i] > targets.get(t, 0.0) + tol.get(t, 0.0):
                continue
            assigned[i] = tidx[t]
            loads[t] += vol[i]
            placed = True
        if not placed:
            break

    # best-fit ผ่อนปรน ก่อนยอมให้ตกเป็น Overflow
    for i in np.where(assigned < 0)[0]:
        pool = [t for t in trucks if targets.get(t, 0.0) > 0]
        if not pool:
            continue
        t = max(pool, key=lambda z: targets[z] - loads[z])
        if targets[t] - loads[t] > -0.15 * max(1.0, targets[t]):
            assigned[i] = tidx[t]
            loads[t] += vol[i]
    return assigned, loads


def cleanup_stray_points(stops: pd.DataFrame, trucks: List[str],
                         targets: Dict[str, float], loads: Dict[str, float],
                         tol: Dict[str, float], mult: float,
                         rounds: int = 3) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """ย้าย 'เกาะเดี่ยว' ที่หลุดไกลจากกลุ่มก้อนตัวเอง ไปอยู่กับคันที่ใกล้กว่าจริง"""
    stops = stops.copy()
    for _ in range(rounds):
        changed = False
        cent = {}
        for t in trucks:
            g = stops[stops['assigned_truck'] == t]
            if not g.empty:
                cent[t] = (g['x'].mean(), g['y'].mean())
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
                    if ot == t:
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


def majority_vote_smoothing(stops: pd.DataFrame, trucks: List[str],
                            targets: Dict[str, float], loads: Dict[str, float],
                            tol: Dict[str, float], cfg: ZoningConfig
                            ) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """ขัดผิวรอยต่อโซน (แก้ checkerboard) ด้วย k-NN majority filter — ตอนนี้ใช้ KDTree"""
    stops = stops.reset_index(drop=True)
    n = len(stops)
    if n < cfg.knn_k + 2:
        return stops, loads

    xy = stops[['x', 'y']].to_numpy(dtype=float)
    nb = knn_indices(xy, cfg.knn_k)
    locked = stops['is_locked'].to_numpy()
    vol = stops['total_vol'].to_numpy(dtype=float)

    for _ in range(cfg.knn_rounds):
        changed = False
        assigned = stops['assigned_truck'].to_numpy(dtype=object).copy()
        for i in range(n):
            if locked[i]:
                continue                        # VIP/Core lock สำคัญกว่าความสวยของโซน
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


def swap_improve(stops: pd.DataFrame, trucks: List[str],
                 targets: Dict[str, float], loads: Dict[str, float],
                 tol: Dict[str, float], rounds: int = 3,
                 max_pairs_per_combo: int = 60) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """Local search แบบสลับคู่ข้ามคัน (2-opt exchange)

    ของใหม่ใน v2: แก้เคสที่ 2 คันต่างมีจุดที่ 'ควรอยู่กับอีกคัน' พร้อมกัน
    ซึ่ง cleanup ย้ายเดี่ยวไม่ได้เพราะติดเพดานความจุ — ต้องสลับพร้อมกันถึงจะผ่าน
    """
    stops = stops.copy()
    for _ in range(rounds):
        changed = False
        cent = {}
        for t in trucks:
            g = stops[stops['assigned_truck'] == t]
            if not g.empty:
                cent[t] = np.array([g['x'].mean(), g['y'].mean()])
        for a, b in combinations([t for t in trucks if t in cent], 2):
            ca, cb = cent[a], cent[b]
            A = stops[(stops['assigned_truck'] == a) & (~stops['is_locked'])]
            B = stops[(stops['assigned_truck'] == b) & (~stops['is_locked'])]
            if A.empty or B.empty:
                continue
            gainA = (np.sqrt(((A[['x', 'y']].to_numpy() - ca) ** 2).sum(1)) -
                     np.sqrt(((A[['x', 'y']].to_numpy() - cb) ** 2).sum(1)))
            gainB = (np.sqrt(((B[['x', 'y']].to_numpy() - cb) ** 2).sum(1)) -
                     np.sqrt(((B[['x', 'y']].to_numpy() - ca) ** 2).sum(1)))
            ia = A.index[np.argsort(-gainA)][:max_pairs_per_combo]
            ib = B.index[np.argsort(-gainB)][:max_pairs_per_combo]
            ga = dict(zip(A.index, gainA))
            gb = dict(zip(B.index, gainB))
            used_b: set = set()
            for i in ia:
                if ga[i] <= 0:
                    break
                for j in ib:
                    if j in used_b or gb[j] <= 0:
                        continue
                    if ga[i] + gb[j] <= 0:
                        continue
                    va = stops.at[i, 'total_vol']
                    vb = stops.at[j, 'total_vol']
                    la = loads[a] - va + vb
                    lb = loads[b] - vb + va
                    if la > targets.get(a, 0.0) + tol.get(a, 0.0):
                        continue
                    if lb > targets.get(b, 0.0) + tol.get(b, 0.0):
                        continue
                    stops.at[i, 'assigned_truck'] = b
                    stops.at[j, 'assigned_truck'] = a
                    loads[a], loads[b] = la, lb
                    used_b.add(j)
                    changed = True
                    break
        if not changed:
            break
    return stops, loads


def smooth_daily_loads(opt: pd.DataFrame, cfg: ZoningConfig, trucks: List[str]
                       ) -> Tuple[pd.DataFrame, np.ndarray, np.ndarray, Dict[str, np.ndarray]]:
    """PRIORITY 3 — เกลี่ยวันจัดส่งภายในคันเดียวกัน (คุมทั้งปริมาตรและจำนวนจุดจอด)"""
    idx_list = opt.index.tolist()
    pos = {ix: p for p, ix in enumerate(idx_list)}
    vols = opt[cfg.vol_col].to_numpy(dtype=float)

    day_map: Dict[int, List[int]] = {}
    for ix in idx_list:
        d, status = parse_days_from_string(opt.at[ix, cfg.day_col])
        if not d:
            d = list(range(WORKING_DAYS))
        day_map[ix] = d
        opt.at[ix, '_day_status'] = status

    def recompute():
        vol_d = {t: np.zeros(WORKING_DAYS) for t in trucks}
        cnt_d = {t: np.zeros(WORKING_DAYS) for t in trucks}
        for ix in idx_list:
            t = opt.at[ix, 'เบอร์รถใหม่']
            if t not in vol_d:
                continue
            dl = day_map[ix]
            per = vols[pos[ix]] / max(1, len(dl)) / WEEKS_PER_MONTH
            for d in dl:
                vol_d[t][d] += per
                cnt_d[t][d] += 1
        return vol_d, cnt_d

    cap = cfg.daily_control_cap
    for _ in range(cfg.daily_passes):
        vol_d, cnt_d = recompute()
        changed = False
        for t in trucks:
            order = np.argsort(-vol_d[t])
            for d in order:
                over_vol = vol_d[t][d] > cap
                over_cnt = cnt_d[t][d] > cfg.max_stops_per_day
                if not (over_vol or over_cnt):
                    continue
                score = vol_d[t] / max(1.0, cap) + cnt_d[t] / max(1, cfg.max_stops_per_day)
                target_d = int(np.argmin(score))
                if target_d == d:
                    continue
                if vol_d[t][target_d] >= cap - 5 and cnt_d[t][target_d] >= cfg.max_stops_per_day - 2:
                    continue

                movable = [ix for ix in idx_list
                           if opt.at[ix, 'เบอร์รถใหม่'] == t
                           and (cfg.allow_vip_day_move or not opt.at[ix, 'is_vip_locked'])
                           and d in day_map[ix] and len(day_map[ix]) <= 3
                           and target_d not in day_map[ix]]
                if not movable:
                    continue
                movable.sort(key=lambda ix: -vols[pos[ix]] / max(1, len(day_map[ix])))

                excess = max(0.0, vol_d[t][d] - TARGET_DAY_CAP)
                shifted = 0.0
                for ix in movable:
                    if shifted >= excess and not over_cnt:
                        break
                    dl = day_map[ix]
                    v = vols[pos[ix]] / max(1, len(dl)) / WEEKS_PER_MONTH
                    if vol_d[t][target_d] + v > cap:
                        continue
                    if cnt_d[t][target_d] + 1 > cfg.max_stops_per_day:
                        break
                    day_map[ix] = [target_d if z == d else z for z in dl]
                    note = f"{DAY_SHORT[d]}→{DAY_SHORT[target_d]}"
                    prev = str(opt.at[ix, 'สถานะการย้ายวัน'])
                    # แก้บั๊ก v1: เดิมเขียนทับ ทำให้เห็นแค่การย้ายครั้งสุดท้าย
                    opt.at[ix, 'สถานะการย้ายวัน'] = note if prev in ('-', 'nan') else f"{prev}, {note}"
                    vol_d[t][d] -= v
                    vol_d[t][target_d] += v
                    cnt_d[t][d] -= 1
                    cnt_d[t][target_d] += 1
                    shifted += v
                    changed = True
                    over_cnt = cnt_d[t][d] > cfg.max_stops_per_day
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
    """ระยะเฉลี่ยจากจุดจอดถึงศูนย์กลางโซนตัวเอง (เมตร) — ยิ่งต่ำยิ่งเกาะกลุ่ม"""
    if g.empty:
        return 0.0
    cx, cy = g['x'].mean(), g['y'].mean()
    return float(np.sqrt((g['x'] - cx) ** 2 + (g['y'] - cy) ** 2).mean())


# ---------------------------------------------------------------------------------
#  MAIN ENGINE
# ---------------------------------------------------------------------------------
def run_multi_donor_zoning(df: pd.DataFrame, cfg: ZoningConfig,
                           target_pcts: Dict[str, float],
                           dissolve_trucks: Sequence[str],
                           relieve_trucks: Sequence[str],
                           new_trucks: Sequence[str],
                           manual_locks: Sequence[str],
                           road_matrix_getter=None) -> ZoningResult:
    warns: List[str] = []
    infos: List[str] = []
    opt = df.copy()

    all_orig = clean_truck_ids(opt[cfg.truck_col].unique())
    dissolve = [t for t in dissolve_trucks if t in all_orig]
    kept = [t for t in all_orig if t not in dissolve]
    active = kept + [t for t in new_trucks if t not in kept]

    targets = {t: cfg.monthly_capacity * (float(target_pcts.get(t, 0.0)) / 100.0) for t in active}
    tol = {t: _tolerance_for(t, targets, cfg) for t in active}

    # ---- เตรียมข้อมูลระดับลูกค้า ----
    locked_ids = {str(x).strip() for x in manual_locks}
    opt['is_vip_locked'] = (
        opt['VIP_Status'].astype(str).str.upper().str.strip().eq('VIP') |
        opt[cfg.id_col].astype(str).str.strip().isin(locked_ids)
    )
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
                         f"— จุดนี้จะตกเป็น '{OVERFLOW_LABEL}' เสมอ ควรตรวจสอบพิกัด GPS")

    # ---- Core ratio รายคัน: รถที่ถูกดึงงานออก ต้องคลายล็อกให้พอดีกับเป้าใหม่ ----
    vol_by_truck = stops.groupby('orig_truck')['total_vol'].sum().to_dict()
    ratio_override: Dict[str, float] = {}
    for t in relieve_trucks:
        cur = float(vol_by_truck.get(t, 0.0))
        if cur > 0 and t in targets:
            ratio_override[t] = max(0.0, targets[t] / cur * 100.0 * 0.92)
    core_eligible = [t for t in kept if t not in dissolve]

    # ---- Seeds ----
    seeds: Dict[str, Tuple[float, float]] = {}
    for t in kept:
        g = stops[stops['orig_truck'] == t]
        if not g.empty:
            seeds[t] = (float(g['x'].mean()), float(g['y'].mean()))
    bx, by = float(stops['x'].mean()), float(stops['y'].mean())

    if new_trucks:
        ck = compute_core_keys(stops, cfg.core_ratio, core_eligible, ratio_override)
        pool = stops[~stops['coord_key'].isin(ck)]
        if pool.empty:
            pool = stops
        C = kmeans_seeds(pool[['x', 'y']].to_numpy(dtype=float),
                         pool['total_vol'].to_numpy(dtype=float), len(new_trucks))
        for i, t in enumerate(new_trucks):
            seeds[t] = (float(C[i][0]), float(C[i][1]))

    # ---- Road distance matrix (เรียกครั้งเดียว) ----
    road = None
    if cfg.use_road and road_matrix_getter is not None and active and not stops.empty:
        dest_ll = []
        for t in active:
            sx, sy = seeds.get(t, (bx, by))
            lat0 = float(opt[cfg.lat_col].mean())
            k = math.cos(math.radians(lat0))
            dest_ll.append((math.degrees(sy / EARTH_RADIUS_M),
                            math.degrees(sx / (EARTH_RADIUS_M * k))))
        src_ll = list(zip(stops['lat'].tolist(), stops['lon'].tolist()))
        road, err = road_matrix_getter(tuple(src_ll), tuple(dest_ll))
        if road is None:
            warns.append(f"เรียก API ระยะทางถนนจริงไม่สำเร็จ ({err}) — รอบนี้ใช้ระยะทางเส้นตรงแทน")

    # ---- Zoning pass + auto core-ratio decay ----
    def one_pass(ratio: float):
        s = stops.copy()
        ck = compute_core_keys(s, ratio, core_eligible, ratio_override)
        s['is_core_locked'] = s['coord_key'].isin(ck)
        s['is_locked'] = s['has_vip_lock'] | s['is_core_locked']
        s['assigned_truck'] = None

        for i, r in s.iterrows():               # pin เฉพาะที่ล็อกและรถเดิมยังอยู่
            if r['is_locked'] and r['orig_truck'] in active:
                s.at[i, 'assigned_truck'] = r['orig_truck']

        a, ld = _assign_capacitated(s, active, targets, tol, seeds, road)
        s['assigned_truck'] = [active[k] if k >= 0 else OVERFLOW_LABEL for k in a]
        # จุดที่ล็อกแต่รถเดิมถูกยุบ ให้ปลดล็อกเพื่อให้ขั้นขัดผิวจัดต่อได้
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

    # ---- ขัดผิวโซน 3 ชั้น ----
    if cfg.enable_stray_cleanup:
        stops_a, loads = cleanup_stray_points(stops_a, active, targets, loads, tol,
                                              cfg.polish_tol_multiplier)
    if cfg.enable_majority_vote:
        stops_a, loads = majority_vote_smoothing(stops_a, active, targets, loads, tol, cfg)
    if cfg.enable_swap:
        stops_a, loads = swap_improve(stops_a, active, targets, loads, tol, cfg.swap_rounds)

    # ---- แมปกลับสู่ระดับลูกค้า ----
    m_truck = dict(zip(stops_a['coord_key'], stops_a['assigned_truck']))
    m_core = dict(zip(stops_a['coord_key'], stops_a['is_core_locked']))
    opt['เบอร์รถใหม่'] = opt['coord_key'].map(m_truck).fillna(OVERFLOW_LABEL)
    opt['is_core_locked'] = opt['coord_key'].map(m_core).fillna(False)
    opt['is_locked'] = opt['is_vip_locked'] | opt['is_core_locked']

    opt['สถานะ'] = np.where(opt[cfg.truck_col] == opt['เบอร์รถใหม่'],
                            'คงเดิม', 'ย้ายไปสาย ' + opt['เบอร์รถใหม่'].astype(str))
    opt.loc[opt['is_locked'] & (opt[cfg.truck_col] == opt['เบอร์รถใหม่']), 'สถานะ'] = 'คงเดิม 🔒'

    # ---- PRIORITY 3: เกลี่ยวัน ----
    opt, dm, ds, final_daily = smooth_daily_loads(opt, cfg, active)

    # ---- KPI ----
    before = opt.groupby(cfg.truck_col)
    after = opt.groupby('เบอร์รถใหม่')
    comp_before = np.mean([compute_compactness(g) for _, g in before]) if len(before) else 0.0
    comp_after = np.mean([compute_compactness(g) for t, g in after if t != OVERFLOW_LABEL]) \
        if len(after) else 0.0

    peak_before = {}
    for t, g in before:
        d = np.zeros(WORKING_DAYS)
        for _, r in g.iterrows():
            dl, _ = parse_days_from_string(r[cfg.day_col])
            dl = dl or list(range(WORKING_DAYS))
            per = float(r[cfg.vol_col]) / len(dl) / WEEKS_PER_MONTH
            for k in dl:
                d[k] += per
        peak_before[str(t).strip()] = float(d.max())
    peak_after = {t: float(v.max()) for t, v in final_daily.items()}

    moved = int((opt[cfg.truck_col] != opt['เบอร์รถใหม่']).sum())
    metrics = {
        'compact_before_km': comp_before / 1000.0,
        'compact_after_km': comp_after / 1000.0,
        'over_before': sum(1 for v in peak_before.values() if v > cfg.daily_control_cap),
        'over_after': sum(1 for v in peak_after.values() if v > cfg.daily_control_cap),
        'peak_before': max(peak_before.values()) if peak_before else 0.0,
        'peak_after': max(peak_after.values()) if peak_after else 0.0,
        'moved_cust': moved,
        'moved_pct': moved / max(1, len(opt)) * 100.0,
        'moved_vol': float(opt.loc[opt[cfg.truck_col] != opt['เบอร์รถใหม่'], cfg.vol_col].sum()),
        'std_before': float(np.std(list(peak_before.values()))) if peak_before else 0.0,
        'std_after': float(np.std(list(peak_after.values()))) if peak_after else 0.0,
    }

    bad_days = int((opt['_day_status'] != 'ok').sum()) if '_day_status' in opt.columns else 0
    if bad_days:
        warns.append(f"อ่านค่า 'วันจัดส่ง' ไม่ออก {bad_days} รายการ — ระบบถือว่าเป็น 'จ-ส' "
                     f"ซึ่งจะทำให้โหลดรายวันดูสูงเกินจริง กรุณาตรวจสอบข้อมูลต้นทาง")

    return ZoningResult(result_df=opt, stops_df=stops_a, daily_matrix=dm, daily_stops=ds,
                        final_daily=final_daily, targets=targets, loads=loads,
                        core_ratio_used=ratio_used, metrics=metrics,
                        warnings=warns, infos=infos)


# =====================================================================================
#  SECTION 7 — UI THEME
# =====================================================================================
st.markdown('''
<style>
@import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');
html, body, [class*="css"], p, span, label, div, small, li, a, h1,h2,h3,h4,h5,h6 {
    font-family:'Sarabun',sans-serif !important; color:#FFFFFF !important; font-weight:400; }
.stApp { background:linear-gradient(135deg,#000814 0%,#001D3D 45%,#003566 100%) !important;
    background-attachment:fixed; }
h1,h2,h3,h4,h5,h6 { color:#FFD700 !important; font-weight:700 !important; letter-spacing:.5px;
    text-shadow:0 2px 4px rgba(0,0,0,.6); }
[data-testid="stSidebar"] { background:rgba(0,13,26,.55) !important; backdrop-filter:blur(25px);
    border-right:1px solid rgba(255,255,255,.15); }
[data-testid="stSidebar"] * { color:#FFF !important; }
[data-testid="stSidebar"] label, [data-testid="stSidebar"] .stMarkdown p {
    color:#F3E5AB !important; font-weight:600 !important; }
[data-testid="stSidebar"] h1,[data-testid="stSidebar"] h2,[data-testid="stSidebar"] h3 {
    color:#FFD700 !important; border-bottom:1px solid rgba(212,175,55,.3); padding-bottom:8px; }
div[data-baseweb="select"] > div, input, textarea {
    background:rgba(0,30,60,.3) !important; backdrop-filter:blur(12px);
    border:1px solid rgba(255,255,255,.2) !important; color:#FFF !important;
    border-radius:12px !important; font-weight:500; }
div[data-baseweb="select"] * { color:#FFF !important; }
div[data-baseweb="select"] [class*="placeholder"] { color:#CBD5E1 !important; }
div[data-baseweb="tag"] { background:rgba(212,175,55,.28) !important; border:1px solid #D4AF37 !important; }
div[data-baseweb="tag"] * { color:#FFF !important; }
input::placeholder { color:#CBD5E1 !important; opacity:1 !important; }
input:focus, div[data-baseweb="select"] > div:focus-within {
    border-color:#FFD700 !important; box-shadow:0 0 15px rgba(255,215,0,.35) !important; }
div[role="listbox"], ul[role="listbox"], div[data-baseweb="menu"], [data-baseweb="select-dropdown"] {
    background:rgba(248,250,252,.95) !important; border:1px solid #D4AF37 !important;
    border-radius:12px !important; box-shadow:0 12px 32px rgba(0,0,0,.4) !important; }
div[role="option"], ul[role="listbox"] > li { color:#0F172A !important; font-weight:500 !important;
    padding:10px 16px !important; border-bottom:1px solid #E2E8F0 !important; }
div[role="option"] *, ul[role="listbox"] > li * { color:#0F172A !important; }
div[role="option"]:hover { background:#FFF8E1 !important; }
div[role="option"][aria-selected="true"] { background:#FFD700 !important; }
div[role="option"][aria-selected="true"] * { color:#000B18 !important; font-weight:700 !important; }
div[data-testid="stNotification"], div[data-testid="stNotification"] * { color:#0F172A !important; }
.stButton>button { background:linear-gradient(135deg,#D4AF37 0%,#AA8C2C 100%) !important;
    color:#000B18 !important; border:none !important; border-radius:10px; font-weight:700;
    padding:.6rem 1.4rem; width:100%; box-shadow:0 4px 15px rgba(212,175,55,.4); transition:all .3s; }
.stButton>button:hover { background:linear-gradient(135deg,#F3E5AB 0%,#D4AF37 100%) !important;
    box-shadow:0 6px 20px rgba(255,215,0,.6); transform:translateY(-2px); }
.stDataFrame { background:rgba(0,24,48,.25) !important; backdrop-filter:blur(20px); padding:1rem;
    border-radius:16px; border:1px solid rgba(255,255,255,.15); border-top:3px solid #D4AF37; }
.stDataFrame td,.stDataFrame th,.stDataFrame div { color:#0F172A !important; font-weight:500 !important; }
[data-testid="stMetricValue"] { color:#FFD700 !important; font-weight:700 !important; }
[data-testid="stMetricLabel"] * { color:#F1F5F9 !important; }
[data-testid="stDownloadButton"] > button {
    background:linear-gradient(135deg,#28A745 0%,#1E7E34 100%) !important; color:#FFF !important;
    border-radius:10px !important; padding:.8rem 2rem; font-weight:700; }
@keyframes moveRoad { 0%{background-position:0 0} 100%{background-position:-120px 0} }
@keyframes truckV { 0%{transform:translateY(0)} 50%{transform:translateY(-2px)} 100%{transform:translateY(0)} }
.custom-truck-loader { text-align:center; padding:2.2rem; color:#FFD700; font-weight:bold;
    font-size:1.15rem; border-radius:16px; background:rgba(0,24,48,.5); backdrop-filter:blur(20px);
    border:1px solid rgba(255,255,255,.18); margin-bottom:20px; position:relative; overflow:hidden; }
.custom-truck-loader::after { content:""; position:absolute; bottom:10px; left:0; width:100%; height:4px;
    background:repeating-linear-gradient(90deg,#D4AF37,#D4AF37 35px,transparent 35px,transparent 70px);
    animation:moveRoad 1s linear infinite; }
.custom-truck-loader img { width:150px; animation:truckV .35s ease-in-out infinite; margin-bottom:8px; }
.stSpinner > div > div { display:none !important; }
</style>
''', unsafe_allow_html=True)


def reset_results():
    for k in ('result', 'zoning_cfg_used'):
        st.session_state.pop(k, None)


def show_loader(placeholder, msg: str):
    try:
        with open("truck.jpg", "rb") as f:
            b64 = base64.b64encode(f.read()).decode()
        html = (f'<div class="custom-truck-loader">'
                f'<img src="data:image/jpeg;base64,{b64}"><br>{msg}</div>')
    except FileNotFoundError:
        html = f'<div class="custom-truck-loader">{msg}</div>'
    placeholder.markdown(html, unsafe_allow_html=True)


st.title("🚛 Smart Route Rebalancer — Production v2.0")
st.markdown("**ระบบปรับสมดุลสายส่งหลายคันพร้อมกัน (Multi-Donor Fleet Rebalancing)**")
if not HAS_SCIPY:
    st.warning("⚠️ ไม่พบไลบรารี `scipy` — ระบบจะใช้โหมดคำนวณสำรองซึ่งช้ากว่ามากเมื่อข้อมูลเกิน "
               "5,000 จุด แนะนำติดตั้งด้วย `pip install scipy`")

# =====================================================================================
#  SECTION 8 — DATA LOADING
# =====================================================================================
st.sidebar.markdown("### 📁 1. นำเข้าข้อมูล")
sheet_url = st.sidebar.text_input("🔗 ลิงก์ Google Sheets:", placeholder="วางลิงก์ที่นี่...",
                                  on_change=reset_results)
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

# =====================================================================================
#  SECTION 9 — COLUMN MAPPING
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
monthly_cap = st.sidebar.number_input("ความจุอ้างอิง (ถัง/เดือน/คัน) = 100%",
                                      1000.0, 20000.0, DEFAULT_MONTHLY_CAPACITY, 40.0,
                                      on_change=reset_results)
daily_cap = st.sidebar.number_input("เพดานยอดส่งต่อวัน (ถัง/วัน)",
                                    50.0, 400.0, float(DEFAULT_DAILY_CONTROL_CAP), 1.0,
                                    help="รถที่ยอดสูงสุดต่อวันเกินค่านี้ = ต้องถูกดึงงานออก",
                                    on_change=reset_results)
max_stops_day = st.sidebar.number_input("เพดานจุดจอดต่อวัน (จุด)",
                                        10, 400, DEFAULT_MAX_STOPS_PER_DAY, 5,
                                        help="เวลาคนขับถูกจำกัดด้วยจำนวนจุดจอด ไม่ใช่แค่จำนวนถัง",
                                        on_change=reset_results)
cap_units = daily_cap * DAYS_PER_MONTH
st.sidebar.caption(f"เพดาน {daily_cap:,.0f} ถัง/วัน × {DAYS_PER_MONTH:.1f} วันทำงาน "
                   f"≈ **{cap_units:,.0f} ถัง/เดือน** ({cap_units/monthly_cap*100:,.1f}% ของความจุ)")

base_cfg = ZoningConfig(lat_col=lat_col, lon_col=lon_col, vol_col=vol_col, truck_col=truck_col,
                        id_col=id_col, day_col=day_col, name_col=name_col,
                        monthly_capacity=monthly_cap, daily_control_cap=daily_cap,
                        max_stops_per_day=int(max_stops_day))

# =====================================================================================
#  SECTION 11 — FLEET DIAGNOSTIC & DONOR SELECTION
# =====================================================================================
diag = diagnose_fleet(df, base_cfg)
overloaded = diag.loc[diag['สถานะ'] == '🔴 เกินเพดาน', 'เบอร์รถ'].tolist() if not diag.empty else []

st.markdown("## 🩺 ผลวินิจฉัยสถานะรถปัจจุบัน (ก่อนปรับ)")
d1, d2, d3, d4 = st.columns(4)
d1.metric("จำนวนรถทั้งหมด", f"{len(diag)} คัน")
d2.metric("รถที่เกินเพดาน", f"{len(overloaded)} คัน",
          delta=f"เพดาน {daily_cap:,.0f} ถัง/วัน", delta_color="off")
d3.metric("ยอดรวมทั้งสาขา", f"{df[vol_col].sum():,.0f} ถัง/เดือน")
excess_total = float(diag['ส่วนเกิน/วัน'].sum()) * DAYS_PER_MONTH if not diag.empty else 0.0
d4.metric("ยอดส่วนเกินที่ต้องย้าย", f"{excess_total:,.0f} ถัง/เดือน",
          delta=f"≈ {math.ceil(excess_total/max(1.0,cap_units))} คันรถ", delta_color="off")
st.dataframe(diag, use_container_width=True, hide_index=True)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🚚 4. เลือกรถต้นทาง (Donors)")
st.sidebar.caption("รองรับหลายคันพร้อมกัน — ระบบเลือกคันที่เกินเพดานให้อัตโนมัติ")

dissolve_trucks = st.sidebar.multiselect(
    "🗑️ ยุบทั้งคัน (กระจายงานออกทั้งหมด)", options=available_trucks, default=[],
    on_change=reset_results)
relieve_default = [t for t in overloaded if t not in dissolve_trucks]
relieve_trucks = st.sidebar.multiselect(
    "✂️ ดึงงานออกบางส่วน (ลดให้อยู่ในเพดาน)",
    options=[t for t in available_trucks if t not in dissolve_trucks],
    default=relieve_default, on_change=reset_results)

new_trucks_raw = st.sidebar.text_input(
    "➕ เบอร์รถคันใหม่ (คั่นด้วยจุลภาค)", value="", placeholder="เช่น 15112, 15113",
    on_change=reset_results)
new_trucks = [t.strip() for t in new_trucks_raw.split(',') if t.strip()]
new_trucks = [t for t in dict.fromkeys(new_trucks) if t not in available_trucks]

vol_by_truck_all = df.groupby(truck_col)[vol_col].sum().to_dict()
kept_trucks = [t for t in available_trucks if t not in dissolve_trucks]
_, leftover_probe = compute_default_targets(vol_by_truck_all, dissolve_trucks,
                                            kept_trucks, new_trucks, cap_units)
if leftover_probe > 1e-6:
    need = math.ceil(leftover_probe / cap_units)
    st.sidebar.error(f"🚨 ความจุไม่พอ ขาดอีก {leftover_probe:,.0f} ถัง/เดือน "
                     f"— ควรเพิ่มรถใหม่อีกอย่างน้อย **{need} คัน**")
else:
    if new_trucks:
        st.sidebar.success(f"✅ ความจุเพียงพอ (รถใหม่ {len(new_trucks)} คัน)")

active_trucks = kept_trucks + new_trucks
if not active_trucks:
    st.error("❌ ไม่เหลือรถสำหรับจัดสรรงาน กรุณาตรวจสอบการเลือกรถที่ยุบ")
    st.stop()

# =====================================================================================
#  SECTION 12 — TARGET SLIDERS (zero-sum + lock)
# =====================================================================================
st.sidebar.markdown("---")
st.sidebar.markdown("### 🎛️ 5. เป้าหมายรายคัน (%)")

fingerprint = "|".join([sheet_url, sheet_gid, vol_col, truck_col, day_col,
                        str(sorted(dissolve_trucks)), str(sorted(relieve_trucks)),
                        str(new_trucks), f"{monthly_cap}", f"{daily_cap}"])

if st.sidebar.button("🔄 คำนวณเป้าหมายอัตโนมัติจากเพดานควบคุม"):
    st.session_state.pop('slider_fp', None)
    reset_results()

if st.session_state.get('slider_fp') != fingerprint:
    for k in [k for k in list(st.session_state.keys())
              if k.startswith('slider_') or k.startswith('lock_')]:
        del st.session_state[k]                 # กัน state ค้างจากชุดข้อมูลเดิม
    tgt_units, _ = compute_default_targets(vol_by_truck_all, dissolve_trucks,
                                           kept_trucks, new_trucks, cap_units)
    st.session_state.truck_pcts = {
        t: float(round(max(0.0, min(200.0, tgt_units.get(t, 0.0) / monthly_cap * 100)), 1))
        for t in active_trucks}
    for t in active_trucks:
        st.session_state[f"slider_{t}"] = st.session_state.truck_pcts[t]
    st.session_state['slider_fp'] = fingerprint


def on_slider_change(changed: str):
    new_val = max(0.0, min(200.0, st.session_state.get(f"slider_{changed}", 0.0)))
    old = st.session_state.truck_pcts.get(changed, new_val)
    diff = new_val - old
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
    st.session_state.truck_pcts[changed] = round(new_val, 1)
    reset_results()


target_pcts: Dict[str, float] = {}
for t in active_trucks:
    c1, c2 = st.sidebar.columns([3, 1.2])
    with c2:
        st.markdown("<div style='margin-top:32px'></div>", unsafe_allow_html=True)
        st.checkbox("🔒", key=f"lock_{t}", on_change=reset_results)
    with c1:
        tag = "🆕 " if t in new_trucks else ("✂️ " if t in relieve_trucks else "")
        st.session_state.setdefault(f"slider_{t}", st.session_state.truck_pcts.get(t, 0.0))
        v = st.slider(f"{tag}รถ {t} (%)", 0.0, 200.0, step=0.1,
                      key=f"slider_{t}", on_change=on_slider_change, args=(t,))
        target_pcts[t] = max(0.0, min(200.0, v))
        st.session_state.truck_pcts[t] = target_pcts[t]

total_vol = float(df[vol_col].sum())
sys_pct = total_vol / monthly_cap * 100
tot_pct = sum(target_pcts.values())
st.sidebar.info(f"💧 ต้องจัดสรรจริง {sys_pct:,.1f}% | ตั้งเป้าไว้รวม {tot_pct:,.1f}%")
if sys_pct > 0 and abs(tot_pct - sys_pct) / sys_pct > 0.05:
    st.sidebar.warning(f"⚠️ ผลรวมเป้าหมายต่างจากยอดจริงเกิน 5% — เสี่ยงเกิด '{OVERFLOW_LABEL}'")

over_cap_trucks = [t for t in active_trucks
                   if target_pcts[t] * monthly_cap / 100 > cap_units + 1]
if over_cap_trucks:
    st.sidebar.warning(f"⚠️ ตั้งเป้าเกินเพดานควบคุม: {', '.join(over_cap_trucks)}")

# =====================================================================================
#  SECTION 13 — RULES / ADVANCED
# =====================================================================================
st.sidebar.markdown("---")
st.sidebar.markdown("### 🔒 6. ล็อก Key Account")
manual_vips = st.sidebar.multiselect("รหัสสมาชิกที่ห้ามย้ายสาย",
                                     options=df[id_col].unique().tolist(), default=[],
                                     on_change=reset_results)

st.sidebar.markdown("---")
st.sidebar.markdown("### 🎯 7. กฎลำดับความสำคัญ")
st.sidebar.caption("1) VIP Lock → 2) Core Lock → 3) Daily Threshold → 4) Target Matching")
core_ratio_pct = st.sidebar.slider("สัดส่วนแกนกลางที่ล็อก (Core %)", 0, 100, 65, 5,
                                   on_change=reset_results)
tol_mode_label = st.sidebar.radio("ฐานการคิดค่าเผื่อ:",
                                  ["% ของเป้าหมายรถคันนั้น", "% ของความจุเต็ม"], index=0,
                                  on_change=reset_results)
tolerance_pct = st.sidebar.number_input("ค่าเผื่อเป้าหมาย (%)", 0.0, 50.0, 5.0, 0.5,
                                        on_change=reset_results)
allow_vip_day = st.sidebar.checkbox("อนุญาตให้ย้ายวันของลูกค้า VIP", value=False,
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
    road_provider = st.sidebar.radio("ผู้ให้บริการ:", ["osrm", "google"],
                                     format_func=lambda x: "OSRM (ฟรี)" if x == "osrm"
                                     else "Google Distance Matrix",
                                     on_change=reset_results)
    n_stop_est = df.groupby([lat_col, lon_col]).ngroups
    if road_provider == 'osrm':
        osrm_url = st.sidebar.text_input("OSRM Server URL", "https://router.project-osrm.org",
                                         on_change=reset_results)
        st.sidebar.caption(f"⚠️ demo server จำกัดโควตา — ข้อมูลนี้ ~{n_stop_est:,} จุด "
                           f"จะแบ่งเป็นหลาย request แนะนำ self-host หากใช้งานประจำ")
    else:
        gkey = st.sidebar.text_input("Google Maps API Key", "", type="password",
                                     on_change=reset_results)
        el = n_stop_est * len(active_trucks)
        st.sidebar.caption(f"💰 ประมาณ {el:,} elements ≈ ${el/1000*5:,.2f} (เรต $5/1k)")
        if not gkey:
            st.sidebar.warning("⚠️ ยังไม่ใส่ API Key — ระบบจะใช้ระยะทางเส้นตรงแทน")

cfg = ZoningConfig(
    lat_col=lat_col, lon_col=lon_col, vol_col=vol_col, truck_col=truck_col, id_col=id_col,
    day_col=day_col, name_col=name_col, monthly_capacity=monthly_cap,
    daily_control_cap=daily_cap, max_stops_per_day=int(max_stops_day),
    core_ratio=float(core_ratio_pct), tol_pct=float(tolerance_pct),
    tol_mode='target' if tol_mode_label.startswith('%ของเป้า') or
    tol_mode_label.startswith('% ของเป้า') else 'capacity',
    knn_k=int(knn_k), enable_stray_cleanup=en_stray, enable_majority_vote=en_major,
    enable_swap=en_swap, swap_rounds=int(swap_rounds), allow_vip_day_move=allow_vip_day,
    use_road=use_road, road_provider=road_provider, osrm_url=osrm_url, gmaps_key=gkey)

# ---- Scenario save / load ----
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
#  SECTION 14 — RUN
# =====================================================================================
st.sidebar.markdown("---")
if st.sidebar.button("🚀 ประมวลผลจัดสายส่งใหม่", use_container_width=True):
    if not new_trucks and not dissolve_trucks and not relieve_trucks:
        st.sidebar.error("❌ กรุณาเลือกรถต้นทาง หรือระบุเบอร์รถคันใหม่อย่างน้อย 1 คัน")
        st.stop()

    ph = st.empty()
    msg = "กำลังจัดสรรเส้นทาง (Multi-Donor Zoning)... 💧"
    if use_road:
        msg += " กำลังเรียก API ระยะทางถนนจริง อาจใช้เวลาสักครู่"
    show_loader(ph, msg)

    def getter(src, dst):
        if cfg.road_provider == 'osrm':
            return fetch_osrm_matrix(src, dst, cfg.osrm_url)
        if cfg.gmaps_key:
            return fetch_google_matrix(src, dst, cfg.gmaps_key)
        return None, 'ไม่ได้ระบุ Google API Key'

    try:
        res = run_multi_donor_zoning(df, cfg, target_pcts, dissolve_trucks, relieve_trucks,
                                     new_trucks, manual_vips,
                                     road_matrix_getter=getter if use_road else None)
        st.session_state['result'] = res
        st.session_state['zoning_cfg_used'] = cfg
    except Exception as e:
        ph.empty()
        st.exception(e)
        st.stop()
    ph.empty()

if 'result' not in st.session_state:
    st.info("👈 ตรวจผลวินิจฉัยด้านบน เลือกรถต้นทาง/รถใหม่ แล้วกด 'ประมวลผลจัดสายส่งใหม่'")
    st.stop()

res: ZoningResult = st.session_state['result']
ucfg: ZoningConfig = st.session_state['zoning_cfg_used']
rdf = res.result_df

for w in res.warnings:
    st.warning(f"⚠️ {w}")
for i in res.infos:
    st.info(f"ℹ️ {i}")

ov = rdf[rdf['เบอร์รถใหม่'] == OVERFLOW_LABEL]
if not ov.empty:
    need = math.ceil(ov[ucfg.vol_col].sum() / max(1.0, ucfg.daily_control_cap * DAYS_PER_MONTH))
    st.error(f"🚨 ลูกค้า {len(ov):,} ราย ({ov[ucfg.vol_col].sum():,.0f} ถัง/เดือน) จัดสรรไม่ได้ "
             f"— ควรเพิ่มรถอีกประมาณ {need} คัน หรือเพิ่ม % เป้าหมาย")

# =====================================================================================
#  SECTION 15 — KPI
# =====================================================================================
m = res.metrics
st.markdown("## 📈 ตัวชี้วัดผลลัพธ์ (ก่อน → หลัง)")
k1, k2, k3, k4 = st.columns(4)
k1.metric("รถที่เกินเพดาน", f"{int(m['over_after'])} คัน",
          delta=f"{int(m['over_after']-m['over_before']):+d} คัน", delta_color="inverse")
k2.metric("โหลดสูงสุดในฝูง", f"{m['peak_after']:,.0f} ถัง/วัน",
          delta=f"{m['peak_after']-m['peak_before']:+,.0f}", delta_color="inverse")
k3.metric("ความกระชับโซนเฉลี่ย", f"{m['compact_after_km']:.2f} กม.",
          delta=f"{m['compact_after_km']-m['compact_before_km']:+.2f} กม.", delta_color="inverse")
k4.metric("ลูกค้าที่ต้องย้ายสาย", f"{int(m['moved_cust']):,} ราย",
          delta=f"{m['moved_pct']:.1f}% ของทั้งหมด", delta_color="off")
st.caption(f"ส่วนเบี่ยงเบนโหลดระหว่างคัน: {m['std_before']:.1f} → **{m['std_after']:.1f}** "
           f"(ยิ่งต่ำยิ่งสมดุล) | ยอดที่ย้าย {m['moved_vol']:,.0f} ถัง/เดือน "
           f"| Core % ที่ใช้จริง {res.core_ratio_used:.0f}%")

# =====================================================================================
#  SECTION 16 — TARGET vs ACTUAL
# =====================================================================================
rows = []
for t, tg in res.targets.items():
    if tg <= 0:
        continue
    act = float(rdf.loc[rdf['เบอร์รถใหม่'] == t, ucfg.vol_col].sum())
    tp, ap = tg / ucfg.monthly_capacity * 100, act / ucfg.monthly_capacity * 100
    tolu = _tolerance_for(t, res.targets, ucfg)
    rows.append({'เบอร์รถ': t, 'ประเภท': '🆕 ใหม่' if t in new_trucks else
                 ('✂️ ดึงงานออก' if t in relieve_trucks else 'คงเดิม'),
                 'เป้าหมาย(%)': round(tp, 1), 'ทำได้จริง(%)': round(ap, 1),
                 'ส่วนต่าง(ถัง)': int(round(act - tg)),
                 'ค่าเผื่อ(±ถัง)': int(round(tolu)),
                 'สถานะ': '✅ ในเกณฑ์' if abs(act - tg) <= tolu else '⚠️ เกินค่าเผื่อ'})
if rows:
    st.markdown("### 🎯 เทียบเป้าหมาย vs ผลจริง")
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

c1, c2 = st.columns(2)
with c1:
    st.markdown("**ก่อนปรับ**")
    sb = df.groupby(truck_col).agg(จำนวนสมาชิก=(truck_col, 'count'),
                                   **{'ยอด(ถัง/เดือน)': (vol_col, 'sum')}).reset_index()
    st.dataframe(sb, use_container_width=True, hide_index=True)
with c2:
    st.markdown("**หลังปรับ**")
    sa = rdf.groupby('เบอร์รถใหม่').agg(จำนวนสมาชิก=('เบอร์รถใหม่', 'count'),
                                        **{'ยอด(ถัง/เดือน)': (vol_col, 'sum')}).reset_index()
    sa['ภาระงาน(%)'] = np.where(sa['เบอร์รถใหม่'] == OVERFLOW_LABEL, '-',
                                (sa['ยอด(ถัง/เดือน)'] / ucfg.monthly_capacity * 100)
                                .round(1).astype(str) + '%')
    st.dataframe(sa, use_container_width=True, hide_index=True)

# =====================================================================================
#  SECTION 17 — MAPS
# =====================================================================================
st.markdown("### 🗺️ แผนที่เปรียบเทียบการกระจายตัว")
truck_list = [t for t in sorted(rdf['เบอร์รถใหม่'].dropna().unique()) if t != OVERFLOW_LABEL]
view = st.selectbox("🔍 รูปแบบการแสดงผล:",
                    ["แสดงทั้งหมด (แยกสีตามเบอร์รถ)"] + truck_list)

palette = ['#3388FF', '#2ECC71', '#FF8C00', '#9B59B6', '#1ABC9C',
           '#E74C3C', '#F1C40F', '#16A085', '#8E44AD', '#D35400']
color_map = {t: ('#FF0000' if t in new_trucks else palette[i % len(palette)])
             for i, t in enumerate(truck_list)}

if view.startswith("แสดงทั้งหมด"):
    mb, ma, mode = df, rdf[rdf['เบอร์รถใหม่'] != OVERFLOW_LABEL], 'truck'
else:
    mb = df[df[truck_col] == view] if view in available_trucks else df.iloc[0:0]
    ma, mode = rdf[rdf['เบอร์รถใหม่'] == view], 'day'

cy_ = ma[lat_col].mean() if not ma.empty else df[lat_col].mean()
cx_ = ma[lon_col].mean() if not ma.empty else df[lon_col].mean()


def day_color(day_text: str) -> str:
    d, _ = parse_days_from_string(day_text)
    return DAY_COLORS.get(d[0], '#95A5A6') if d else '#95A5A6'


def draw(container, data, title, truck_field, day_field):
    with container:
        st.markdown(f"<div style='text-align:center;color:#FFD700;font-weight:bold;"
                    f"margin-bottom:8px'>{title}</div>", unsafe_allow_html=True)
        fm = folium.Map(location=[cy_, cx_], zoom_start=12 if mode == 'truck' else 14,
                        prefer_canvas=True)
        plugins.Fullscreen(position='topright').add_to(fm)
        layer = plugins.MarkerCluster().add_to(fm) if len(data) > 1500 else fm
        for _, r in data.iterrows():
            tid = str(r[truck_field])
            vip = (str(r.get('VIP_Status', '')).upper() == 'VIP'
                   or str(r[id_col]) in manual_vips)
            col = color_map.get(tid, '#95A5A6') if mode == 'truck' \
                else day_color(str(r.get(day_field, '')))
            nm = str(r[name_col]) if name_col else 'ไม่ระบุ'
            pop = (f"<b>รหัส:</b> {r[id_col]}<br><b>ชื่อ:</b> {nm}<br>"
                   f"<b>ยอด:</b> {int(r[vol_col])} ถัง<br><b>รถ:</b> {tid}<br>"
                   f"<b>วัน:</b> {r.get(day_field,'-')}")
            folium.CircleMarker([r[lat_col], r[lon_col]], radius=8 if vip else 5,
                                color='#FFD700' if vip else col, weight=2 if vip else 1,
                                fill=True, fill_color=col, fill_opacity=.9,
                                popup=folium.Popup(pop, max_width=300)).add_to(layer)
        components.html(fm.get_root().render(), height=460)


mc1, mc2 = st.columns(2)
draw(mc1, mb, "โซนเดิม (Before)", truck_col, day_col)
# แก้บั๊ก v1: แผนที่ After เดิมยังโชว์ 'วันเดิม' ทำให้ไม่เห็นผลของการเกลี่ยวัน
draw(mc2, ma, "โซนใหม่ (After — วันจัดส่งที่ปรับแล้ว)", 'เบอร์รถใหม่', 'วันจัดส่ง(ใหม่)')

# =====================================================================================
#  SECTION 18 — DAILY LOAD TABLE
# =====================================================================================
st.markdown("### 📅 ตารางวิเคราะห์โหลดรายวัน")
st.caption(f"🟢 {OPTIMAL_MIN}-{OPTIMAL_MAX} | 🟡 {AVOID_MIN}-{AVOID_MAX} | ⚪ <{AVOID_MIN} | "
           f"🔴 >{ucfg.daily_control_cap:.0f} (เกินเพดาน) | 🚚 รอบ3 {ESCALATE_TARGET_MIN}-"
           f"{ESCALATE_TARGET_MAX} | 🆘 >{ESCALATE_TARGET_MAX}")


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


ds_rows = []
for t in truck_list:
    mask = (rdf['เบอร์รถใหม่'] == t).to_numpy()
    dv = res.daily_matrix[mask].sum(axis=0) if mask.any() else np.zeros(WORKING_DAYS)
    dc = res.daily_stops[mask].sum(axis=0) if mask.any() else np.zeros(WORKING_DAYS)
    row = {'เบอร์รถ': t}
    row.update({DAY_NAMES[d]: int(round(dv[d])) for d in range(WORKING_DAYS)})
    row['จุดจอดสูงสุด/วัน'] = int(dc.max())
    row['โหลดสูงสุด/วัน'] = int(round(dv.max()))
    row['สถานะ'] = day_status(float(dv.max()), ucfg.daily_control_cap)
    ds_rows.append(row)
st.dataframe(pd.DataFrame(ds_rows), use_container_width=True, hide_index=True)

# =====================================================================================
#  SECTION 19 — DETAIL & EXPORT
# =====================================================================================
st.markdown("### 📋 รายละเอียดการโยกย้ายสมาชิก")
detail = rdf.copy()
detail['เบอร์รถเดิม'] = detail[truck_col]
detail['วันจัดส่ง(เดิม)'] = detail[day_col]
want = [id_col] + ([name_col] if name_col else []) + \
    ['วันจัดส่ง(เดิม)', 'วันจัดส่ง(ใหม่)', 'สถานะการย้ายวัน', vol_col,
     'เบอร์รถเดิม', 'เบอร์รถใหม่', 'สถานะ']
want = list(dict.fromkeys([c for c in want if c in detail.columns]))   # กันคอลัมน์ซ้ำ
detail = detail[want]

f1, f2 = st.columns([1, 1])
only_moved = f1.checkbox("แสดงเฉพาะรายที่ย้ายสาย", False)
truck_filter = f2.multiselect("กรองตามเบอร์รถใหม่", truck_list, [])
view_df = detail
if only_moved:
    view_df = view_df[view_df['สถานะ'].str.startswith('ย้าย')]
if truck_filter:
    view_df = view_df[view_df['เบอร์รถใหม่'].isin(truck_filter)]
st.dataframe(view_df, use_container_width=True, hide_index=True)

st.markdown("---")


@st.cache_data
def to_csv(d: pd.DataFrame) -> bytes:
    return d.to_csv(index=False).encode('utf-8-sig')


b1, b2, b3 = st.columns([1, 2, 1])
with b2:
    st.download_button("📥 ดาวน์โหลดผลลัพธ์ทั้งหมด (CSV เปิดใน Excel ได้ทันที)",
                       to_csv(detail), 'route_rebalance_result.csv', 'text/csv',
                       use_container_width=True)
