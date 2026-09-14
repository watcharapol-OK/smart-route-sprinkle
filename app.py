# =====================================================================================
#  SMART ROUTE REBALANCER — PRODUCTION BUILD v2.1
#  Multi-Donor Fleet Rebalancing Engine
#  ---------------------------------------------------------------------------------
#  requirements.txt:
#     streamlit>=1.31
#     pandas>=2.0
#     numpy>=1.24
#     folium>=0.15
#     scipy>=1.10
#     requests>=2.31
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
    page_title="Smart Route Rebalancer v2.1",
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
    "",
    "nan",
    "none",
    "null",
    "-",
    "ไม่ระบุ",
    "na",
    "n/a",
}

# โซนโหลดรายวัน (ถัง/วัน)
OPTIMAL_MIN = 140
OPTIMAL_MAX = 155
AVOID_MIN = 121
AVOID_MAX = 139
TARGET_DAY_CAP = 148
ESCALATE_THRESHOLD = 160
ESCALATE_TARGET_MIN = 180
ESCALATE_TARGET_MAX = 190

EARTH_RADIUS_M = 6371008.8

DAY_NAMES = {
    0: "จันทร์",
    1: "อังคาร",
    2: "พุธ",
    3: "พฤหัสบดี",
    4: "ศุกร์",
    5: "เสาร์",
}

DAY_SHORT = {
    0: "จ",
    1: "อ",
    2: "พ",
    3: "พฤ",
    4: "ศ",
    5: "ส",
}

DAY_COLORS = {
    0: "#FFD700",
    1: "#FF69B4",
    2: "#28A745",
    3: "#FD7E14",
    4: "#00BFFF",
    5: "#6F42C1",
}

# เรียง token จากยาวไปสั้น เพื่อไม่ให้ "พ" จับ "พฤหัสบดี" ก่อน
DAY_TOKENS: List[Tuple[str, int]] = [
    ("จันทร์", 0),
    ("อังคาร", 1),
    ("พฤหัสบดี", 3),
    ("พฤหัสฯ", 3),
    ("พฤหัส", 3),
    ("พฤ", 3),
    ("พุธ", 2),
    ("ศุกร์", 4),
    ("เสาร์", 5),
    ("monday", 0),
    ("tuesday", 1),
    ("wednesday", 2),
    ("thursday", 3),
    ("friday", 4),
    ("saturday", 5),
    ("mon", 0),
    ("tue", 1),
    ("wed", 2),
    ("thu", 3),
    ("fri", 4),
    ("sat", 5),
    ("จ", 0),
    ("อ", 1),
    ("พ", 2),
    ("ศ", 4),
    ("ส", 5),
]

ALL_DAYS_TOKENS = (
    "ทุกวัน",
    "จ-ส",
    "จันทร์-เสาร์",
    "จ.-ส.",
    "ทุกวันทำการ",
)


# =====================================================================================
#  SECTION 2 — PURE HELPERS
# =====================================================================================
def parse_days_from_string(val_str) -> Tuple[List[int], str]:
    """
    แปลงข้อความวันจัดส่งเป็น index วัน 0-5

    Returns:
        tuple:
            - รายการ index วัน
            - สถานะ: "ok", "empty" หรือ "unparsed"

    หลักการ:
        - ค่าว่างจะคืนสถานะ empty
        - ข้อความทุกวัน/จันทร์-เสาร์จะคืนวัน 0-5
        - ตัวเลขยอมรับเฉพาะ token ที่เป็นเลขล้วน 1-6
        - กรณีอ่านไม่ได้จะไม่สมมติเป็นทุกวันโดยอัตโนมัติ
    """
    raw = "" if val_str is None else str(val_str)
    val = raw.strip().lower()

    if val.lower() in NO_TRUCK_TOKENS:
        return [], "empty"

    compact = re.sub(r"\s+", "", val)
    if any(token in compact for token in ALL_DAYS_TOKENS):
        return list(range(WORKING_DAYS)), "ok"

    days = set()

    # แยกตามเครื่องหมายคั่น แต่ไม่ทำลายคำ เช่น "พฤหัสบดี"
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
    """แปลงรายการ index วันเป็นชื่อวันแบบเต็ม"""
    if not days_list:
        return "ไม่ระบุ"

    days = sorted(
        {
            int(day)
            for day in days_list
            if 0 <= int(day) < WORKING_DAYS
        }
    )

    if not days:
        return "ไม่ระบุ"

    if len(days) == WORKING_DAYS:
        return "จ-ส"

    return ", ".join(DAY_NAMES[day] for day in days)


def format_days_short(days_list: Sequence[int]) -> str:
    """แปลงรายการ index วันเป็นชื่อวันแบบย่อ"""
    if not days_list:
        return "-"

    days = sorted(
        {
            int(day)
            for day in days_list
            if 0 <= int(day) < WORKING_DAYS
        }
    )

    if not days:
        return "-"

    if len(days) == WORKING_DAYS:
        return "จ-ส"

    return "".join(DAY_SHORT[day] for day in days)


def project_xy(
    lat,
    lon,
    lat0: Optional[float] = None,
) -> Tuple[np.ndarray, np.ndarray, float]:
    """
    แปลง latitude/longitude เป็นพิกัด x/y หน่วยเมตร
    ด้วย equirectangular projection
    """
    lat_array = np.asarray(lat, dtype=float)
    lon_array = np.asarray(lon, dtype=float)

    if lat_array.size == 0 or lon_array.size == 0:
        return (
            np.asarray([], dtype=float),
            np.asarray([], dtype=float),
            0.0 if lat0 is None else float(lat0),
        )

    if lat0 is None:
        lat0 = float(np.nanmean(lat_array))

    scale = math.cos(math.radians(lat0))

    x = np.radians(lon_array) * EARTH_RADIUS_M * scale
    y = np.radians(lat_array) * EARTH_RADIUS_M

    return x, y, lat0


def knn_indices(xy: np.ndarray, k: int) -> np.ndarray:
    """
    หา index เพื่อนบ้านใกล้ที่สุด k จุด โดยไม่รวมตัวเอง

    ใช้ scipy cKDTree หากติดตั้งไว้
    และใช้ brute-force แบบแบ่งก้อนเป็น fallback
    """
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

        distances = (
            (xy[start:end, None, :] - xy[None, :, :]) ** 2
        ).sum(axis=2)

        local_rows = np.arange(end - start)
        global_rows = np.arange(start, end)
        distances[local_rows, global_rows] = np.inf

        # kth ใช้ k-1 เพราะต้องการสมาชิกจำนวน k ตัวแรก
        nearest = np.argpartition(
            distances,
            kth=k - 1,
            axis=1,
        )[:, :k]

        nearest_distances = np.take_along_axis(
            distances,
            nearest,
            axis=1,
        )

        order = np.argsort(nearest_distances, axis=1)
        output[start:end] = np.take_along_axis(nearest, order, axis=1)

    return output


def kmeans_seeds(
    xy: np.ndarray,
    weights: np.ndarray,
    k: int,
    iters: int = 20,
    seed: int = 42,
) -> np.ndarray:
    """
    Weighted k-means++ สำหรับกำหนดตำแหน่งเริ่มต้นของรถใหม่หลายคัน
    """
    xy = np.asarray(xy, dtype=float)
    weights = np.asarray(weights, dtype=float)

    n = len(xy)
    if n == 0:
        return np.zeros((0, 2), dtype=float)

    k = max(1, min(int(k), n))
    rng = np.random.default_rng(seed)

    valid_weights = np.where(
        np.isfinite(weights) & (weights > 0),
        weights,
        1e-9,
    )

    first_index = rng.choice(
        n,
        p=valid_weights / valid_weights.sum(),
    )

    centers = [xy[first_index]]

    for _ in range(k - 1):
        current_centers = np.asarray(centers, dtype=float)

        distance_squared = np.min(
            (
                xy[:, None, :]
                - current_centers[None, :, :]
            ) ** 2,
            axis=2,
        ).sum(axis=1)

        probabilities = distance_squared * valid_weights

        if probabilities.sum() > 0:
            probabilities = probabilities / probabilities.sum()
        else:
            probabilities = np.full(n, 1.0 / n)

        next_index = rng.choice(n, p=probabilities)
        centers.append(xy[next_index])

    centers_array = np.asarray(centers, dtype=float)

    for _ in range(max(1, int(iters))):
        distance_squared = (
            (
                xy[:, None, :]
                - centers_array[None, :, :]
            ) ** 2
        ).sum(axis=2)

        labels = distance_squared.argmin(axis=1)
        new_centers = centers_array.copy()

        for cluster_index in range(k):
            mask = labels == cluster_index
            if not mask.any():
                continue

            cluster_weights = valid_weights[mask]
            new_centers[cluster_index] = np.average(
                xy[mask],
                axis=0,
                weights=cluster_weights,
            )

        if np.allclose(
            new_centers,
            centers_array,
            atol=1e-3,
            rtol=0.0,
        ):
            centers_array = new_centers
            break

        centers_array = new_centers

    return centers_array


def clean_truck_ids(values: Sequence) -> List[str]:
    """กรองค่ารถว่าง รถ nan และค่าขยะออกจากรายการเบอร์รถ"""
    output: List[str] = []

    for value in values:
        truck_id = str(value).strip()

        if truck_id.lower() in NO_TRUCK_TOKENS:
            continue

        output.append(truck_id)

    return sorted(set(output))


def guess_col(
    substrings: Sequence[str],
    cols: Sequence[str],
    fallback: Optional[str] = None,
    allow_none: bool = False,
) -> Optional[str]:
    """
    เดาคอลัมน์จากคำที่อยู่ในชื่อคอลัมน์

    หาก allow_none=True และหาไม่พบ จะคืน None
    เพื่อป้องกันคอลัมน์ VIP หรือชื่อลูกค้าถูกเลือกเป็นคอลัมน์แรกโดยไม่ตั้งใจ
    """
    for column in cols:
        column_text = str(column).lower()

        if any(
            str(substring).lower() in column_text
            for substring in substrings
        ):
            return column

    if allow_none:
        return None

    if fallback is not None:
        return fallback

    return cols[0] if len(cols) else None


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
#  SECTION 4 — ROAD DISTANCE PROVIDERS
# =====================================================================================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_osrm_matrix(
    source_coords: tuple,
    dest_coords: tuple,
    base_url: str,
    max_coords: int = 95,
) -> Tuple[Optional[np.ndarray], str]:
    """
    ดึง Distance Matrix จาก OSRM

    แบ่ง source เป็นหลาย batch เพื่อให้จำนวนพิกัดรวมต่อ request
    ไม่เกินข้อจำกัดของ OSRM server
    """
    import requests

    sources = list(source_coords)
    destinations = list(dest_coords)

    source_count = len(sources)
    destination_count = len(destinations)

    if source_count == 0:
        return None, "ไม่มีพิกัดต้นทาง"

    if destination_count == 0:
        return None, "ไม่มีพิกัดปลายทาง"

    if destination_count >= max_coords:
        return (
            None,
            f"จำนวนปลายทาง {destination_count} จุด "
            f"มากกว่าขีดจำกัด OSRM ต่อคำขอ ({max_coords - 1} จุด)",
        )

    batch_size = max(1, max_coords - destination_count)

    output = np.full(
        (source_count, destination_count),
        np.nan,
        dtype=float,
    )

    for start in range(0, source_count, batch_size):
        chunk = sources[start:start + batch_size]
        all_coordinates = chunk + destinations

        coordinate_string = ";".join(
            f"{float(lon):.6f},{float(lat):.6f}"
            for lat, lon in all_coordinates
        )

        endpoint = (
            f"{base_url.rstrip('/')}/table/v1/driving/"
            f"{coordinate_string}"
        )

        params = {
            "sources": ";".join(
                str(index)
                for index in range(len(chunk))
            ),
            "destinations": ";".join(
                str(index)
                for index in range(
                    len(chunk),
                    len(all_coordinates),
                )
            ),
            "annotations": "distance",
        }

        try:
            response = requests.get(
                endpoint,
                params=params,
                timeout=40,
            )
            response.raise_for_status()

            data = response.json()

            if data.get("code") != "Ok":
                return (
                    None,
                    f"OSRM ตอบกลับ code={data.get('code')}",
                )

            distances = data.get("distances")
            if distances is None:
                return None, "OSRM ไม่ส่งตารางระยะทางกลับมา"

            matrix = np.asarray(distances, dtype=float)

            expected_shape = (
                len(chunk),
                destination_count,
            )

            if matrix.shape != expected_shape:
                return (
                    None,
                    "ขนาดตารางระยะทางจาก OSRM ไม่ตรงกับที่ร้องขอ "
                    f"(ได้รับ {matrix.shape}, คาดว่า {expected_shape})",
                )

            output[
                start:start + len(chunk),
                :,
            ] = matrix

        except Exception as exc:
            return None, f"OSRM error: {exc}"

        # ลดความเสี่ยงต่อการติด rate limit ของ public demo server
        time.sleep(0.35)

    return output, ""


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_google_matrix(
    source_coords: tuple,
    dest_coords: tuple,
    api_key: str,
) -> Tuple[Optional[np.ndarray], str]:
    """
    ดึง Distance Matrix จาก Google

    จำกัดไม่เกิน 100 elements ต่อ request
    และไม่เกิน 25 origins ต่อ request
    """
    import requests

    sources = list(source_coords)
    destinations = list(dest_coords)

    source_count = len(sources)
    destination_count = len(destinations)

    if source_count == 0:
        return None, "ไม่มีพิกัดต้นทาง"

    if destination_count == 0:
        return None, "ไม่มีพิกัดปลายทาง"

    if not str(api_key).strip():
        return None, "ไม่ได้ระบุ Google API Key"

    max_elements = 100
    max_origins = 25

    if destination_count > max_elements:
        return (
            None,
            f"จำนวนปลายทาง {destination_count} จุด "
            f"เกินข้อจำกัด {max_elements} elements ต่อ request",
        )

    chunk_size = max(
        1,
        min(
            max_origins,
            max_elements // destination_count,
        ),
    )

    output = np.full(
        (source_count, destination_count),
        np.nan,
        dtype=float,
    )

    destination_string = "|".join(
        f"{float(lat):.6f},{float(lon):.6f}"
        for lat, lon in destinations
    )

    for start in range(0, source_count, chunk_size):
        chunk = sources[start:start + chunk_size]

        origin_string = "|".join(
            f"{float(lat):.6f},{float(lon):.6f}"
            for lat, lon in chunk
        )

        try:
            response = requests.get(
                "https://maps.googleapis.com/maps/api/distancematrix/json",
                params={
                    "origins": origin_string,
                    "destinations": destination_string,
                    "key": api_key,
                    "mode": "driving",
                },
                timeout=40,
            )
            response.raise_for_status()

            data = response.json()
            status = data.get("status")

            if status != "OK":
                error_message = data.get("error_message", "")
                return (
                    None,
                    f"Google status={status} {error_message}".strip(),
                )

            rows = data.get("rows", [])
            if len(rows) != len(chunk):
                return (
                    None,
                    "จำนวนแถวจาก Google Distance Matrix ไม่ตรงกับที่ร้องขอ",
                )

            for local_index, row in enumerate(rows):
                elements = row.get("elements", [])

                for destination_index, element in enumerate(elements):
                    if destination_index >= destination_count:
                        break

                    if element.get("status") == "OK":
                        distance = element.get("distance", {}).get("value")

                        if distance is not None:
                            output[
                                start + local_index,
                                destination_index,
                            ] = float(distance)

        except Exception as exc:
            return None, f"Google error: {exc}"

    return output, ""# =====================================================================================
#  SECTION 5 — CAPACITY PLANNING
# =====================================================================================
def compute_default_targets(
    vol_by_truck: Dict[str, float],
    dissolve: Sequence[str],
    keep: Sequence[str],
    new_trucks: Sequence[str],
    cap_units: float,
) -> Tuple[Dict[str, float], float]:
    """
    คำนวณเป้าหมายเริ่มต้นรายคัน

    หลักการ:
        1. รวมยอดของรถที่ยุบทั้งคันเข้า allocation pool
        2. รถเดิมที่เกินเพดานจะถูกลดเป้าหมายลงมาเท่ากับ cap_units
        3. ส่วนเกินจะถูกจัดให้รถใหม่ก่อน
        4. ยอดที่เหลือจะถูกเกลี่ยตาม headroom ของรถทุกคัน
        5. leftover > 0 หมายถึงความจุรถทั้งหมดไม่เพียงพอ
    """
    capacity_limit = max(0.0, float(cap_units))

    pool = float(
        sum(
            float(vol_by_truck.get(truck, 0.0))
            for truck in dissolve
        )
    )

    targets: Dict[str, float] = {}

    for truck in keep:
        current_volume = max(
            0.0,
            float(vol_by_truck.get(truck, 0.0)),
        )

        if current_volume > capacity_limit:
            pool += current_volume - capacity_limit
            targets[truck] = capacity_limit
        else:
            targets[truck] = current_volume

    for truck in new_trucks:
        targets[truck] = 0.0

    # เติมรถใหม่ก่อน เพื่อให้ส่วนเกินจาก donor มีปลายทางชัดเจน
    for truck in new_trucks:
        if pool <= 1e-6:
            break

        available_capacity = max(
            0.0,
            capacity_limit - targets.get(truck, 0.0),
        )

        allocated = min(available_capacity, pool)
        targets[truck] = targets.get(truck, 0.0) + allocated
        pool -= allocated

    # เกลี่ยยอดที่เหลือลงรถทุกคันตาม headroom
    for _ in range(60):
        if pool <= 1e-6:
            break

        headroom = {
            truck: max(
                0.0,
                capacity_limit - target,
            )
            for truck, target in targets.items()
            if capacity_limit - target > 1e-6
        }

        if not headroom:
            break

        total_headroom = float(sum(headroom.values()))
        if total_headroom <= 1e-9:
            break

        volume_before = pool
        distribution_ratio = min(
            1.0,
            pool / total_headroom,
        )

        for truck, available in headroom.items():
            allocated = min(
                pool,
                available * distribution_ratio,
            )

            targets[truck] += allocated
            pool -= allocated

            if pool <= 1e-6:
                pool = 0.0
                break

        if abs(volume_before - pool) <= 1e-9:
            break

    return targets, max(0.0, pool)


def diagnose_fleet(
    df: pd.DataFrame,
    cfg: ZoningConfig,
) -> pd.DataFrame:
    """
    วิเคราะห์สถานะรถปัจจุบันก่อนปรับสาย

    แสดง:
        - จำนวนลูกค้า
        - ยอดต่อเดือน
        - ภาระงานเทียบความจุ
        - โหลดสูงสุดต่อวัน
        - จำนวนจุดจอดสูงสุดต่อวัน
        - ส่วนเกินต่อวัน
    """
    output_rows = []

    if df.empty:
        return pd.DataFrame()

    for truck, group in df.groupby(cfg.truck_col, dropna=False):
        truck_id = str(truck).strip()

        if truck_id.lower() in NO_TRUCK_TOKENS:
            continue

        daily_volume = np.zeros(
            WORKING_DAYS,
            dtype=float,
        )

        daily_stops = np.zeros(
            WORKING_DAYS,
            dtype=float,
        )

        for _, row in group.iterrows():
            days, _ = parse_days_from_string(
                row.get(cfg.day_col),
            )

            if not days:
                days = list(range(WORKING_DAYS))

            monthly_volume = float(
                pd.to_numeric(
                    row.get(cfg.vol_col),
                    errors="coerce",
                )
                or 0.0
            )

            volume_per_delivery_day = (
                monthly_volume
                / max(1, len(days))
                / WEEKS_PER_MONTH
            )

            for day in days:
                daily_volume[day] += volume_per_delivery_day
                daily_stops[day] += 1

        total_monthly_volume = float(
            pd.to_numeric(
                group[cfg.vol_col],
                errors="coerce",
            )
            .fillna(0)
            .sum()
        )

        peak_daily_volume = float(
            daily_volume.max()
        )

        peak_daily_stops = int(
            round(float(daily_stops.max()))
        )

        if peak_daily_volume > cfg.daily_control_cap:
            status = "🔴 เกินเพดาน"
        elif peak_daily_volume >= OPTIMAL_MIN:
            status = "🟢 เหมาะสม"
        elif peak_daily_volume >= AVOID_MIN:
            status = "🟡 ควรเลี่ยง"
        else:
            status = "⚪ เบาเกิน"

        output_rows.append(
            {
                "เบอร์รถ": truck_id,
                "จำนวนลูกค้า": int(len(group)),
                "ยอด/เดือน": int(round(total_monthly_volume)),
                "ภาระงาน(%)": round(
                    total_monthly_volume
                    / max(1.0, cfg.monthly_capacity)
                    * 100.0,
                    1,
                ),
                "โหลดสูงสุด/วัน": int(
                    round(peak_daily_volume)
                ),
                "จุดจอดสูงสุด/วัน": peak_daily_stops,
                "ส่วนเกิน/วัน": int(
                    round(
                        max(
                            0.0,
                            peak_daily_volume
                            - cfg.daily_control_cap,
                        )
                    )
                ),
                "สถานะ": status,
            }
        )

    output = pd.DataFrame(output_rows)

    if output.empty:
        return output

    return output.sort_values(
        "โหลดสูงสุด/วัน",
        ascending=False,
    ).reset_index(drop=True)


# =====================================================================================
#  SECTION 6 — ZONING ENGINE HELPERS
# =====================================================================================
def _tolerance_for(
    truck: str,
    targets: Dict[str, float],
    cfg: ZoningConfig,
) -> float:
    """
    คำนวณค่าเผื่อของรถแต่ละคัน

    target:
        คิดเป็นเปอร์เซ็นต์ของเป้าหมายรถคันนั้น

    capacity:
        คิดเป็นเปอร์เซ็นต์ของความจุอ้างอิงเต็ม
    """
    if cfg.tol_mode == "target":
        return max(
            40.0,
            (cfg.tol_pct / 100.0)
            * max(0.0, targets.get(truck, 0.0)),
        )

    return (
        cfg.tol_pct
        / 100.0
        * max(0.0, cfg.monthly_capacity)
    )


def build_stops(
    df: pd.DataFrame,
    cfg: ZoningConfig,
) -> pd.DataFrame:
    """
    รวมลูกค้าที่ใช้พิกัดเดียวกันเป็นหนึ่งจุดจอด

    จุดจอดหนึ่งจุดถือเป็นก้อนงานที่ไม่ควรถูกแบ่งข้ามรถ
    """
    required_columns = {
        "coord_key",
        "x",
        "y",
        "is_vip_locked",
        cfg.lat_col,
        cfg.lon_col,
        cfg.vol_col,
        cfg.id_col,
        cfg.truck_col,
    }

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "ไม่พบคอลัมน์ที่จำเป็นสำหรับสร้างจุดจอด: "
            + ", ".join(map(str, missing_columns))
        )

    stops = (
        df.groupby(
            "coord_key",
            dropna=False,
        )
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

    stops["orig_truck"] = (
        stops["orig_truck"]
        .astype(str)
        .str.strip()
    )

    stops["total_vol"] = (
        pd.to_numeric(
            stops["total_vol"],
            errors="coerce",
        )
        .fillna(0.0)
        .astype(float)
    )

    return stops


def compute_core_keys(
    stops: pd.DataFrame,
    ratio: float,
    eligible_trucks: Sequence[str],
    ratio_override: Optional[Dict[str, float]] = None,
) -> set:
    """
    เลือกจุดจอดแกนกลางของรถเดิมเพื่อทำ Core Lock

    จุดที่อยู่ใกล้ centroid จะถูกเลือกก่อน
    จนยอดสะสมถึงสัดส่วนที่กำหนด
    """
    core_keys: set = set()

    if stops.empty or ratio <= 0:
        return core_keys

    ratio_override = ratio_override or {}

    for truck in eligible_trucks:
        truck_ratio = min(
            float(ratio),
            float(ratio_override.get(truck, 100.0)),
        )

        if truck_ratio <= 0:
            continue

        group = stops[
            stops["orig_truck"] == truck
        ].copy()

        if group.empty:
            continue

        center_x = float(
            np.average(
                group["x"].to_numpy(dtype=float),
                weights=np.maximum(
                    group["total_vol"].to_numpy(dtype=float),
                    1e-9,
                ),
            )
        )

        center_y = float(
            np.average(
                group["y"].to_numpy(dtype=float),
                weights=np.maximum(
                    group["total_vol"].to_numpy(dtype=float),
                    1e-9,
                ),
            )
        )

        group["_distance_squared"] = (
            (group["x"] - center_x) ** 2
            + (group["y"] - center_y) ** 2
        )

        group = group.sort_values(
            "_distance_squared",
            ascending=True,
        )

        total_volume = max(
            1e-6,
            float(group["total_vol"].sum()),
        )

        cumulative_ratio = (
            group["total_vol"].cumsum()
            / total_volume
        )

        selected = cumulative_ratio <= (
            truck_ratio / 100.0
        )

        # ต้องมีแกนกลางอย่างน้อยหนึ่งจุดเมื่อ ratio > 0
        if not selected.any() and len(group):
            selected.iloc[0] = True

        core_keys.update(
            group.loc[selected, "coord_key"].tolist()
        )

    return core_keys


def _assign_capacitated(
    stops: pd.DataFrame,
    trucks: List[str],
    targets: Dict[str, float],
    tolerance: Dict[str, float],
    seeds: Dict[str, Tuple[float, float]],
    road: Optional[np.ndarray],
    max_rounds: int = 80,
) -> Tuple[np.ndarray, Dict[str, float]]:
    """
    จัดจุดจอดให้รถตามระยะทางและข้อจำกัดความจุ

    ลำดับ:
        1. โหลดจุดที่ถูกล็อกไว้ก่อน
        2. จัดคู่ที่ใกล้และยังไม่เกิน target+tolerance
        3. ใช้ best-fit แบบผ่อนปรนกับจุดที่ยังไม่ถูกจัด
        4. จุดที่จัดไม่ได้จะคงค่า -1 และถูกแปลงเป็น Overflow ภายหลัง
    """
    number_of_stops = len(stops)
    number_of_trucks = len(trucks)

    if number_of_stops == 0:
        return (
            np.asarray([], dtype=int),
            {truck: 0.0 for truck in trucks},
        )

    if number_of_trucks == 0:
        return (
            np.full(number_of_stops, -1, dtype=int),
            {},
        )

    coordinates = stops[
        ["x", "y"]
    ].to_numpy(dtype=float)

    volumes = stops[
        "total_vol"
    ].to_numpy(dtype=float)

    truck_index = {
        truck: index
        for index, truck in enumerate(trucks)
    }

    assigned = np.array(
        [
            truck_index.get(value, -1)
            if isinstance(value, str)
            else -1
            for value in stops[
                "assigned_truck"
            ].tolist()
        ],
        dtype=int,
    )

    loads = {
        truck: 0.0
        for truck in trucks
    }

    for stop_index in np.where(
        assigned >= 0
    )[0]:
        truck = trucks[assigned[stop_index]]
        loads[truck] += volumes[stop_index]

    if road is not None:
        road = np.asarray(road, dtype=float)

        expected_shape = (
            number_of_stops,
            number_of_trucks,
        )

        if road.shape != expected_shape:
            raise ValueError(
                "ขนาด Road Distance Matrix ไม่ถูกต้อง "
                f"(ได้รับ {road.shape}, คาดว่า {expected_shape})"
            )

    for _ in range(max(1, int(max_rounds))):
        eligible_trucks = [
            truck
            for truck in trucks
            if loads[truck]
            < targets.get(truck, 0.0) - 1e-9
        ]

        if not eligible_trucks:
            break

        candidate_indices = np.where(
            assigned < 0
        )[0]

        if candidate_indices.size == 0:
            break

        eligible_columns = [
            truck_index[truck]
            for truck in eligible_trucks
        ]

        if road is not None:
            distances = road[
                np.ix_(
                    candidate_indices,
                    eligible_columns,
                )
            ].astype(float)

            distances = np.where(
                np.isfinite(distances),
                distances,
                np.inf,
            )

        else:
            centers = []

            for truck in eligible_trucks:
                mask = (
                    assigned
                    == truck_index[truck]
                )

                if mask.any():
                    center = np.average(
                        coordinates[mask],
                        axis=0,
                        weights=np.maximum(
                            volumes[mask],
                            1e-9,
                        ),
                    )
                else:
                    fallback_center = (
                        float(coordinates[:, 0].mean()),
                        float(coordinates[:, 1].mean()),
                    )

                    center = np.asarray(
                        seeds.get(
                            truck,
                            fallback_center,
                        ),
                        dtype=float,
                    )

                centers.append(center)

            centers_array = np.asarray(
                centers,
                dtype=float,
            )

            distances = np.sqrt(
                (
                    (
                        coordinates[
                            candidate_indices
                        ][:, None, :]
                        - centers_array[
                            None, :, :
                        ]
                    )
                    ** 2
                ).sum(axis=2)
            )

        capacity_limits = np.asarray(
            [
                targets.get(truck, 0.0)
                + tolerance.get(truck, 0.0)
                for truck in eligible_trucks
            ],
            dtype=float,
        )

        current_loads = np.asarray(
            [
                loads[truck]
                for truck in eligible_trucks
            ],
            dtype=float,
        )

        feasible = (
            current_loads[None, :]
            + volumes[candidate_indices][:, None]
            <= capacity_limits[None, :]
        )

        distances = np.where(
            feasible,
            distances,
            np.inf,
        )

        best_local_truck = distances.argmin(
            axis=1
        )

        best_distance = distances[
            np.arange(len(candidate_indices)),
            best_local_truck,
        ]

        feasible_rows = np.isfinite(
            best_distance
        )

        if not feasible_rows.any():
            break

        feasible_candidates = candidate_indices[
            feasible_rows
        ]

        feasible_truck_indices = best_local_truck[
            feasible_rows
        ]

        order = np.argsort(
            best_distance[feasible_rows]
        )

        placed_any = False

        for position in order:
            stop_index = feasible_candidates[position]

            if assigned[stop_index] >= 0:
                continue

            truck = eligible_trucks[
                feasible_truck_indices[position]
            ]

            upper_limit = (
                targets.get(truck, 0.0)
                + tolerance.get(truck, 0.0)
            )

            if (
                loads[truck]
                + volumes[stop_index]
                > upper_limit
            ):
                continue

            assigned[stop_index] = truck_index[truck]
            loads[truck] += volumes[stop_index]
            placed_any = True

        if not placed_any:
            break

    # Best-fit แบบผ่อนปรน
    for stop_index in np.where(
        assigned < 0
    )[0]:
        candidate_trucks = [
            truck
            for truck in trucks
            if targets.get(truck, 0.0) > 0
        ]

        if not candidate_trucks:
            continue

        # เลือกรถที่เหลือ headroom มากที่สุด
        best_truck = max(
            candidate_trucks,
            key=lambda truck: (
                targets.get(truck, 0.0)
                - loads.get(truck, 0.0)
            ),
        )

        target = targets.get(
            best_truck,
            0.0,
        )

        projected_load = (
            loads.get(best_truck, 0.0)
            + volumes[stop_index]
        )

        # ยอมเกินเป้าได้ไม่เกิน 15% ในรอบผ่อนปรน
        relaxed_limit = (
            target
            + max(
                tolerance.get(best_truck, 0.0),
                target * 0.15,
            )
        )

        if projected_load <= relaxed_limit:
            assigned[stop_index] = truck_index[
                best_truck
            ]
            loads[best_truck] = projected_load

    return assigned, loads


def cleanup_stray_points(
    stops: pd.DataFrame,
    trucks: List[str],
    targets: Dict[str, float],
    loads: Dict[str, float],
    tolerance: Dict[str, float],
    multiplier: float,
    rounds: int = 3,
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """
    ย้ายจุดที่หลุดออกจากกลุ่มของรถตัวเองอย่างชัดเจน
    ไปยังรถที่มีศูนย์กลางใกล้กว่าและยังมีความจุ
    """
    stops = stops.copy()
    loads = dict(loads)

    for _ in range(max(1, int(rounds))):
        changed = False
        centers: Dict[str, Tuple[float, float]] = {}

        for truck in trucks:
            group = stops[
                stops["assigned_truck"] == truck
            ]

            if group.empty:
                continue

            weights = np.maximum(
                group["total_vol"].to_numpy(dtype=float),
                1e-9,
            )

            centers[truck] = (
                float(
                    np.average(
                        group["x"],
                        weights=weights,
                    )
                ),
                float(
                    np.average(
                        group["y"],
                        weights=weights,
                    )
                ),
            )

        for truck in trucks:
            mask = (
                (stops["assigned_truck"] == truck)
                & (~stops["is_locked"].astype(bool))
            )

            group = stops[mask]

            if len(group) < 3 or truck not in centers:
                continue

            center_x, center_y = centers[truck]

            distances = np.sqrt(
                (group["x"] - center_x) ** 2
                + (group["y"] - center_y) ** 2
            )

            median_distance = float(
                distances.median()
            )

            radius = (
                median_distance * 3.0
                + 1.0
            )

            stray_indices = group.index[
                distances > radius
            ]

            for stop_index in stray_indices:
                stop = stops.loc[stop_index]

                own_distance_squared = (
                    (stop["x"] - center_x) ** 2
                    + (stop["y"] - center_y) ** 2
                )

                best_truck = None
                best_distance_squared = float("inf")

                for other_truck, (
                    other_x,
                    other_y,
                ) in centers.items():
                    if other_truck == truck:
                        continue

                    distance_squared = (
                        (stop["x"] - other_x) ** 2
                        + (stop["y"] - other_y) ** 2
                    )

                    if (
                        distance_squared
                        < best_distance_squared
                    ):
                        best_distance_squared = (
                            distance_squared
                        )
                        best_truck = other_truck

                if best_truck is None:
                    continue

                projected_load = (
                    loads.get(best_truck, 0.0)
                    + float(stop["total_vol"])
                )

                allowed_load = (
                    targets.get(best_truck, 0.0)
                    + tolerance.get(best_truck, 0.0)
                    * multiplier
                )

                is_materially_closer = (
                    best_distance_squared
                    < own_distance_squared * 0.6
                )

                if (
                    is_materially_closer
                    and projected_load <= allowed_load
                ):
                    volume = float(
                        stop["total_vol"]
                    )

                    stops.at[
                        stop_index,
                        "assigned_truck",
                    ] = best_truck

                    loads[truck] = (
                        loads.get(truck, 0.0)
                        - volume
                    )

                    loads[best_truck] = (
                        loads.get(best_truck, 0.0)
                        + volume
                    )

                    changed = True

        if not changed:
            break

    return stops, loads


def majority_vote_smoothing(
    stops: pd.DataFrame,
    trucks: List[str],
    targets: Dict[str, float],
    loads: Dict[str, float],
    tolerance: Dict[str, float],
    cfg: ZoningConfig,
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """
    ขัดผิวรอยต่อของโซนด้วย k-nearest-neighbor majority vote
    โดยไม่ย้ายจุดที่ถูกล็อก
    """
    stops = stops.copy().reset_index(drop=True)
    loads = dict(loads)

    number_of_stops = len(stops)

    if number_of_stops < cfg.knn_k + 2:
        return stops, loads

    coordinates = stops[
        ["x", "y"]
    ].to_numpy(dtype=float)

    neighbor_indices = knn_indices(
        coordinates,
        cfg.knn_k,
    )

    locked = stops[
        "is_locked"
    ].astype(bool).to_numpy()

    volumes = stops[
        "total_vol"
    ].to_numpy(dtype=float)

    valid_trucks = set(trucks)

    for _ in range(
        max(1, int(cfg.knn_rounds))
    ):
        changed = False

        assigned = stops[
            "assigned_truck"
        ].astype(object).to_numpy().copy()

        for stop_index in range(number_of_stops):
            if locked[stop_index]:
                continue

            current_truck = assigned[stop_index]

            neighbor_assignments = [
                value
                for value in assigned[
                    neighbor_indices[stop_index]
                ].tolist()
                if value in valid_trucks
            ]

            if not neighbor_assignments:
                continue

            values, counts = np.unique(
                np.asarray(
                    neighbor_assignments,
                    dtype=str,
                ),
                return_counts=True,
            )

            majority_truck = str(
                values[np.argmax(counts)]
            )

            majority_count = int(
                counts.max()
            )

            if majority_truck == current_truck:
                continue

            if (
                majority_count
                < cfg.knn_k
                * cfg.knn_majority
            ):
                continue

            projected_load = (
                loads.get(majority_truck, 0.0)
                + volumes[stop_index]
            )

            allowed_load = (
                targets.get(majority_truck, 0.0)
                + tolerance.get(
                    majority_truck,
                    0.0,
                )
                * cfg.polish_tol_multiplier
            )

            if projected_load > allowed_load:
                continue

            if current_truck in valid_trucks:
                loads[current_truck] = (
                    loads.get(current_truck, 0.0)
                    - volumes[stop_index]
                )

            loads[majority_truck] = projected_load
            assigned[stop_index] = majority_truck
            changed = True

        stops["assigned_truck"] = assigned

        if not changed:
            break

    return stops, loads


def swap_improve(
    stops: pd.DataFrame,
    trucks: List[str],
    targets: Dict[str, float],
    loads: Dict[str, float],
    tolerance: Dict[str, float],
    rounds: int = 3,
    max_pairs_per_combo: int = 60,
) -> Tuple[pd.DataFrame, Dict[str, float]]:
    """
    สลับคู่จุดจอดข้ามรถแบบ 2-opt exchange

    ใช้แก้กรณีที่การย้ายจุดเดี่ยวทำไม่ได้เพราะติดเพดาน
    แต่การสลับสองจุดพร้อมกันช่วยให้ทั้งสองโซนกระชับขึ้น
    """
    stops = stops.copy()
    loads = dict(loads)

    for _ in range(max(1, int(rounds))):
        changed = False
        centers: Dict[str, np.ndarray] = {}

        for truck in trucks:
            group = stops[
                stops["assigned_truck"] == truck
            ]

            if group.empty:
                continue

            weights = np.maximum(
                group["total_vol"].to_numpy(dtype=float),
                1e-9,
            )

            centers[truck] = np.asarray(
                [
                    np.average(
                        group["x"],
                        weights=weights,
                    ),
                    np.average(
                        group["y"],
                        weights=weights,
                    ),
                ],
                dtype=float,
            )

        eligible_center_trucks = [
            truck
            for truck in trucks
            if truck in centers
        ]

        for truck_a, truck_b in combinations(
            eligible_center_trucks,
            2,
        ):
            center_a = centers[truck_a]
            center_b = centers[truck_b]

            group_a = stops[
                (stops["assigned_truck"] == truck_a)
                & (~stops["is_locked"].astype(bool))
            ]

            group_b = stops[
                (stops["assigned_truck"] == truck_b)
                & (~stops["is_locked"].astype(bool))
            ]

            if group_a.empty or group_b.empty:
                continue

            coordinates_a = group_a[
                ["x", "y"]
            ].to_numpy(dtype=float)

            coordinates_b = group_b[
                ["x", "y"]
            ].to_numpy(dtype=float)

            gain_a = (
                np.sqrt(
                    (
                        (
                            coordinates_a
                            - center_a
                        )
                        ** 2
                    ).sum(axis=1)
                )
                - np.sqrt(
                    (
                        (
                            coordinates_a
                            - center_b
                        )
                        ** 2
                    ).sum(axis=1)
                )
            )

            gain_b = (
                np.sqrt(
                    (
                        (
                            coordinates_b
                            - center_b
                        )
                        ** 2
                    ).sum(axis=1)
                )
                - np.sqrt(
                    (
                        (
                            coordinates_b
                            - center_a
                        )
                        ** 2
                    ).sum(axis=1)
                )
            )

            candidate_a = group_a.index[
                np.argsort(-gain_a)
            ][:max_pairs_per_combo]

            candidate_b = group_b.index[
                np.argsort(-gain_b)
            ][:max_pairs_per_combo]

            gain_lookup_a = dict(
                zip(group_a.index, gain_a)
            )

            gain_lookup_b = dict(
                zip(group_b.index, gain_b)
            )

            used_b: set = set()

            for index_a in candidate_a:
                if gain_lookup_a[index_a] <= 0:
                    break

                for index_b in candidate_b:
                    if index_b in used_b:
                        continue

                    if gain_lookup_b[index_b] <= 0:
                        continue

                    if (
                        gain_lookup_a[index_a]
                        + gain_lookup_b[index_b]
                        <= 0
                    ):
                        continue

                    volume_a = float(
                        stops.at[
                            index_a,
                            "total_vol",
                        ]
                    )

                    volume_b = float(
                        stops.at[
                            index_b,
                            "total_vol",
                        ]
                    )

                    new_load_a = (
                        loads.get(truck_a, 0.0)
                        - volume_a
                        + volume_b
                    )

                    new_load_b = (
                        loads.get(truck_b, 0.0)
                        - volume_b
                        + volume_a
                    )

                    limit_a = (
                        targets.get(truck_a, 0.0)
                        + tolerance.get(
                            truck_a,
                            0.0,
                        )
                    )

                    limit_b = (
                        targets.get(truck_b, 0.0)
                        + tolerance.get(
                            truck_b,
                            0.0,
                        )
                    )

                    if new_load_a > limit_a:
                        continue

                    if new_load_b > limit_b:
                        continue

                    stops.at[
                        index_a,
                        "assigned_truck",
                    ] = truck_b

                    stops.at[
                        index_b,
                        "assigned_truck",
                    ] = truck_a

                    loads[truck_a] = new_load_a
                    loads[truck_b] = new_load_b

                    used_b.add(index_b)
                    changed = True
                    break

        if not changed:
            break

    return stops, loads# =====================================================================================
#  SECTION 7 — DAILY LOAD SMOOTHING & KPI HELPERS
# =====================================================================================
def smooth_daily_loads(
    opt: pd.DataFrame,
    cfg: ZoningConfig,
    trucks: List[str],
) -> Tuple[
    pd.DataFrame,
    np.ndarray,
    np.ndarray,
    Dict[str, np.ndarray],
]:
    """
    เกลี่ยวันจัดส่งภายในรถคันเดียวกัน

    เงื่อนไขหลัก:
        - ควบคุมทั้งยอดส่งต่อวันและจำนวนจุดจอดต่อวัน
        - ไม่ย้ายวันของ VIP หากไม่ได้เปิด allow_vip_day_move
        - ไม่ย้ายงานข้ามรถในขั้นตอนนี้
        - ลูกค้าที่มีวันส่งมากกว่า 3 วันจะไม่ถูกย้าย
        - สะสมประวัติการย้ายวันโดยไม่เขียนทับรายการเดิม
    """
    opt = opt.copy().reset_index(drop=True)
    trucks = list(dict.fromkeys(str(t).strip() for t in trucks))

    number_of_rows = len(opt)

    if number_of_rows == 0:
        empty_matrix = np.zeros(
            (0, WORKING_DAYS),
            dtype=float,
        )

        return (
            opt,
            empty_matrix,
            empty_matrix.copy(),
            {
                truck: np.zeros(
                    WORKING_DAYS,
                    dtype=float,
                )
                for truck in trucks
            },
        )

    if "สถานะการย้ายวัน" not in opt.columns:
        opt["สถานะการย้ายวัน"] = "-"

    if "is_vip_locked" not in opt.columns:
        opt["is_vip_locked"] = False

    monthly_volumes = (
        pd.to_numeric(
            opt[cfg.vol_col],
            errors="coerce",
        )
        .fillna(0.0)
        .to_numpy(dtype=float)
    )

    day_map: Dict[int, List[int]] = {}

    for row_index in opt.index:
        days, status = parse_days_from_string(
            opt.at[row_index, cfg.day_col]
        )

        # ใช้ทุกวันเฉพาะตอนคำนวณ เพื่อไม่ให้ระบบหยุดทำงาน
        # แต่เก็บสถานะ unparsed/empty ไว้สำหรับแจ้งเตือนผู้ใช้
        if not days:
            days = list(range(WORKING_DAYS))

        day_map[row_index] = list(
            sorted(set(days))
        )

        opt.at[
            row_index,
            "_day_status",
        ] = status

    def recompute_daily() -> Tuple[
        Dict[str, np.ndarray],
        Dict[str, np.ndarray],
    ]:
        daily_volume = {
            truck: np.zeros(
                WORKING_DAYS,
                dtype=float,
            )
            for truck in trucks
        }

        daily_stop_count = {
            truck: np.zeros(
                WORKING_DAYS,
                dtype=float,
            )
            for truck in trucks
        }

        for row_index in opt.index:
            truck = str(
                opt.at[row_index, "เบอร์รถใหม่"]
            ).strip()

            if truck not in daily_volume:
                continue

            days = day_map[row_index]

            if not days:
                continue

            volume_per_day = (
                monthly_volumes[row_index]
                / len(days)
                / WEEKS_PER_MONTH
            )

            for day in days:
                if not 0 <= day < WORKING_DAYS:
                    continue

                daily_volume[truck][day] += (
                    volume_per_day
                )

                daily_stop_count[truck][day] += 1

        return daily_volume, daily_stop_count

    daily_capacity = max(
        1.0,
        float(cfg.daily_control_cap),
    )

    maximum_stops = max(
        1,
        int(cfg.max_stops_per_day),
    )

    for _ in range(
        max(1, int(cfg.daily_passes))
    ):
        daily_volume, daily_stop_count = (
            recompute_daily()
        )

        changed = False

        for truck in trucks:
            if truck not in daily_volume:
                continue

            # เริ่มแก้จากวันที่มีคะแนนความหนาแน่นสูงที่สุด
            density_score = (
                daily_volume[truck]
                / daily_capacity
                + daily_stop_count[truck]
                / maximum_stops
            )

            source_day_order = np.argsort(
                -density_score
            )

            for source_day in source_day_order:
                source_day = int(source_day)

                volume_overloaded = (
                    daily_volume[truck][source_day]
                    > daily_capacity
                )

                stops_overloaded = (
                    daily_stop_count[truck][source_day]
                    > maximum_stops
                )

                if not (
                    volume_overloaded
                    or stops_overloaded
                ):
                    continue

                destination_score = (
                    daily_volume[truck]
                    / daily_capacity
                    + daily_stop_count[truck]
                    / maximum_stops
                )

                # ห้ามเลือกวันต้นทางเป็นวันปลายทาง
                destination_score = (
                    destination_score.copy()
                )

                destination_score[source_day] = (
                    np.inf
                )

                destination_days = np.argsort(
                    destination_score
                )

                destination_day = None

                for candidate_day in destination_days:
                    candidate_day = int(
                        candidate_day
                    )

                    if not np.isfinite(
                        destination_score[
                            candidate_day
                        ]
                    ):
                        continue

                    if (
                        daily_volume[truck][
                            candidate_day
                        ]
                        >= daily_capacity
                    ):
                        continue

                    if (
                        daily_stop_count[truck][
                            candidate_day
                        ]
                        >= maximum_stops
                    ):
                        continue

                    destination_day = (
                        candidate_day
                    )
                    break

                if destination_day is None:
                    continue

                movable_rows = []

                for row_index in opt.index:
                    assigned_truck = str(
                        opt.at[
                            row_index,
                            "เบอร์รถใหม่",
                        ]
                    ).strip()

                    if assigned_truck != truck:
                        continue

                    if (
                        not cfg.allow_vip_day_move
                        and bool(
                            opt.at[
                                row_index,
                                "is_vip_locked",
                            ]
                        )
                    ):
                        continue

                    current_days = day_map[
                        row_index
                    ]

                    if source_day not in current_days:
                        continue

                    if destination_day in current_days:
                        continue

                    if len(current_days) > 3:
                        continue

                    movable_rows.append(
                        row_index
                    )

                if not movable_rows:
                    continue

                # ย้ายก้อนใหญ่ก่อน เพื่อลดจำนวนครั้งในการโยกวัน
                movable_rows.sort(
                    key=lambda row_index: (
                        -monthly_volumes[
                            row_index
                        ]
                        / max(
                            1,
                            len(
                                day_map[
                                    row_index
                                ]
                            ),
                        )
                    )
                )

                excess_volume = max(
                    0.0,
                    daily_volume[truck][
                        source_day
                    ]
                    - TARGET_DAY_CAP,
                )

                shifted_volume = 0.0

                for row_index in movable_rows:
                    current_days = day_map[
                        row_index
                    ]

                    volume_per_day = (
                        monthly_volumes[row_index]
                        / max(
                            1,
                            len(current_days),
                        )
                        / WEEKS_PER_MONTH
                    )

                    destination_projected_volume = (
                        daily_volume[truck][
                            destination_day
                        ]
                        + volume_per_day
                    )

                    destination_projected_stops = (
                        daily_stop_count[truck][
                            destination_day
                        ]
                        + 1
                    )

                    if (
                        destination_projected_volume
                        > daily_capacity
                    ):
                        continue

                    if (
                        destination_projected_stops
                        > maximum_stops
                    ):
                        continue

                    new_days = [
                        destination_day
                        if day == source_day
                        else day
                        for day in current_days
                    ]

                    new_days = sorted(
                        set(new_days)
                    )

                    if len(new_days) != len(
                        current_days
                    ):
                        continue

                    day_map[row_index] = new_days

                    movement_note = (
                        f"{DAY_SHORT[source_day]}"
                        f"→{DAY_SHORT[destination_day]}"
                    )

                    previous_note = str(
                        opt.at[
                            row_index,
                            "สถานะการย้ายวัน",
                        ]
                    ).strip()

                    if (
                        not previous_note
                        or previous_note.lower()
                        in NO_TRUCK_TOKENS
                    ):
                        opt.at[
                            row_index,
                            "สถานะการย้ายวัน",
                        ] = movement_note
                    else:
                        existing_notes = [
                            note.strip()
                            for note in previous_note.split(
                                ","
                            )
                            if note.strip()
                        ]

                        if (
                            movement_note
                            not in existing_notes
                        ):
                            existing_notes.append(
                                movement_note
                            )

                        opt.at[
                            row_index,
                            "สถานะการย้ายวัน",
                        ] = ", ".join(
                            existing_notes
                        )

                    daily_volume[truck][
                        source_day
                    ] -= volume_per_day

                    daily_volume[truck][
                        destination_day
                    ] += volume_per_day

                    daily_stop_count[truck][
                        source_day
                    ] -= 1

                    daily_stop_count[truck][
                        destination_day
                    ] += 1

                    shifted_volume += (
                        volume_per_day
                    )

                    changed = True

                    volume_overloaded = (
                        daily_volume[truck][
                            source_day
                        ]
                        > daily_capacity
                    )

                    stops_overloaded = (
                        daily_stop_count[truck][
                            source_day
                        ]
                        > maximum_stops
                    )

                    enough_volume_shifted = (
                        shifted_volume
                        >= excess_volume
                    )

                    if (
                        not volume_overloaded
                        and not stops_overloaded
                        and enough_volume_shifted
                    ):
                        break

        if not changed:
            break

    for row_index in opt.index:
        opt.at[
            row_index,
            "วันจัดส่ง(ใหม่)",
        ] = format_days_to_string(
            day_map[row_index]
        )

        opt.at[
            row_index,
            "วันจัดส่ง(ย่อ)",
        ] = format_days_short(
            day_map[row_index]
        )

    daily_matrix = np.zeros(
        (number_of_rows, WORKING_DAYS),
        dtype=float,
    )

    daily_stops_matrix = np.zeros(
        (number_of_rows, WORKING_DAYS),
        dtype=float,
    )

    for row_index in opt.index:
        days = day_map[row_index]

        if not days:
            continue

        volume_per_day = (
            monthly_volumes[row_index]
            / len(days)
            / WEEKS_PER_MONTH
        )

        for day in days:
            daily_matrix[
                row_index,
                day,
            ] = volume_per_day

            daily_stops_matrix[
                row_index,
                day,
            ] = 1.0

    final_daily, _ = recompute_daily()

    return (
        opt,
        daily_matrix,
        daily_stops_matrix,
        final_daily,
    )


def compute_compactness(
    group: pd.DataFrame,
) -> float:
    """
    คำนวณระยะเฉลี่ยจากจุดลูกค้าถึงศูนย์กลางโซน หน่วยเมตร

    ยิ่งค่าต่ำ หมายถึงพื้นที่ของรถคันนั้นยิ่งเกาะกลุ่ม
    """
    if group.empty:
        return 0.0

    coordinates = group[
        ["x", "y"]
    ].to_numpy(dtype=float)

    weights = np.ones(
        len(group),
        dtype=float,
    )

    if "total_vol" in group.columns:
        weights = np.maximum(
            pd.to_numeric(
                group["total_vol"],
                errors="coerce",
            )
            .fillna(0.0)
            .to_numpy(dtype=float),
            1e-9,
        )

    elif len(group.columns):
        possible_volume_columns = [
            column
            for column in group.columns
            if "ยอด" in str(column)
            or "volume" in str(column).lower()
        ]

        if possible_volume_columns:
            weights = np.maximum(
                pd.to_numeric(
                    group[
                        possible_volume_columns[0]
                    ],
                    errors="coerce",
                )
                .fillna(0.0)
                .to_numpy(dtype=float),
                1e-9,
            )

    center = np.average(
        coordinates,
        axis=0,
        weights=weights,
    )

    distances = np.sqrt(
        (
            (
                coordinates
                - center
            )
            ** 2
        ).sum(axis=1)
    )

    return float(
        np.average(
            distances,
            weights=weights,
        )
    )


def calculate_peak_daily_loads(
    data: pd.DataFrame,
    truck_column: str,
    volume_column: str,
    day_column: str,
) -> Dict[str, float]:
    """
    คำนวณโหลดสูงสุดต่อวันของรถแต่ละคัน
    ใช้สำหรับ KPI ก่อนปรับสาย
    """
    output: Dict[str, float] = {}

    if data.empty:
        return output

    for truck, group in data.groupby(
        truck_column,
        dropna=False,
    ):
        truck_id = str(truck).strip()

        if (
            truck_id.lower()
            in NO_TRUCK_TOKENS
        ):
            continue

        daily = np.zeros(
            WORKING_DAYS,
            dtype=float,
        )

        for _, row in group.iterrows():
            days, _ = parse_days_from_string(
                row.get(day_column)
            )

            if not days:
                days = list(
                    range(WORKING_DAYS)
                )

            monthly_volume = pd.to_numeric(
                row.get(volume_column),
                errors="coerce",
            )

            if pd.isna(monthly_volume):
                monthly_volume = 0.0

            volume_per_day = (
                float(monthly_volume)
                / len(days)
                / WEEKS_PER_MONTH
            )

            for day in days:
                daily[day] += volume_per_day

        output[truck_id] = float(
            daily.max()
        )

    return output


# =====================================================================================
#  SECTION 8 — MAIN MULTI-DONOR ZONING ENGINE
# =====================================================================================
def run_multi_donor_zoning(
    df: pd.DataFrame,
    cfg: ZoningConfig,
    target_pcts: Dict[str, float],
    dissolve_trucks: Sequence[str],
    relieve_trucks: Sequence[str],
    new_trucks: Sequence[str],
    manual_locks: Sequence[str],
    road_matrix_getter=None,
) -> ZoningResult:
    """
    ประมวลผลจัดสายส่งใหม่แบบ Multi-Donor

    ขั้นตอน:
        1. ตรวจสอบและเตรียมข้อมูล
        2. สร้างจุดจอดจากพิกัด
        3. ล็อก VIP และ Core
        4. สร้าง seed ของรถเดิมและรถใหม่
        5. จัดสรรตามระยะทางและความจุ
        6. ลด Core Ratio อัตโนมัติเมื่อเข้าเป้าไม่ได้
        7. ขัดผิวโซนและสลับคู่
        8. แมปผลกลับระดับลูกค้า
        9. เกลี่ยวันจัดส่ง
        10. คำนวณ KPI ก่อนและหลัง
    """
    warnings: List[str] = []
    infos: List[str] = []

    if df is None or df.empty:
        raise ValueError(
            "ไม่มีข้อมูลสำหรับประมวลผล"
        )

    opt = df.copy().reset_index(drop=True)

    required_columns = [
        cfg.lat_col,
        cfg.lon_col,
        cfg.vol_col,
        cfg.truck_col,
        cfg.id_col,
        cfg.day_col,
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in opt.columns
    ]

    if missing_columns:
        raise ValueError(
            "ไม่พบคอลัมน์ที่จำเป็น: "
            + ", ".join(
                map(str, missing_columns)
            )
        )

    opt[cfg.lat_col] = pd.to_numeric(
        opt[cfg.lat_col],
        errors="coerce",
    )

    opt[cfg.lon_col] = pd.to_numeric(
        opt[cfg.lon_col],
        errors="coerce",
    )

    opt[cfg.vol_col] = (
        pd.to_numeric(
            opt[cfg.vol_col],
            errors="coerce",
        )
        .fillna(0.0)
        .clip(lower=0.0)
        .astype(float)
    )

    opt[cfg.truck_col] = (
        opt[cfg.truck_col]
        .astype(str)
        .str.strip()
    )

    opt[cfg.id_col] = (
        opt[cfg.id_col]
        .astype(str)
        .str.strip()
    )

    valid_coordinate_mask = (
        opt[cfg.lat_col].notna()
        & opt[cfg.lon_col].notna()
        & opt[cfg.lat_col].between(
            -90.0,
            90.0,
        )
        & opt[cfg.lon_col].between(
            -180.0,
            180.0,
        )
    )

    invalid_coordinate_count = int(
        (~valid_coordinate_mask).sum()
    )

    if invalid_coordinate_count:
        warnings.append(
            f"ตัดข้อมูลพิกัดไม่ถูกต้องออก "
            f"{invalid_coordinate_count:,} รายการ"
        )

        opt = opt[
            valid_coordinate_mask
        ].reset_index(drop=True)

    valid_truck_mask = ~(
        opt[cfg.truck_col]
        .str.lower()
        .isin(NO_TRUCK_TOKENS)
    )

    invalid_truck_count = int(
        (~valid_truck_mask).sum()
    )

    if invalid_truck_count:
        warnings.append(
            f"ตัดข้อมูลเบอร์รถว่างหรือไม่ถูกต้องออก "
            f"{invalid_truck_count:,} รายการ"
        )

        opt = opt[
            valid_truck_mask
        ].reset_index(drop=True)

    if opt.empty:
        raise ValueError(
            "ไม่เหลือข้อมูลที่มีพิกัดและเบอร์รถถูกต้อง"
        )

    all_original_trucks = clean_truck_ids(
        opt[cfg.truck_col].unique()
    )

    dissolve_set = {
        str(truck).strip()
        for truck in dissolve_trucks
        if str(truck).strip()
        in all_original_trucks
    }

    dissolve = [
        truck
        for truck in all_original_trucks
        if truck in dissolve_set
    ]

    kept = [
        truck
        for truck in all_original_trucks
        if truck not in dissolve_set
    ]

    normalized_new_trucks = []

    for truck in new_trucks:
        truck_id = str(truck).strip()

        if (
            not truck_id
            or truck_id.lower()
            in NO_TRUCK_TOKENS
        ):
            continue

        if truck_id in kept:
            continue

        if (
            truck_id
            not in normalized_new_trucks
        ):
            normalized_new_trucks.append(
                truck_id
            )

    active = (
        kept
        + normalized_new_trucks
    )

    if not active:
        raise ValueError(
            "ไม่เหลือรถที่สามารถรับการจัดสรรงานได้"
        )

    targets = {
        truck: max(
            0.0,
            cfg.monthly_capacity
            * float(
                target_pcts.get(
                    truck,
                    0.0,
                )
            )
            / 100.0,
        )
        for truck in active
    }

    tolerance = {
        truck: _tolerance_for(
            truck,
            targets,
            cfg,
        )
        for truck in active
    }

    target_total = float(
        sum(targets.values())
    )

    actual_total = float(
        opt[cfg.vol_col].sum()
    )

    if target_total <= 0:
        raise ValueError(
            "ผลรวมเป้าหมายของรถทุกคันเป็นศูนย์"
        )

    if (
        actual_total
        > target_total
        + sum(tolerance.values())
    ):
        warnings.append(
            f"ยอดรวมจริง {actual_total:,.0f} ถัง/เดือน "
            f"สูงกว่าผลรวมเป้าหมายและค่าเผื่อ "
            f"มีโอกาสเกิด '{OVERFLOW_LABEL}'"
        )

    locked_ids = {
        str(value).strip()
        for value in manual_locks
        if str(value).strip()
    }

    if "VIP_Status" not in opt.columns:
        opt["VIP_Status"] = "ปกติ"

    vip_status = (
        opt["VIP_Status"]
        .astype(str)
        .str.upper()
        .str.strip()
    )

    opt["is_vip_locked"] = (
        vip_status.eq("VIP")
        | opt[cfg.id_col]
        .astype(str)
        .str.strip()
        .isin(locked_ids)
    )

    opt["สถานะการย้ายวัน"] = "-"

    opt["coord_key"] = (
        opt[cfg.lat_col]
        .round(5)
        .astype(str)
        + ","
        + opt[cfg.lon_col]
        .round(5)
        .astype(str)
    )

    projected_x, projected_y, latitude_reference = (
        project_xy(
            opt[cfg.lat_col].to_numpy(
                dtype=float
            ),
            opt[cfg.lon_col].to_numpy(
                dtype=float
            ),
        )
    )

    opt["x"] = projected_x
    opt["y"] = projected_y

    stops = build_stops(
        opt,
        cfg,
    )

    if stops.empty:
        raise ValueError(
            "ไม่สามารถสร้างจุดจอดจากข้อมูลได้"
        )

    biggest_stop_volume = float(
        stops["total_vol"].max()
    )

    maximum_target = (
        max(targets.values())
        if targets
        else 0.0
    )

    maximum_single_stop_limit = max(
        (
            targets.get(truck, 0.0)
            + tolerance.get(truck, 0.0)
            for truck in active
        ),
        default=0.0,
    )

    if (
        maximum_target > 0
        and biggest_stop_volume
        > maximum_single_stop_limit
    ):
        warnings.append(
            f"พบจุดพิกัดเดียวที่มียอดรวม "
            f"{biggest_stop_volume:,.0f} ถัง/เดือน "
            f"มากกว่าความจุสูงสุดที่รถหนึ่งคันรับได้ "
            f"จุดดังกล่าวอาจตกเป็น '{OVERFLOW_LABEL}' "
            f"กรุณาตรวจสอบพิกัด GPS ที่ซ้ำกัน"
        )

    volume_by_original_truck = (
        stops.groupby(
            "orig_truck"
        )["total_vol"]
        .sum()
        .to_dict()
    )

    relieve_set = {
        str(truck).strip()
        for truck in relieve_trucks
    }

    ratio_override: Dict[str, float] = {}

    for truck in relieve_set:
        current_volume = float(
            volume_by_original_truck.get(
                truck,
                0.0,
            )
        )

        if (
            current_volume > 0
            and truck in targets
        ):
            ratio_override[truck] = max(
                0.0,
                min(
                    100.0,
                    targets[truck]
                    / current_volume
                    * 100.0
                    * 0.92,
                ),
            )

    core_eligible = [
        truck
        for truck in kept
        if truck not in dissolve_set
    ]

    seeds: Dict[
        str,
        Tuple[float, float],
    ] = {}

    for truck in kept:
        group = stops[
            stops["orig_truck"] == truck
        ]

        if group.empty:
            continue

        weights = np.maximum(
            group["total_vol"]
            .to_numpy(dtype=float),
            1e-9,
        )

        seeds[truck] = (
            float(
                np.average(
                    group["x"],
                    weights=weights,
                )
            ),
            float(
                np.average(
                    group["y"],
                    weights=weights,
                )
            ),
        )

    global_weights = np.maximum(
        stops["total_vol"]
        .to_numpy(dtype=float),
        1e-9,
    )

    global_x = float(
        np.average(
            stops["x"],
            weights=global_weights,
        )
    )

    global_y = float(
        np.average(
            stops["y"],
            weights=global_weights,
        )
    )

    if normalized_new_trucks:
        initial_core_keys = compute_core_keys(
            stops,
            cfg.core_ratio,
            core_eligible,
            ratio_override,
        )

        seed_pool = stops[
            ~stops["coord_key"].isin(
                initial_core_keys
            )
        ]

        if seed_pool.empty:
            seed_pool = stops

        new_centers = kmeans_seeds(
            seed_pool[
                ["x", "y"]
            ].to_numpy(dtype=float),
            seed_pool[
                "total_vol"
            ].to_numpy(dtype=float),
            len(normalized_new_trucks),
        )

        if len(new_centers) == 0:
            new_centers = np.asarray(
                [[global_x, global_y]],
                dtype=float,
            )

        for index, truck in enumerate(
            normalized_new_trucks
        ):
            center_index = min(
                index,
                len(new_centers) - 1,
            )

            seeds[truck] = (
                float(
                    new_centers[
                        center_index,
                        0,
                    ]
                ),
                float(
                    new_centers[
                        center_index,
                        1,
                    ]
                ),
            )

    road_matrix = None

    if (
        cfg.use_road
        and road_matrix_getter is not None
        and active
    ):
        destination_coordinates = []

        cosine_scale = math.cos(
            math.radians(
                latitude_reference
            )
        )

        for truck in active:
            seed_x, seed_y = seeds.get(
                truck,
                (global_x, global_y),
            )

            destination_latitude = (
                math.degrees(
                    seed_y
                    / EARTH_RADIUS_M
                )
            )

            if abs(cosine_scale) <= 1e-12:
                destination_longitude = (
                    float(
                        opt[cfg.lon_col].mean()
                    )
                )
            else:
                destination_longitude = (
                    math.degrees(
                        seed_x
                        / (
                            EARTH_RADIUS_M
                            * cosine_scale
                        )
                    )
                )

            destination_coordinates.append(
                (
                    destination_latitude,
                    destination_longitude,
                )
            )

        source_coordinates = list(
            zip(
                stops["lat"].astype(
                    float
                ).tolist(),
                stops["lon"].astype(
                    float
                ).tolist(),
            )
        )

        road_matrix, road_error = (
            road_matrix_getter(
                tuple(source_coordinates),
                tuple(
                    destination_coordinates
                ),
            )
        )

        if road_matrix is None:
            warnings.append(
                "เรียก API ระยะทางถนนจริงไม่สำเร็จ "
                f"({road_error}) "
                "ระบบใช้ระยะทางเส้นตรงแทนในรอบนี้"
            )

        else:
            road_matrix = np.asarray(
                road_matrix,
                dtype=float,
            )

            expected_shape = (
                len(stops),
                len(active),
            )

            if (
                road_matrix.shape
                != expected_shape
            ):
                warnings.append(
                    "Road Distance Matrix มีขนาดไม่ถูกต้อง "
                    f"(ได้รับ {road_matrix.shape}, "
                    f"คาดว่า {expected_shape}) "
                    "ระบบใช้ระยะทางเส้นตรงแทน"
                )

                road_matrix = None

    def run_single_pass(
        core_ratio: float,
    ) -> Tuple[
        pd.DataFrame,
        Dict[str, float],
    ]:
        candidate_stops = stops.copy()

        core_keys = compute_core_keys(
            candidate_stops,
            core_ratio,
            core_eligible,
            ratio_override,
        )

        candidate_stops[
            "is_core_locked"
        ] = candidate_stops[
            "coord_key"
        ].isin(core_keys)

        candidate_stops[
            "is_locked"
        ] = (
            candidate_stops[
                "has_vip_lock"
            ].astype(bool)
            | candidate_stops[
                "is_core_locked"
            ].astype(bool)
        )

        candidate_stops[
            "assigned_truck"
        ] = None

        for stop_index, row in (
            candidate_stops.iterrows()
        ):
            original_truck = str(
                row["orig_truck"]
            ).strip()

            if (
                bool(row["is_locked"])
                and original_truck in active
            ):
                candidate_stops.at[
                    stop_index,
                    "assigned_truck",
                ] = original_truck

        assignment, pass_loads = (
            _assign_capacitated(
                candidate_stops,
                active,
                targets,
                tolerance,
                seeds,
                road_matrix,
            )
        )

        candidate_stops[
            "assigned_truck"
        ] = [
            active[truck_index]
            if truck_index >= 0
            else OVERFLOW_LABEL
            for truck_index in assignment
        ]

        # หากรถเดิมถูกยุบ จุด VIP/Core ของรถนั้นต้องถูกปลดล็อก
        # เพราะไม่สามารถคงอยู่กับรถเดิมได้
        inactive_original_mask = ~(
            candidate_stops[
                "orig_truck"
            ].isin(active)
        )

        candidate_stops.loc[
            candidate_stops[
                "is_locked"
            ]
            & inactive_original_mask,
            "is_locked",
        ] = False

        return (
            candidate_stops,
            pass_loads,
        )

    current_ratio = max(
        0.0,
        min(
            100.0,
            float(cfg.core_ratio),
        ),
    )

    minimum_ratio = max(
        0.0,
        min(
            current_ratio,
            float(cfg.core_floor),
        ),
    )

    core_step = max(
        1.0,
        float(cfg.core_step),
    )

    best_result = None

    while True:
        candidate_stops, candidate_loads = (
            run_single_pass(
                current_ratio
            )
        )

        total_violation = 0.0

        for truck in active:
            target = targets.get(
                truck,
                0.0,
            )

            if target <= 0:
                continue

            actual = candidate_loads.get(
                truck,
                0.0,
            )

            violation = max(
                0.0,
                abs(actual - target)
                - tolerance.get(
                    truck,
                    0.0,
                ),
            )

            total_violation += violation

        overflow_volume = float(
            candidate_stops.loc[
                candidate_stops[
                    "assigned_truck"
                ]
                == OVERFLOW_LABEL,
                "total_vol",
            ].sum()
        )

        objective_score = (
            total_violation
            + overflow_volume * 2.0
        )

        if (
            best_result is None
            or objective_score
            < best_result[3]
        ):
            best_result = (
                candidate_stops,
                candidate_loads,
                current_ratio,
                objective_score,
            )

        if (
            objective_score <= 1e-6
            or current_ratio
            <= minimum_ratio
        ):
            break

        next_ratio = max(
            minimum_ratio,
            current_ratio - core_step,
        )

        if abs(
            next_ratio
            - current_ratio
        ) <= 1e-9:
            break

        current_ratio = next_ratio

    if best_result is None:
        raise RuntimeError(
            "ระบบไม่สามารถสร้างผลการจัดสรรได้"
        )

    (
        assigned_stops,
        loads,
        ratio_used,
        _,
    ) = best_result

    if ratio_used < cfg.core_ratio:
        infos.append(
            "ระบบลดสัดส่วนแกนกลางที่ล็อก "
            f"จาก {cfg.core_ratio:.0f}% "
            f"เหลือ {ratio_used:.0f}% อัตโนมัติ "
            "เพื่อให้ยอดจริงเข้าใกล้เป้าหมาย"
        )

    if cfg.enable_stray_cleanup:
        assigned_stops, loads = (
            cleanup_stray_points(
                assigned_stops,
                active,
                targets,
                loads,
                tolerance,
                cfg.polish_tol_multiplier,
            )
        )

    if cfg.enable_majority_vote:
        assigned_stops, loads = (
            majority_vote_smoothing(
                assigned_stops,
                active,
                targets,
                loads,
                tolerance,
                cfg,
            )
        )

    if cfg.enable_swap:
        assigned_stops, loads = (
            swap_improve(
                assigned_stops,
                active,
                targets,
                loads,
                tolerance,
                cfg.swap_rounds,
            )
        )

    truck_mapping = dict(
        zip(
            assigned_stops[
                "coord_key"
            ],
            assigned_stops[
                "assigned_truck"
            ],
        )
    )

    core_mapping = dict(
        zip(
            assigned_stops[
                "coord_key"
            ],
            assigned_stops[
                "is_core_locked"
            ],
        )
    )

    opt["เบอร์รถใหม่"] = (
        opt["coord_key"]
        .map(truck_mapping)
        .fillna(OVERFLOW_LABEL)
        .astype(str)
    )

    opt["is_core_locked"] = (
        opt["coord_key"]
        .map(core_mapping)
        .fillna(False)
        .astype(bool)
    )

    opt["is_locked"] = (
        opt["is_vip_locked"].astype(bool)
        | opt["is_core_locked"].astype(bool)
    )

    original_truck_series = (
        opt[cfg.truck_col]
        .astype(str)
        .str.strip()
    )

    new_truck_series = (
        opt["เบอร์รถใหม่"]
        .astype(str)
        .str.strip()
    )

    same_truck_mask = (
        original_truck_series
        == new_truck_series
    )

    opt["สถานะ"] = np.where(
        same_truck_mask,
        "คงเดิม",
        "ย้ายไปสาย "
        + new_truck_series,
    )

    opt.loc[
        opt["is_locked"]
        & same_truck_mask,
        "สถานะ",
    ] = "คงเดิม 🔒"

    (
        opt,
        daily_matrix,
        daily_stops_matrix,
        final_daily,
    ) = smooth_daily_loads(
        opt,
        cfg,
        active,
    )

    # -------------------------------------------------------------------------
    # KPI: ความกระชับของโซนก่อนและหลัง
    # -------------------------------------------------------------------------
    compactness_before_values = []

    for _, group in opt.groupby(
        cfg.truck_col
    ):
        compactness_before_values.append(
            compute_compactness(group)
        )

    compactness_after_values = []

    for truck, group in opt.groupby(
        "เบอร์รถใหม่"
    ):
        if truck == OVERFLOW_LABEL:
            continue

        compactness_after_values.append(
            compute_compactness(group)
        )

    compactness_before = (
        float(
            np.mean(
                compactness_before_values
            )
        )
        if compactness_before_values
        else 0.0
    )

    compactness_after = (
        float(
            np.mean(
                compactness_after_values
            )
        )
        if compactness_after_values
        else 0.0
    )

    peak_before = calculate_peak_daily_loads(
        opt,
        cfg.truck_col,
        cfg.vol_col,
        cfg.day_col,
    )

    peak_after = {
        truck: float(
            daily_values.max()
        )
        for truck, daily_values
        in final_daily.items()
    }

    moved_mask = (
        original_truck_series
        != new_truck_series
    )

    moved_customer_count = int(
        moved_mask.sum()
    )

    moved_volume = float(
        opt.loc[
            moved_mask,
            cfg.vol_col,
        ].sum()
    )

    metrics = {
        "compact_before_km": (
            compactness_before / 1000.0
        ),
        "compact_after_km": (
            compactness_after / 1000.0
        ),
        "over_before": int(
            sum(
                1
                for value in peak_before.values()
                if value
                > cfg.daily_control_cap
            )
        ),
        "over_after": int(
            sum(
                1
                for value in peak_after.values()
                if value
                > cfg.daily_control_cap
            )
        ),
        "peak_before": (
            max(peak_before.values())
            if peak_before
            else 0.0
        ),
        "peak_after": (
            max(peak_after.values())
            if peak_after
            else 0.0
        ),
        "moved_cust": moved_customer_count,
        "moved_pct": (
            moved_customer_count
            / max(1, len(opt))
            * 100.0
        ),
        "moved_vol": moved_volume,
        "std_before": (
            float(
                np.std(
                    list(
                        peak_before.values()
                    )
                )
            )
            if peak_before
            else 0.0
        ),
        "std_after": (
            float(
                np.std(
                    list(
                        peak_after.values()
                    )
                )
            )
            if peak_after
            else 0.0
        ),
    }

    unreadable_day_count = int(
        (
            opt["_day_status"]
            != "ok"
        ).sum()
    )

    if unreadable_day_count:
        warnings.append(
            f"อ่านค่าวันจัดส่งไม่ได้หรือเป็นค่าว่าง "
            f"{unreadable_day_count:,} รายการ "
            "ระบบใช้ จ-ส สำหรับการคำนวณรายการเหล่านี้ "
            "กรุณาตรวจสอบข้อมูลต้นทาง"
        )

    overflow_stop_count = int(
        (
            assigned_stops[
                "assigned_truck"
            ]
            == OVERFLOW_LABEL
        ).sum()
    )

    if overflow_stop_count:
        overflow_stop_volume = float(
            assigned_stops.loc[
                assigned_stops[
                    "assigned_truck"
                ]
                == OVERFLOW_LABEL,
                "total_vol",
            ].sum()
        )

        warnings.append(
            f"มีจุดจอดที่ยังจัดสรรไม่ได้ "
            f"{overflow_stop_count:,} จุด "
            f"รวม {overflow_stop_volume:,.0f} ถัง/เดือน"
        )

    return ZoningResult(
        result_df=opt,
        stops_df=assigned_stops,
        daily_matrix=daily_matrix,
        daily_stops=daily_stops_matrix,
        final_daily=final_daily,
        targets=targets,
        loads=loads,
        core_ratio_used=float(
            ratio_used
        ),
        metrics=metrics,
        warnings=warnings,
        infos=infos,
    )# =====================================================================================
#  SECTION 7 (UI) — UI THEME
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
    st.warning("⚠️ ไม่พบไลบรารี `scipy` — ระบบจะใช้โหมดคำนวณสำรองซึ่งช้ากว่ามาก แนะนำติดตั้งด้วย `pip install scipy`")


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
                        max_stops_per_day=int(max_stops_day))# =====================================================================================
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
st.sidebar.caption("เลือกรถที่ต้องการยุบหรือดึงงานออก")

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
    st.sidebar.error(f"🚨 ความจุไม่พอ ขาดอีก {leftover_probe:,.0f} ถัง/เดือน — เพิ่มรถใหม่อีก **{need} คัน**")
else:
    if new_trucks:
        st.sidebar.success(f"✅ ความจุเพียงพอ (รถใหม่ {len(new_trucks)} คัน)")

active_trucks = kept_trucks + new_trucks
if not active_trucks:
    st.error("❌ ไม่เหลือรถสำหรับจัดสรรงาน")
    st.stop()

# =====================================================================================
#  SECTION 12 — TARGET SLIDERS
# =====================================================================================
st.sidebar.markdown("---")
st.sidebar.markdown("### 🎛️ 5. เป้าหมายรายคัน (%)")
fingerprint = "|".join([sheet_url, sheet_gid, vol_col, truck_col, day_col, str(sorted(dissolve_trucks)), str(sorted(relieve_trucks)), str(new_trucks), f"{monthly_cap}", f"{daily_cap}"])

if st.sidebar.button("🔄 คำนวณเป้าหมายอัตโนมัติ"):
    st.session_state.pop('slider_fp', None)
    reset_results()

if st.session_state.get('slider_fp') != fingerprint:
    for k in [k for k in list(st.session_state.keys()) if k.startswith('slider_') or k.startswith('lock_')]: del st.session_state[k]
    tgt_units, _ = compute_default_targets(vol_by_truck_all, dissolve_trucks, kept_trucks, new_trucks, cap_units)
    st.session_state.truck_pcts = {t: float(round(max(0.0, min(200.0, tgt_units.get(t, 0.0) / monthly_cap * 100)), 1)) for t in active_trucks}
    for t in active_trucks: st.session_state[f"slider_{t}"] = st.session_state.truck_pcts[t]
    st.session_state['slider_fp'] = fingerprint

def on_slider_change(changed: str):
    new_val = max(0.0, min(200.0, st.session_state.get(f"slider_{changed}", 0.0)))
    old = st.session_state.truck_pcts.get(changed, new_val)
    diff = new_val - old
    if abs(diff) < 0.01: return
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
    with c2: st.checkbox("🔒", key=f"lock_{t}", on_change=reset_results)
    with c1:
        v = st.slider(f"{'🆕 ' if t in new_trucks else ''}รถ {t} (%)", 0.0, 200.0, step=0.1, key=f"slider_{t}", on_change=on_slider_change, args=(t,))
        target_pcts[t] = v
        st.session_state.truck_pcts[t] = v

# =====================================================================================
#  SECTION 13 — ADVANCED RULES
# =====================================================================================
st.sidebar.markdown("---")
st.sidebar.markdown("### 🔒 6. ล็อก Key Account & กฎ")
manual_vips = st.sidebar.multiselect("รหัสลูกค้าที่ห้ามย้ายสาย", options=df[id_col].unique().tolist(), default=[], on_change=reset_results)
core_ratio_pct = st.sidebar.slider("สัดส่วนแกนกลางที่ล็อก (Core %)", 0, 100, 65, 5, on_change=reset_results)
tol_pct = st.sidebar.number_input("ค่าเผื่อเป้าหมาย (%)", 0.0, 50.0, 5.0, 0.5, on_change=reset_results)
use_road = st.sidebar.checkbox("ใช้ระยะทางถนนจริง", False, on_change=reset_results)

cfg = ZoningConfig(lat_col=lat_col, lon_col=lon_col, vol_col=vol_col, truck_col=truck_col, id_col=id_col, day_col=day_col, name_col=name_col, monthly_capacity=monthly_cap, daily_control_cap=daily_cap, max_stops_per_day=int(max_stops_day), core_ratio=float(core_ratio_pct), tol_pct=float(tol_pct), use_road=use_road)

# =====================================================================================
#  SECTION 14 — EXECUTE
# =====================================================================================
if st.sidebar.button("🚀 ประมวลผลจัดสายส่งใหม่", use_container_width=True):
    ph = st.empty()
    show_loader(ph, "กำลังคำนวณ... 💧")
    res = run_multi_donor_zoning(df, cfg, target_pcts, dissolve_trucks, relieve_trucks, new_trucks, manual_vips)
    st.session_state['result'] = res
    st.session_state['zoning_cfg_used'] = cfg
    ph.empty()

if 'result' in st.session_state:
    res = st.session_state['result']
    rdf = res.result_df
    st.markdown("## 📈 ตัวชี้วัดผลลัพธ์")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("รถเกินเพดาน", f"{int(res.metrics['over_after'])} คัน", delta=f"{int(res.metrics['over_after']-res.metrics['over_before']):+d}")
    k2.metric("โหลดสูงสุด", f"{res.metrics['peak_after']:,.0f} ถัง/วัน")
    k3.metric("ความกระชับ", f"{res.metrics['compact_after_km']:.2f} กม.")
    k4.metric("ลูกค้าที่ย้าย", f"{int(res.metrics['moved_cust']):,}")
    st.dataframe(rdf, use_container_width=True)
    st.download_button("📥 ดาวน์โหลดผลลัพธ์", rdf.to_csv(index=False), 'result.csv', 'text/csv', use_container_width=True)
