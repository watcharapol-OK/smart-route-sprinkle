import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import folium
from folium import plugins
import re
import math
import time
import base64

st.set_page_config(page_title="Smart Route Rebalancer", layout="wide", initial_sidebar_state="expanded")

def reset_results():
    keys_to_clear = ['result_df', 'daily_matrix', 'applied_truck_recs']
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]

# -------------------------------------------------------------
# 💎 CLEAN HARD-CAP & CONTIGUOUS ZONING ARCHITECTURE
# -------------------------------------------------------------
st.markdown('''
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');
        
        html, body, [class*="css"], p, span, label, div, small, li, a, h1, h2, h3, h4, h5, h6 { 
            font-family: 'Sarabun', sans-serif !important; 
            color: #FFFFFF !important;
            font-weight: 400;
        }

        .stApp { 
            background: linear-gradient(135deg, #000814 0%, #001D3D 45%, #003566 100%) !important;
            background-attachment: fixed;
        }

        h1, h2, h3, h4, h5, h6 { 
            color: #FFD700 !important; 
            font-weight: 700 !important; 
            letter-spacing: 0.5px;
            text-shadow: 0 2px 4px rgba(0,0,0,0.6);
        }
        
        .stMarkdown p, span, div[data-testid="stMarkdownContainer"] p, [data-testid="stCaptionContainer"], .stCaption {
            color: #F1F5F9 !important;
            opacity: 1 !important;
            font-weight: 400 !important;
        }

        [data-testid="stSidebar"] { 
            background: rgba(0, 13, 26, 0.55) !important; 
            backdrop-filter: blur(25px);
            -webkit-backdrop-filter: blur(25px);
            border-right: 1px solid rgba(255, 255, 255, 0.15); 
        }
        [data-testid="stSidebar"] * { color: #FFFFFF !important; }
        [data-testid="stSidebar"] label, [data-testid="stSidebar"] .stMarkdown p {
            color: #F3E5AB !important;
            font-weight: 600 !important;
        }
        [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { 
            color: #FFD700 !important; 
            border-bottom: 1px solid rgba(212, 175, 55, 0.3);
            padding-bottom: 8px;
        }

        div[data-baseweb="select"] > div, input { 
            background: rgba(0, 30, 60, 0.3) !important; 
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.2) !important; 
            color: #FFFFFF !important;
            border-radius: 12px !important;
            font-weight: 500;
        }
        input::placeholder { color: #CBD5E1 !important; opacity: 1 !important; }
        input:focus, div[data-baseweb="select"] > div:focus-within {
            border-color: #FFD700 !important;
            box-shadow: 0 0 15px rgba(255, 215, 0, 0.35) !important;
        }

        div[role="listbox"], ul[role="listbox"], div[data-baseweb="menu"], [data-baseweb="select-dropdown"] {
            background: rgba(248, 250, 252, 0.92) !important;
            backdrop-filter: blur(16px);
            border: 1px solid #D4AF37 !important;
            border-radius: 12px !important;
            box-shadow: 0 12px 32px rgba(0, 0, 0, 0.4) !important;
        }
        div[role="option"], ul[role="listbox"] > li {
            color: #0F172A !important;
            font-weight: 500 !important;
            padding: 10px 16px !important;
            border-bottom: 1px solid #E2E8F0 !important;
        }
        div[role="option"] > div, div[role="option"] span { color: #0F172A !important; font-weight: 500 !important; }
        div[role="option"]:hover { background-color: #FFF8E1 !important; color: #000B18 !important; }
        div[role="option"]:hover div, div[role="option"]:hover span { color: #000B18 !important; }
        div[role="option"][aria-selected="true"] { background-color: #FFD700 !important; color: #000B18 !important; }
        div[role="option"][aria-selected="true"] div, div[role="option"][aria-selected="true"] span { color: #000B18 !important; font-weight: 700 !important; }

        .stButton>button { 
            background: linear-gradient(135deg, #D4AF37 0%, #AA8C2C 100%) !important; 
            color: #000B18 !important; 
            border: none !important; 
            border-radius: 10px; 
            font-weight: 700; 
            padding: 0.6rem 2rem; 
            width: 100%; 
            box-shadow: 0 4px 15px rgba(212, 175, 55, 0.4);
            transition: all 0.3s ease; 
        }
        .stButton>button:hover { 
            background: linear-gradient(135deg, #F3E5AB 0%, #D4AF37 100%) !important; 
            box-shadow: 0 6px 20px rgba(255, 215, 0, 0.6); 
            transform: translateY(-2px); 
        }

        .stDataFrame { 
            background: rgba(0, 24, 48, 0.25) !important; 
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            padding: 1.2rem; 
            border-radius: 16px; 
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3); 
            border: 1px solid rgba(255, 255, 255, 0.15); 
            border-top: 3px solid #D4AF37;
        }
        .stDataFrame td, .stDataFrame th, .stDataFrame div { color: #0F172A !important; font-weight: 500 !important; }

        .stSpinner > div > div { display: none !important; }
        @keyframes moveRoad { 0% { background-position: 0 0; } 100% { background-position: -120px 0; } }
        @keyframes truckVibration { 0% { transform: translateY(0px); } 50% { transform: translateY(-2px); } 100% { transform: translateY(0px); } }

        .custom-truck-loader { 
            text-align: center; 
            padding: 2.2rem; 
            color: #FFD700; 
            font-weight: bold; 
            font-size: 1.2rem; 
            border-radius: 16px; 
            background: rgba(0, 24, 48, 0.5); 
            backdrop-filter: blur(20px);
            border: 1px solid rgba(255, 255, 255, 0.18); 
            margin-bottom: 20px; 
            position: relative;
            overflow: hidden;
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.3);
        }
        .custom-truck-loader::after {
            content: ""; position: absolute; bottom: 10px; left: 0; width: 100%; height: 4px;
            background: repeating-linear-gradient(90deg, #D4AF37, #D4AF37 35px, transparent 35px, transparent 70px);
            animation: moveRoad 1s linear infinite;
        }
        .custom-truck-loader img { width: 150px; animation: truckVibration 0.35s ease-in-out infinite; display: inline-block; margin-bottom: 8px; }

        [data-testid="stDownloadButton"] > button { 
            background: linear-gradient(135deg, #28A745 0%, #1E7E34 100%) !important; 
            color: #FFFFFF !important; 
            border-radius: 10px !important;
            padding: 0.8rem 2rem; font-size: 1.1rem; font-weight: 700;
            box-shadow: 0 4px 15px rgba(40, 167, 69, 0.4);
        }
    </style>
''', unsafe_allow_html=True)

st.title("🚛 Smart Route Rebalancer Dashboard")
st.markdown("**ระบบวิเคราะห์และตัดสายส่งน้ำอัตโนมัติ (Clean Hard-Cap Zoning Architecture)**")

st.sidebar.markdown("### 📁 1. นำเข้าข้อมูล (Data Source)")
sheet_url = st.sidebar.text_input("🔗 ลิงก์ Google Sheets:", placeholder="วางลิงก์ที่นี่...", on_change=reset_results)
raw_gid_input = st.sidebar.text_input("แท็บชีต (GID):", value="0", on_change=reset_results)

gid_match = re.search(r'gid=([0-9]+)', raw_gid_input)
sheet_gid = gid_match.group(1) if gid_match else ("".join(filter(str.isdigit, raw_gid_input)) or "0")

@st.cache_data(ttl=300)
def load_data_from_sheet(url, gid):
    try:
        match = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
        if not match: return None, "ลิงก์ Google Sheets ไม่ถูกต้อง"
        export_url = f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=csv&gid={gid}"
        df = pd.read_csv(export_url, dtype=str)
        if df.empty: return None, "ไม่พบข้อมูลในแท็บนี้"
        return df, None
    except Exception as e:
        return None, f"เกิดข้อผิดพลาด: {e}"

df = None
if sheet_url:
    cache_key = f"{sheet_url}::{sheet_gid}"
    if 'cached_raw_key' not in st.session_state or st.session_state['cached_raw_key'] != cache_key:
        loading_placeholder = st.empty()
        try:
            with open("truck.jpg", "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode()
            loader_html = f'''<div class="custom-truck-loader"><img src="data:image/jpeg;base64,{encoded_string}" alt="รถกำลังวิ่ง..."><br>กำลังเชื่อมต่อฐานข้อมูลระดับองค์กร... 💧</div>'''
        except FileNotFoundError:
            loader_html = '<div class="custom-truck-loader">กำลังเชื่อมต่อฐานข้อมูลระดับองค์กร... 💧</div>'
            
        loading_placeholder.markdown(loader_html, unsafe_allow_html=True)
        raw_df, err = load_data_from_sheet(sheet_url, sheet_gid)
        st.session_state['cached_raw_df'] = raw_df
        st.session_state['cached_raw_error'] = err
        st.session_state['cached_raw_key'] = cache_key
        time.sleep(0.5)
        loading_placeholder.empty()

    df = st.session_state.get('cached_raw_df', None)
    if df is None and st.session_state.get('cached_raw_error'):
        st.sidebar.error(f"❌ {st.session_state['cached_raw_error']}")

if df is not None and not df.empty:
    df = df.copy()

    def guess_col(substrings, cols, fallback=None):
        for c in cols:
            if any(s.lower() in str(c).lower() for s in substrings): return c
        return fallback if fallback is not None else cols[0]

    cols = df.columns.tolist()
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🧭 2. ยืนยันคอลัมน์ข้อมูล")

    vol_col = st.sidebar.selectbox("คอลัมน์ยอด (ถัง/เดือน):", options=cols, index=cols.index(guess_col(['ยอด', 'เดือน'], cols, cols[-1])), on_change=reset_results)
    lat_col = st.sidebar.selectbox("คอลัมน์ละติจูด:", options=cols, index=cols.index(guess_col(['ละติจูด', 'lat'], cols, cols[0])), on_change=reset_results)
    lon_col = st.sidebar.selectbox("คอลัมน์ลองจิจูด:", options=cols, index=cols.index(guess_col(['ลอง', 'lon'], cols, cols[0])), on_change=reset_results)
    truck_col = st.sidebar.selectbox("คอลัมน์เบอร์รถ:", options=cols, index=cols.index(guess_col(['เบอร์รถ', 'รถ'], cols, cols[0])), on_change=reset_results)
    
    vip_opt = ["-- ไม่มี --"] + cols
    vip_guessed = guess_col(['VIP', 'เงื่อนไข'], cols, None)
    vip_col_sel = st.sidebar.selectbox("คอลัมน์ VIP/เงื่อนไขพิเศษ:", options=vip_opt, index=(cols.index(vip_guessed) + 1) if vip_guessed else 0, on_change=reset_results)
    vip_col = None if vip_col_sel == "-- ไม่มี --" else vip_col_sel

    id_col = st.sidebar.selectbox("คอลัมน์รหัสลูกค้า:", options=cols, index=cols.index(guess_col(['รหัส', 'id'], cols, cols[0])), on_change=reset_results)
    
    name_opt = ["-- ไม่มี --"] + cols
    name_guessed = guess_col(['ชื่อ', 'name'], cols, None)
    name_col_sel = st.sidebar.selectbox("คอลัมน์ชื่อลูกค้า:", options=name_opt, index=(cols.index(name_guessed) + 1) if name_guessed else 0, on_change=reset_results)
    name_col = None if name_col_sel == "-- ไม่มี --" else name_col_sel

    df[lat_col] = pd.to_numeric(df[lat_col], errors='coerce')
    df[lon_col] = pd.to_numeric(df[lon_col], errors='coerce')
    df[vol_col] = pd.to_numeric(df[vol_col], errors='coerce').fillna(0).round().astype(int)
    df[truck_col] = df[truck_col].astype(str).str.strip()
    df[id_col] = df[id_col].astype(str).str.strip()
    df['VIP_Status'] = df[vip_col].astype(str).str.strip() if vip_col else 'ปกติ'

    df = df.dropna(subset=[lat_col, lon_col]).reset_index(drop=True)

    st.sidebar.success(f"✅ โหลดข้อมูลสำเร็จ: {len(df)} รายการ")
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚙️ 3. ตั้งค่าสายใหม่")

    guessed_day = guess_col(['สัปดาห์', 'วัน', 'รอบ', 'day'], cols, cols[0])
    day_col = st.sidebar.selectbox("📅 คอลัมน์ 'วันจัดส่ง':", options=cols, index=cols.index(guessed_day), on_change=reset_results)

    available_trucks = sorted(df[truck_col].unique().tolist())
    base_truck_options = ["(ไม่มี - เพิ่มรถคันใหม่กระจายงาน)"] + available_trucks

    base_truck = st.sidebar.selectbox("เลือกรถที่จะถูกยุบ/ดึงงานออก", options=base_truck_options, on_change=reset_results)
    new_truck_name = st.sidebar.text_input("ตั้งชื่อเบอร์รถคันใหม่", value="", placeholder="เช่น 15112", on_change=reset_results).strip()

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🎛️ 4. ปรับเป้าหมายรายวัน (%) พร้อมปุ่มล็อก")
    st.sidebar.caption("100% = 4,160 ถัง/เดือน (เลื่อนปรับ % และรถที่ไม่ได้ล็อกจะปรับแปรผันตามกันอัตโนมัติ)")

    # ตัดรถที่ถูกยุบออกจาก active_trucks ทันที เพื่อไม่ให้มีสไลเดอร์ค้าง
    active_trucks = [t for t in available_trucks if t != base_truck]
    if new_truck_name and new_truck_name not in active_trucks: 
        active_trucks.append(new_truck_name)

    if 'slider_init' not in st.session_state or st.session_state.get('base_truck') != base_truck or st.session_state.get('new_truck') != new_truck_name:
        st.session_state.truck_pcts = {}
        for t in active_trucks:
            if t == new_truck_name and t not in available_trucks:
                st.session_state.truck_pcts[t] = 100.0 if len(active_trucks) == 1 else round(100.0 / len(active_trucks), 1)
            else:
                actual_vol = df[df[truck_col] == t][vol_col].sum()
                # ถ้ารายการรถเดิมถูกยุบ ให้เอายอดรถยุบมารวมตั้งต้นให้สมเหตุสมผล
                st.session_state.truck_pcts[t] = float(round(max(0.0, min(200.0, (actual_vol / 4160.0) * 100)), 1))
                    
        for t in active_trucks:
            st.session_state[f"slider_{t}"] = float(round(st.session_state.truck_pcts[t], 1))
            
        st.session_state['slider_init'] = True
        st.session_state['base_truck'] = base_truck
        st.session_state['new_truck'] = new_truck_name

    def on_slider_change(changed_truck):
        raw_new_val = st.session_state.get(f"slider_{changed_truck}", 0.0)
        new_val = max(0.0, min(200.0, raw_new_val))
        old_val = st.session_state.truck_pcts.get(changed_truck, new_val)
        diff = new_val - old_val
        if abs(diff) < 0.01: return

        unlocked = [t for t in active_trucks if not st.session_state.get(f"lock_{t}", False) and t != changed_truck]
        if len(unlocked) > 0:
            split_diff = diff / len(unlocked)
            can_move = all(0.0 <= st.session_state.truck_pcts.get(t, 100.0) - split_diff <= 200.0 for t in unlocked)
            if can_move:
                for t in unlocked:
                    new_t_val = round(max(0.0, min(200.0, st.session_state.truck_pcts[t] - split_diff)), 1)
                    st.session_state.truck_pcts[t] = new_t_val
                    st.session_state[f"slider_{t}"] = new_t_val
                st.session_state.truck_pcts[changed_truck] = round(new_val, 1)
                st.session_state[f"slider_{changed_truck}"] = round(new_val, 1)
        else:
            st.session_state.truck_pcts[changed_truck] = round(new_val, 1)
            st.session_state[f"slider_{changed_truck}"] = round(new_val, 1)
        reset_results()

    target_pcts = {}
    for t in active_trucks:
        col_s1, col_s2 = st.sidebar.columns([3, 1.2])
        with col_s2:
            st.markdown("<div style='margin-top: 32px;'></div>", unsafe_allow_html=True)
            st.checkbox("🔒 ล็อก", key=f"lock_{t}", on_change=reset_results)
        with col_s1:
            if f"slider_{t}" not in st.session_state:
                st.session_state[f"slider_{t}"] = float(round(max(0.0, min(200.0, st.session_state.truck_pcts.get(t, 100.0))), 1))
            val = st.slider(f"รถ {t} (%)", min_value=0.0, max_value=200.0, step=0.1, key=f"slider_{t}", on_change=on_slider_change, args=(t,))
            clamped_val = max(0.0, min(200.0, val))
            target_pcts[t] = clamped_val
            st.session_state.truck_pcts[t] = clamped_val

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🔒 5. ล็อก Key Account")
    manual_vips = st.sidebar.multiselect("เลือกรหัสสมาชิกที่ห้ามย้ายสาย", options=df[id_col].unique().tolist(), default=[], on_change=reset_results)

    def parse_days_from_string(val_str):
        val = str(val_str).strip().replace(' ', '').lower()
        days = set()
        if 'ทุกวัน' in val or 'จ-ส' in val or 'จันทร์-เสาร์' in val: return [0, 1, 2, 3, 4, 5]
        if re.search(r'(จันทร์|จ\.|^จ$|^จ,|,จ,|,จ$|1)', val): days.add(0)
        if re.search(r'(อังคาร|อ\.|^อ$|^อ,|,อ,|,อ$|2)', val): days.add(1)
        if re.search(r'(พุธ|พ\.|^พ$|^พ,|,พ,|,พ$|3)', val.replace('พฤ', '')): days.add(2)
        if re.search(r'(พฤหัส|พฤ|4)', val): days.add(3)
        if re.search(r'(ศุกร์|ศ\.|^ศ$|^ศ,|,ศ,|,ศ$|5)', val): days.add(4)
        if re.search(r'(เสาร์|ส\.|^ส$|^ส,|,ศ$|6)', val): days.add(5)
        d_list = list(days)
        return d_list if d_list else [0, 1, 2, 3, 4, 5]

    def get_daily_vols(data_df):
        daily_matrix = np.zeros((len(data_df), 6)) 
        for i, row in data_df.iterrows():
            vol = int(row[vol_col])
            val = str(row.get(day_col, ''))
            days = parse_days_from_string(val)
            vol_per_day = vol / (len(days) * 4.333) 
            for d in days: daily_matrix[i, d] = vol_per_day
        return np.round(daily_matrix).astype(int)

    # ---------------------------------------------------------
    # 🧠 สมองกลหลัก: Strict Hard-Cap Contiguous Zoning Engine
    # ---------------------------------------------------------
    def run_clean_hard_cap_zoning(data, base_t, new_t, pct_dict, manual_locks):
        opt_df = data.copy()
        
        # 1. ยุบรวมตึก/พิกัดเดียวกันเป็นจุดจอดเดียว (Stop-Level Aggregation)
        opt_df['coord_key'] = opt_df[lat_col].round(5).astype(str) + "," + opt_df[lon_col].round(5).astype(str)
        locked_manual = [str(x).strip() for x in manual_locks]
        opt_df['is_locked'] = (opt_df['VIP_Status'].str.upper().str.strip() == 'VIP') | (opt_df[id_col].str.strip().isin(locked_manual))
        
        has_base = base_t != "(ไม่มี - เพิ่มรถคันใหม่กระจายงาน)"
        active_trucks = [t for t in available_trucks if t != base_t]
        if new_t and new_t not in active_trucks: 
            active_trucks.append(new_t)
            
        # กำหนดเป้าหมายปริมาณงาน (Hard-Cap Target Volume) ตามสไลเดอร์ (%)
        # 100% = 4160 ถังต่อเดือน
        targets = {t: 4160.0 * (pct_dict.get(t, 100.0) / 100.0) for t in active_trucks}

        stops = opt_df.groupby('coord_key').agg(
            lat=(lat_col, 'first'),
            lon=(lon_col, 'first'),
            total_vol=(vol_col, 'sum'),
            orig_truck=(truck_col, 'first'),
            has_lock=('is_locked', 'any')
        ).reset_index()

        # คำนวณ Seed / Centroid ของรถเดิมแต่ละคัน
        seeds = {}
        for t in available_trucks:
            if t == base_t: continue
            t_stops = stops[stops['orig_truck'] == t]
            if not t_stops.empty:
                seeds[t] = (t_stops['lat'].mean(), t_stops['lon'].mean())

        branch_lat = stops['lat'].mean()
        branch_lon = stops['lon'].mean()

        # ถ้ารีเควสรถใหม่ ให้ตั้ง Seed ไว้ที่จุดกึ่งกลางระหว่างรอยต่อรถเดิม
        if new_t:
            if seeds:
                seeds[new_t] = (np.mean([s[0] for s in seeds.values()]), np.mean([s[1] for s in seeds.values()]))
            else:
                seeds[new_t] = (branch_lat, branch_lon)

        # PHASE 1: ถ่ายโอนงานจากรถที่ถูกยุบ (base_t) ไปให้รถเดิมที่อยู่ใกล้ที่สุดก่อน
        stops['assigned_truck'] = stops['orig_truck']
        if has_base:
            base_stops_idx = stops[stops['orig_truck'] == base_t].index
            for idx in base_stops_idx:
                s_lat = stops.at[idx, 'lat']
                s_lon = stops.at[idx, 'lon']
                best_t = active_trucks[0]
                min_dist = float('inf')
                for t in active_trucks:
                    if t == new_t: continue
                    c_lat, c_lon = seeds.get(t, (branch_lat, branch_lon))
                    dist = (s_lat - c_lat)**2 + (s_lon - c_lon)**2
                    if dist < min_dist:
                        min_dist = dist
                        best_t = t
                stops.at[idx, 'assigned_truck'] = best_t

        # PHASE 2: ล็อก VIP / Key Account ให้อยู่กับรถเดิม
        for idx, s in stops.iterrows():
            if s['has_lock']:
                orig = s['assigned_truck']
                assigned = orig if orig in active_trucks else active_trucks[0]
                stops.at[idx, 'assigned_truck'] = assigned

        # PHASE 3: จัดสรรพื้นที่ให้ตรงกับเป้าหมาย Hard-Cap ของสไลเดอร์โดยขยายออกรอบตัวจาก Seed (Contiguous Region Growing)
        current_loads = {t: 0.0 for t in active_trucks}
        
        # ล้างการกำหนดค่าชั่วคราว ยกเว้น Locked
        stops.loc[stops['has_lock'], 'assigned_truck'] = stops.loc[stops['has_lock'], 'assigned_truck']
        # สำหรับจุดที่ไม่ล็อก ให้เริ่มจัดสรรใหม่ทีละวงแหวนรอบ Seed ของแต่ละรถ
        unassigned_stops = stops[~stops['has_lock']].copy()
        
        # คำนวณโหลดจากจุดที่ล็อกแล้วก่อน
        for _, s in stops[stops['has_lock']].iterrows():
            t = s['assigned_truck']
            if t in current_loads: current_loads[t] += s['total_vol']

        # วนลูปขยายอาณาเขตจาก Seed ของแต่ละรถทีละจุดที่ใกล้ที่สุด จนกว่าจะชน Hard-Cap หรือหมดจุด
        assigned_free_keys = set(stops[stops['has_lock']]['coord_key'])
        
        while True:
            progress = False
            for t in active_trucks:
                target_v = targets.get(t, 0.0)
                if current_loads[t] >= target_v:
                    continue # ชนเพดานสไลเดอร์แล้ว หยุดรับ
                
                # หาจุดที่ยังไม่ถูก assign และอยู่ใกล้ Seed ของรถคันนี้ที่สุด
                t_lat, t_lon = seeds.get(t, (branch_lat, branch_lon))
                free_stops = stops[~stops['coord_key'].isin(assigned_free_keys)].copy()
                if free_stops.empty: break
                
                free_stops['dist'] = (free_stops['lat'] - t_lat)**2 + (free_stops['lon'] - t_lon)**2
                free_stops = free_stops.sort_values('dist', ascending=True)
                
                best_match = None
                for _, f_row in free_stops.iterrows():
                    if current_loads[t] + f_row['total_vol'] <= target_v + 10.0:
                        best_match = f_row
                        break
                
                if best_match is not None:
                    stops.loc[stops['coord_key'] == best_match['coord_key'], 'assigned_truck'] = t
                    current_loads[t] += best_match['total_vol']
                    assigned_free_keys.add(best_match['coord_key'])
                    progress = True
            
            if not progress:
                break

        # จุดที่ยังเหลือแต่ทุกคันเต็มเพดานสไลเดอร์แล้ว ให้ปัดไป Overflow
        stops.loc[~stops['coord_key'].isin(assigned_free_keys), 'assigned_truck'] = 'ส่วนเกิน (Overflow)'

        stop_to_truck = dict(zip(stops['coord_key'], stops['assigned_truck']))
        opt_df['เบอร์รถใหม่'] = opt_df['coord_key'].map(stop_to_truck)
        opt_df['วันจัดส่ง(ใหม่)'] = opt_df[day_col].values

        opt_df['สถานะ'] = np.where(opt_df[truck_col] == opt_df['เบอร์รถใหม่'], 'คงเดิม', 'ย้ายไปสาย ' + opt_df['เบอร์รถใหม่'])
        daily_matrix = get_daily_vols(opt_df)
        
        return opt_df, daily_matrix

    st.sidebar.markdown("---")
    if st.sidebar.button("🚀 ประมวลผลตัดสายส่ง", use_container_width=True):
        if not new_truck_name and base_truck == "(ไม่มี - เพิ่มรถคันใหม่กระจายงาน)":
            st.sidebar.error("❌ กรุณาระบุชื่อเบอร์รถคันใหม่ก่อนประมวลผล")
            st.stop()
            
        calc_placeholder = st.empty()
        try:
            with open("truck.jpg", "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode()
            loader_html = f'''<div class="custom-truck-loader"><img src="data:image/jpeg;base64,{encoded_string}" alt="รถกำลังวิ่ง..."><br>กำลังประมวลผลจัดสรรเส้นทาง Clean Hard-Cap Architecture... 💧</div>'''
        except FileNotFoundError:
            loader_html = '<div class="custom-truck-loader">กำลังประมวลผลจัดสรรเส้นทาง Clean Hard-Cap Architecture... 💧</div>'
            
        calc_placeholder.markdown(loader_html, unsafe_allow_html=True)
        
        res_df, daily_matrix = run_clean_hard_cap_zoning(df, base_truck, new_truck_name, target_pcts, manual_vips)
        st.session_state['result_df'] = res_df
        st.session_state['daily_matrix'] = daily_matrix
        time.sleep(0.5) 
        calc_placeholder.empty()

    if 'result_df' in st.session_state:
        res_df = st.session_state['result_df']
        daily_matrix = st.session_state['daily_matrix']
        all_trucks_after = sorted(res_df['เบอร์รถใหม่'].dropna().unique().tolist())
        if new_truck_name and new_truck_name not in all_trucks_after: all_trucks_after.append(new_truck_name)
        
        st.markdown("### 📊 สรุปภาพรวมยอดการจัดส่ง")
        col1, col2 = st.columns(2)
        sum_before = df.groupby(truck_col).agg(จำนวนสมาชิก=pd.NamedAgg(column=truck_col, aggfunc='count'), **{'ยอดรับน้ำ(ถัง/เดือน)': pd.NamedAgg(column=vol_col, aggfunc='sum')}).reset_index()
        sum_after = res_df.groupby('เบอร์รถใหม่').agg(จำนวนสมาชิก=pd.NamedAgg(column='เบอร์รถใหม่', aggfunc='count'), **{'ยอดรับน้ำ(ถัง/เดือน)': pd.NamedAgg(column=vol_col, aggfunc='sum')}).reset_index()
        sum_after['ปริมาณงาน(%)'] = np.where(
            sum_after['เบอร์รถใหม่'] == 'ส่วนเกิน (Overflow)', 
            '-', 
            (sum_after['ยอดรับน้ำ(ถัง/เดือน)'] / 4160 * 100).round(1).astype(str) + '%'
        )

        with col1:
            st.markdown("**ก่อนปรับโครงสร้างสายส่ง**")
            st.dataframe(sum_before, use_container_width=True)
        with col2:
            st.markdown("**หลังปรับโครงสร้าง (Clean Hard-Cap Zoning)**")
            st.dataframe(sum_after, use_container_width=True)
            
        # 🗺️ 1. แผนที่เชิงพื้นที่ (แสดงก่อนตารางวิเคราะห์โหลดรายวันตามที่ต้องการ)
        st.markdown("### 🗺️ แผนที่เปรียบเทียบการกระจายตัว (เชิงพื้นที่)")
        map_trucks_view = [t for t in all_trucks_after if t != 'ส่วนเกิน (Overflow)']
        view_options = ["แสดงทั้งหมด (แยกสีตามเบอร์รถ)"] + map_trucks_view
        
        col_filter, _ = st.columns([1, 1])
        with col_filter: selected_view = st.selectbox("🔍 เลือกรูปแบบการแสดงผลบนแผนที่:", options=view_options)

        day_color_map = {'จันทร์': '#FFD700', 'อังคาร': '#FF69B4', 'พุธ': '#28A745', 'พฤหัสบดี': '#FD7E14', 'ศุกร์': '#00BFFF', 'เสาร์': '#6F42C1', 'อาทิตย์': '#DC3545'}
        standard_palette = ['blue', 'green', 'orange', 'purple', 'darkblue', 'cadetblue', 'pink']
        color_map = {str(t): standard_palette[i % len(standard_palette)] for i, t in enumerate(map_trucks_view) if str(t) != new_truck_name}
        color_map[new_truck_name] = 'red' 

        if selected_view == "แสดงทั้งหมด (แยกสีตามเบอร์รถ)":
            map_df_before, map_df_after = df, res_df[res_df['เบอร์รถใหม่'] != 'ส่วนเกิน (Overflow)']
            color_mode = 'truck'
        else:
            if selected_view == new_truck_name and base_truck == "(ไม่มี - เพิ่มรถคันใหม่กระจายงาน)": map_df_before = pd.DataFrame(columns=df.columns) 
            else: map_df_before = df[df[truck_col] == (base_truck if selected_view == new_truck_name else selected_view)]
            map_df_after = res_df[res_df['เบอร์รถใหม่'] == selected_view]
            color_mode = 'day'

        c_lat, c_lon = (map_df_after[lat_col].mean(), map_df_after[lon_col].mean()) if not map_df_after.empty else (res_df[lat_col].mean(), res_df[lon_col].mean())
        if pd.isna(c_lat): c_lat, c_lon = df[lat_col].mean(), df[lon_col].mean()

        map_col1, map_col2 = st.columns(2)
        def get_name(row): return str(row[name_col]) if name_col else "ไม่ระบุ"

        with map_col1:
            st.markdown("<div style='text-align:center; color:#FFD700; font-weight:bold; margin-bottom:8px;'>โซนการวิ่งรถเดิม (Before - ข้อมูลดิบต้นฉบับ 100%)</div>", unsafe_allow_html=True)
            m1 = folium.Map(location=[c_lat, c_lon], zoom_start=12 if color_mode=='truck' else 14)
            plugins.Fullscreen(position='topright').add_to(m1)
            for _, r in map_df_before.iterrows():
                t_id = str(r[truck_col])
                is_vip = str(r.get('VIP_Status', '')).upper() == 'VIP' or str(r[id_col]) in manual_vips
                m_color = color_map.get(t_id, 'gray') if color_mode == 'truck' else next((c for d, c in day_color_map.items() if d in str(r.get(day_col, '')).strip()), 'gray')
                popup_html = f"<b>รหัส:</b> {r[id_col]}<br><b>ชื่อ:</b> {get_name(r)}<br><b>ยอด:</b> {int(r[vol_col])} ถัง<br><b>รถ:</b> {t_id}"
                folium.CircleMarker([r[lat_col], r[lon_col]], radius=8 if is_vip else 5, color='#FFD700' if is_vip else m_color, weight=2 if is_vip else 1, fill=True, fillColor=m_color, fill_opacity=0.9, popup=folium.Popup(popup_html, max_width=300)).add_to(m1)
            components.html(m1.get_root().render(), height=450)

        with map_col2:
            st.markdown("<div style='text-align:center; color:#FFD700; font-weight:bold; margin-bottom:8px;'>โซนการวิ่งสายใหม่ (Clean Zoning)</div>", unsafe_allow_html=True)
            m2 = folium.Map(location=[c_lat, c_lon], zoom_start=12 if color_mode=='truck' else 14)
            plugins.Fullscreen(position='topright').add_to(m2)
            for _, r in map_df_after.iterrows():
                t_new = str(r['เบอร์รถใหม่'])
                is_vip = str(r.get('VIP_Status', '')).upper() == 'VIP' or str(r[id_col]) in manual_vips
                display_day = str(r.get(day_col, ''))
                m_color = color_map.get(t_new, 'gray') if color_mode == 'truck' else next((c for d, c in day_color_map.items() if d in display_day.strip()), 'gray')
                popup_html = f"<b>รหัส:</b> {r[id_col]}<br><b>ชื่อ:</b> {get_name(r)}<br><b>ยอด:</b> {int(r[vol_col])} ถัง<br><b>รถล่าสุด:</b> {t_new}"
                folium.CircleMarker([r[lat_col], r[lon_col]], radius=8 if is_vip else 5, color='#FFD700' if is_vip else m_color, weight=2 if is_vip else 1, fill=True, fillColor=m_color, fill_opacity=0.9, popup=folium.Popup(popup_html, max_width=300)).add_to(m2)
            components.html(m2.get_root().render(), height=450)

        # 📅 2. ตารางวิเคราะห์โหลดรายวัน (แสดงผลเป็นจำนวนเต็ม 100% ไม่มีทศนิยม)
        st.markdown("### 📅 ตารางวิเคราะห์โหลดรายวัน (จันทร์-เสาร์)")
        daily_summary = []
        for t in all_trucks_after:
            if t == 'ส่วนเกิน (Overflow)': continue
            t_mask = res_df['เบอร์รถใหม่'] == t
            t_daily = daily_matrix[t_mask].sum(axis=0) if t_mask.any() else np.zeros(6)
            daily_summary.append({
                'เบอร์รถ': t,
                'จันทร์': int(round(t_daily[0])),
                'อังคาร': int(round(t_daily[1])),
                'พุธ': int(round(t_daily[2])),
                'พฤหัสฯ': int(round(t_daily[3])),
                'ศุกร์': int(round(t_daily[4])),
                'เสาร์': int(round(t_daily[5])),
                'โหลดสูงสุด (ถัง/วัน)': int(round(max(t_daily)))
            })
        st.dataframe(pd.DataFrame(daily_summary), use_container_width=True)

        # 📋 3. ตารางรายละเอียดข้อมูลการโยกย้ายสมาชิก
        st.markdown("### 📋 รายละเอียดข้อมูลการโยกย้ายสมาชิก")
        final_cols = [id_col]
        if name_col and name_col in res_df.columns: final_cols.append(name_col)
        final_cols.extend([day_col, vol_col, truck_col, 'เบอร์รถใหม่', 'สถานะ'])

        detail_df = res_df.copy()
        detail_df['เบอร์รถเดิม (ก่อนปรับ)'] = detail_df[truck_col]
        detail_df = detail_df[[c for c in final_cols if c in detail_df.columns]].rename(columns={truck_col: 'เบอร์รถเดิม (ก่อนปรับ)'})
        st.dataframe(detail_df, use_container_width=True)
        
        st.markdown("---")
        st.markdown("<div style='text-align:center; margin-bottom: 10px;'><b>📌 เมื่อผลลัพธ์สมบูรณ์แบบแล้ว สามารถดาวน์โหลดข้อมูลไปใช้งานได้ทันที</b></div>", unsafe_allow_html=True)
        
        @st.cache_data
        def convert_df_to_bytes(df): return df.to_csv(index=False).encode('utf-8-sig')

        csv_bytes = convert_df_to_bytes(detail_df)
        col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
        with col_btn2:
            st.download_button(
                label="📥 ดาวน์โหลดข้อมูลสรุปผล (เปิดใน Excel ได้ทันที)",
                data=csv_bytes,
                file_name='sprinkle_route_result.csv',
                mime='text/csv',
                use_container_width=True
            )
    else:
        st.info("👈 ปรับตั้งค่าเปอร์เซ็นต์และล็อกรถให้เรียบร้อย จากนั้นกดปุ่ม 'ประมวลผลตัดสายส่ง' ที่แถบเมนูด้านซ้าย เพื่อดูผลลัพธ์")
else:
    st.info("👈 กรุณาวางลิงก์ Google Sheets ที่แถบเมนูด้านซ้าย เพื่อเริ่มต้นใช้งาน Dashboard")
