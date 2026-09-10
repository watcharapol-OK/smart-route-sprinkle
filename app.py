from __future__ import annotations
import base64, json, math, re, time
from dataclasses import dataclass, field
from itertools import combinations
from typing import Dict, List, Optional, Sequence, Tuple
import numpy as np, pandas as pd
import streamlit as st, streamlit.components.v1 as components
import folium
from folium import plugins
try:
    from scipy.spatial import cKDTree
    HAS_SCIPY = True
except: HAS_SCIPY = False

# --- CONFIG & CONSTANTS ---
WORKING_DAYS, WEEKS_PER_MONTH = 6, 4.333
DEFAULT_MONTHLY_CAPACITY, DEFAULT_DAILY_CONTROL_CAP, DEFAULT_MAX_STOPS_PER_DAY = 4160.0, 156.0, 90
OVERFLOW_LABEL = 'ส่วนเกิน (Overflow)'
NO_TRUCK_TOKENS = {'', 'nan', 'none', 'null', '-', 'ไม่ระบุ', 'na', 'n/a'}
DAY_NAMES = {0: 'จันทร์', 1: 'อังคาร', 2: 'พุธ', 3: 'พฤหัสบดี', 4: 'ศุกร์', 5: 'เสาร์'}
DAY_SHORT = {0: 'จ', 1: 'อ', 2: 'พ', 3: 'พฤ', 4: 'ศ', 5: 'ส'}
C_TEXT, C_GOLD = '#E8EEF7', '#FFD166'

# --- ENGINE HELPER FUNCTIONS ---
def parse_days_from_string(val_str) -> Tuple[List[int], str]:
    raw = '' if val_str is None else str(val_str)
    val = raw.strip().lower().replace(' ', '')
    if val in NO_TRUCK_TOKENS: return [], 'empty'
    if any(tok in val for tok in ('ทุกวัน', 'จ-ส', 'จันทร์-เสาร์')): return list(range(6)), 'ok'
    days = set()
    tokens = [('จันทร์', 0), ('อังคาร', 1), ('พฤหัสบดี', 3), ('พฤหัส', 3), ('พุธ', 2), ('ศุกร์', 4), ('เสาร์', 5), ('จ', 0), ('อ', 1), ('พ', 2), ('ศ', 4), ('ส', 5)]
    for tok in re.split(r'[,\|/\+\-\s;]+', val):
        tok = tok.strip('.').strip()
        if not tok: continue
        if tok.isdigit():
            n = int(tok)
            if 1 <= n <= 6: days.add(n - 1)
            continue
        for name, d in tokens:
            if name in tok: days.add(d); break
    return (sorted(days), 'ok') if days else ([], 'unparsed')

def project_xy(lat, lon, lat0=None):
    lat, lon = np.asarray(lat, dtype=float), np.asarray(lon, dtype=float)
    if lat0 is None: lat0 = float(np.nanmean(lat))
    k = math.cos(math.radians(lat0))
    return np.radians(lon) * 6371008.8 * k, np.radians(lat) * 6371008.8, lat0

@dataclass
class ZoningConfig:
    lat_col: str; lon_col: str; vol_col: str; truck_col: str; id_col: str; day_col: str; name_col: Optional[str] = None
    monthly_capacity: float = 4160.0; daily_control_cap: float = 156.0; max_stops_per_day: int = 90
    core_ratio: float = 65.0; tol_pct: float = 5.0; tol_mode: str = 'target'; knn_k: int = 8
    enable_stray_cleanup: bool = True; enable_majority_vote: bool = True; enable_swap: bool = True
    swap_rounds: int = 3; allow_vip_day_move: bool = False; daily_passes: int = 12
    daily_safety_buffer: float = 4.0; use_road: bool = False; road_provider: str = 'osrm'
    osrm_url: str = 'https://router.project-osrm.org'; gmaps_key: str = ''

@dataclass
class ZoningResult:
    result_df: pd.DataFrame; stops_df: pd.DataFrame; daily_matrix: np.ndarray; daily_stops: np.ndarray
    final_daily: Dict[str, np.ndarray]; targets: Dict[str, float]; loads: Dict[str, float]
    core_ratio_used: float; metrics: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list); infos: List[str] = field(default_factory=list)# =====================================================================================
#  ส่วนที่ 2: Zoning Engine Core (วางต่อจากส่วนที่ 1)
# =====================================================================================

def build_stops(df, cfg):
    df['coord_key'] = df[cfg.lat_col].round(5).astype(str) + "," + df[cfg.lon_col].round(5).astype(str)
    x, y, _ = project_xy(df[cfg.lat_col].to_numpy(), df[cfg.lon_col].to_numpy())
    df['x'], df['y'] = x, y
    return df.groupby('coord_key').agg(
        lat=(cfg.lat_col, 'first'), lon=(cfg.lon_col, 'first'), x=('x', 'first'), y=('y', 'first'),
        total_vol=(cfg.vol_col, 'sum'), orig_truck=(cfg.truck_col, 'first'), has_vip_lock=('is_vip_locked', 'any')
    ).reset_index()

def _assign_capacitated(stops, trucks, targets, tol, seeds, road):
    xy, vol = stops[['x', 'y']].to_numpy(dtype=float), stops['total_vol'].to_numpy(dtype=float)
    tidx = {t: i for i, t in enumerate(trucks)}
    assigned = np.full(len(stops), -1, dtype=int)
    loads = {t: 0.0 for t in trucks}
    
    # Greedy Assignment
    for i in range(len(stops)):
        best_t, min_d = None, float('inf')
        for t in trucks:
            dist = np.sqrt(((xy[i] - seeds[t])**2).sum())
            if loads[t] + vol[i] <= targets.get(t, 0.0) + tol.get(t, 0.0):
                if dist < min_d: min_d, best_t = dist, t
        if best_t:
            assigned[i] = tidx[best_t]
            loads[best_t] += vol[i]
    return assigned, loads

def run_multi_donor_zoning(df, cfg, target_pcts, dissolve_trucks, relieve_trucks, new_trucks, manual_locks):
    # Setup
    all_orig = sorted(set(df[cfg.truck_col].unique()))
    active = [t for t in all_orig if t not in dissolve_trucks] + new_trucks
    targets = {t: cfg.monthly_capacity * (float(target_pcts.get(t, 0.0)) / 100.0) for t in active}
    tol = {t: (cfg.tol_pct / 100.0) * cfg.monthly_capacity for t in active}
    
    # Process
    df['is_vip_locked'] = False # Placeholder
    stops = build_stops(df, cfg)
    stops['is_locked'] = stops['has_vip_lock']
    stops['assigned_truck'] = None
    
    seeds = {t: (stops[stops['orig_truck']==t]['x'].mean(), stops[stops['orig_truck']==t]['y'].mean()) 
             for t in active if t in stops['orig_truck'].values}
    
    a, ld = _assign_capacitated(stops, active, targets, tol, seeds, None)
    stops['assigned_truck'] = [active[k] if k >= 0 else OVERFLOW_LABEL for k in a]
    
    # Map back
    m = dict(zip(stops['coord_key'], stops['assigned_truck']))
    df['เบอร์รถใหม่'] = df['coord_key'].map(m).fillna(OVERFLOW_LABEL)
    
    return ZoningResult(df, stops, np.array([]), np.array([]), {}, targets, ld, 0.0)# =====================================================================================
#  ส่วนที่ 3: UI Dashboard & Main Execution (วางต่อจากส่วนที่ 2)
# =====================================================================================

def main():
    st.markdown("""
        <style>
        .stApp { background: linear-gradient(135deg, #050B18 0%, #0F2A4A 100%); color: #E8EEF7; }
        .stMetric { background: rgba(255,255,255,0.05); padding: 15px; border-radius: 10px; }
        </style>
    """, unsafe_allow_html=True)

    st.title("🚛 Smart Route Rebalancer v3.0 (Official)")

    # Sidebar Inputs
    with st.sidebar:
        st.header("⚙️ ตั้งค่าข้อมูล")
        sheet_url = st.text_input("🔗 ลิงก์ Google Sheets")
        if sheet_url:
            try:
                df = pd.read_csv(sheet_url.replace('/edit#gid=', '/export?format=csv&gid='))
                st.success("✅ โหลดข้อมูลสำเร็จ")
                
                cols = df.columns.tolist()
                vol_col = st.selectbox("เลือกคอลัมน์ยอด", cols)
                truck_col = st.selectbox("เลือกคอลัมน์รถ", cols)
                lat_col = st.selectbox("เลือกคอลัมน์ละติจูด", cols)
                lon_col = st.selectbox("เลือกคอลัมน์ลองจิจูด", cols)
                day_col = st.selectbox("เลือกคอลัมน์วัน", cols)
                id_col = st.selectbox("เลือกรหัสลูกค้า", cols)
                
                cfg = ZoningConfig(lat_col, lon_col, vol_col, truck_col, id_col, day_col)
                
                if st.button("🚀 ประมวลผลและกระจายงาน"):
                    # เตรียมข้อมูล
                    trucks = clean_truck_ids(df[truck_col].unique())
                    targets = {t: cfg.monthly_capacity / len(trucks) for t in trucks}
                    
                    # รัน Engine
                    res = run_multi_donor_zoning(df, cfg, targets, [], [], [], [])
                    
                    # แสดงผลแดชบอร์ด
                    st.subheader("📊 ผลลัพธ์การจัดสรร")
                    res_df = res.result_df
                    st.dataframe(res_df, use_container_width=True)
                    
                    # ปุ่มดาวน์โหลด
                    st.download_button("📥 ดาวน์โหลดผลลัพธ์ CSV", 
                                       res_df.to_csv(index=False), 
                                       "result.csv", "text/csv")
            except Exception as e:
                st.error(f"❌ เกิดข้อผิดพลาด: {e}")

if __name__ == "__main__":
    main()
