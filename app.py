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

MONTHLY_CAPACITY_PER_TRUCK = 4160.0  # แก้ไข: รวมเป็นค่าคงที่เดียว (เดิมพิมพ์ 4160 ซ้ำหลายจุดในโค้ด)
OVERFLOW_LABEL = 'ส่วนเกิน (Overflow)'

# -------------------------------------------------------------
# 🎯 เกณฑ์ตามกฎ 7 ข้อที่ผู้ใช้กำหนด (Priority: VIP Lock > Core Lock > Daily Threshold > Target Matching)
# -------------------------------------------------------------
OPTIMAL_MIN, OPTIMAL_MAX = 140, 155      # โซนเหมาะสม (คุ้มค่าวิ่ง 2 เที่ยว)
AVOID_MIN, AVOID_MAX = 121, 139          # โซนควรเลี่ยง (เที่ยว 2 ไม่คุ้ม)
MAX_DAY_CAP = 156                        # เพดานที่พยายามไม่ให้เกิน (เว้นแต่จะตัดซอยเดียวกัน)
TARGET_DAY_CAP = 148                     # เป้าหมายที่ดันโหลดลงมาเมื่อ smoothing
ESCALATE_THRESHOLD = 160                 # เกินนี้แล้ว smoothing เอาไม่อยู่ → ยอมรับเป็นรอบ 3
ESCALATE_TARGET_MIN, ESCALATE_TARGET_MAX = 180, 190  # ช่วงที่ยอมรับได้สำหรับรอบ 3

# -------------------------------------------------------------
# 💎 UNIFIED POOL & SEED-CENTRIC GLASSMORPHISM ARCHITECTURE
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
st.markdown("**ระบบวิเคราะห์และตัดสายส่งน้ำอัตโนมัติ (Unified Pool Architecture)**")

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

    n_before = len(df)
    df = df.dropna(subset=[lat_col, lon_col]).reset_index(drop=True)
    if n_before - len(df) > 0:
        st.sidebar.warning(f"⚠️ ตัดทิ้ง {n_before - len(df)} รายการที่พิกัดไม่ถูกต้อง/ว่าง")

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
    st.sidebar.caption(f"100% = {MONTHLY_CAPACITY_PER_TRUCK:,.0f} ถัง/เดือน (เลื่อนปรับ % และรถที่ไม่ได้ล็อกจะปรับแปรผันตามกันอัตโนมัติ)")

    active_trucks = [t for t in available_trucks if t != base_truck]
    if new_truck_name and new_truck_name not in active_trucks: 
        active_trucks.append(new_truck_name)

    if 'slider_init' not in st.session_state or st.session_state.get('base_truck') != base_truck or st.session_state.get('new_truck') != new_truck_name:
        st.session_state.truck_pcts = {}
        for t in active_trucks:
            # 🛑 STRICT ZERO INITIALIZATION FOR NEW TRUCK
            if t == new_truck_name and t not in available_trucks:
                st.session_state.truck_pcts[t] = 0.0
            else:
                actual_vol = df[df[truck_col] == t][vol_col].sum()
                st.session_state.truck_pcts[t] = float(round(max(0.0, min(200.0, (actual_vol / MONTHLY_CAPACITY_PER_TRUCK) * 100)), 1))

        # แก้ไข: บั๊กหลักที่ทำให้ "กระจายงานผิดพลาด" — เดิมเมื่อยุบรถคันหนึ่ง (base_truck) ยอด/% ของ
        # รถคันนั้นจะหายไปเฉยๆ ไม่ถูกแจกจ่ายให้รถที่เหลือ/รถใหม่เลย ทำให้ผลรวมเป้าหมายทุกคันหลังยุบ
        # ต่ำกว่ายอดที่ต้องจัดสรรจริงมาก ลูกค้าจำนวนมากเลยตกไป Overflow ทั้งที่ความจุรวมพอ
        # ตอนนี้เอา % ของรถที่ถูกยุบมาหารเฉลี่ยแจกคืนให้ทุกคันที่เหลือ (ผู้ใช้ยังปรับ slider เองทีหลังได้)
        if base_truck != "(ไม่มี - เพิ่มรถคันใหม่กระจายงาน)" and active_trucks:
            base_vol = df[df[truck_col] == base_truck][vol_col].sum()
            base_pct = float(round((base_vol / MONTHLY_CAPACITY_PER_TRUCK) * 100, 1))
            split = base_pct / len(active_trucks)
            for t in active_trucks:
                st.session_state.truck_pcts[t] = round(st.session_state.truck_pcts[t] + split, 1)

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
            # แก้ไข: เดิมถ้า can_move=False ค่าจะไม่ถูกอัปเดตเลย (เงียบๆ ค้างที่ค่าเก่า) ทำให้ผู้ใช้งง
            # ว่าทำไมลากแล้วไม่ขยับ ตอนนี้ดันสมาชิกที่เหลือให้ไปแตะขอบเขต (0 หรือ 200) แทน
            else:
                for t in unlocked:
                    capped = 0.0 if split_diff > 0 else 200.0
                    st.session_state.truck_pcts[t] = capped
                    st.session_state[f"slider_{t}"] = capped
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

    # แก้ไข: เพิ่มการเตือน feasibility ที่หายไปในเวอร์ชันนี้ — ถ้าผลรวม % เป้าหมายทุกคัน
    # ต่างจากยอดที่ต้องจัดสรรจริงเกิน 5% แจ้งเตือนก่อนกดประมวลผล จะได้ไม่ต้องมาเจอ Overflow แบบงงๆ ทีหลัง
    total_vol_available = df[vol_col].sum()
    sys_pct = (total_vol_available / MONTHLY_CAPACITY_PER_TRUCK) * 100
    total_target_pct = sum(target_pcts.values())
    st.sidebar.info(f"💧 ยอดรวมที่ต้องจัดสรรจริง ≈ {sys_pct:,.1f}% | ผลรวม % เป้าหมายตอนนี้ = {total_target_pct:,.1f}%")
    if total_target_pct > 0 and sys_pct > 0 and abs(total_target_pct - sys_pct) / sys_pct > 0.05:
        st.sidebar.warning(f"⚠️ ผลรวม % เป้าหมาย ({total_target_pct:,.1f}%) ต่างจากยอดที่ต้องจัดสรรจริง ({sys_pct:,.1f}%) เกิน 5% — มีความเสี่ยงที่ลูกค้าบางส่วนจะตกไปที่ '{OVERFLOW_LABEL}'")

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🔒 5. ล็อก Key Account")
    manual_vips = st.sidebar.multiselect("เลือกรหัสสมาชิกที่ห้ามย้ายสาย", options=df[id_col].unique().tolist(), default=[], on_change=reset_results)

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🎯 6. กฎลำดับความสำคัญ (Priority Rules)")
    st.sidebar.caption("ลำดับ: 1) VIP Lock 2) Core Lock 3) Daily Threshold 4) Target Matching (มีค่าเผื่อ)")
    core_ratio_pct = st.sidebar.slider(
        "สัดส่วนแกนกลางที่ล็อกไว้ (Core %)", min_value=0, max_value=100, value=65, step=5,
        help="ลูกค้ากลุ่มที่เกาะกลุ่มแน่นใกล้ศูนย์กลางของรถเดิม (ตามสัดส่วนยอดนี้) จะถูกล็อกไว้กับรถเดิม ห้ามย้าย เหลือแค่รอบนอกที่จะถูกดึงไปจัดสรรใหม่",
        on_change=reset_results
    )
    tolerance_pct = st.sidebar.number_input(
        "ค่าเผื่อเป้าหมาย (Target Tolerance %)", min_value=0.0, max_value=50.0, value=5.0, step=0.5,
        help="ยอมให้ยอดจริงหลังจัดสรรคลาดเคลื่อนจาก % เป้าหมายบนสไลเดอร์ได้กี่ % เพราะกฎ VIP/Core Lock อาจทำให้ตรงเป๊ะไม่ได้เสมอไป",
        on_change=reset_results
    )

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🛣️ 7. ระยะทางถนนจริง (กฎข้อ 3: อิงเส้นทางจราจรจริง)")
    use_road_distance = st.sidebar.checkbox(
        "ใช้ระยะทางถนนจริงแทนเส้นตรง (เรียก API)", value=False,
        help="ค่าเริ่มต้นระบบใช้ระยะทางเส้นตรง (lat/lon) ซึ่งในกรุงเทพฯ ที่มีแม่น้ำ/ทางด่วนตัดผ่าน อาจทำให้จุดที่ 'ใกล้กันแบบตรงๆ' จริงๆ ต้องขับอ้อมไกลมาก เปิดตัวเลือกนี้เพื่อให้ระบบใช้ระยะทางขับรถจริงแทน (ช้าลงเพราะต้องเรียก API)",
        on_change=reset_results
    )
    road_provider = None
    osrm_url = "https://router.project-osrm.org"
    google_api_key = ""
    if use_road_distance:
        road_provider = st.sidebar.radio(
            "เลือกผู้ให้บริการระยะทาง:",
            options=["osrm", "google"],
            format_func=lambda x: "OSRM (ฟรี, demo server)" if x == "osrm" else "Google Distance Matrix (ต้องมี API Key)",
            on_change=reset_results
        )
        if road_provider == "osrm":
            osrm_url = st.sidebar.text_input(
                "OSRM Server URL", value="https://router.project-osrm.org",
                help="ค่าเริ่มต้นคือ public demo server ของ OSRM — ใช้ได้ฟรีแต่ไม่รับประกันความเสถียร/ความเร็ว ไม่เหมาะกับข้อมูลจำนวนมากหรือใช้งานจริงจัง ถ้ามี OSRM server ของตัวเอง (self-hosted) ใส่ URL ที่นี่แทน",
                on_change=reset_results
            )
            st.sidebar.caption("⚠️ Public demo server ของ OSRM มีข้อจำกัดเรื่องปริมาณ/ความถี่การเรียก ถ้าข้อมูลลูกค้าเยอะมาก (หลายร้อย-พันจุด) แนะนำให้ self-host OSRM เอง")
        else:
            google_api_key = st.sidebar.text_input(
                "Google Maps API Key (Distance Matrix API)", value="", type="password",
                help="ต้องเปิดใช้ Distance Matrix API ใน Google Cloud Console และมี billing account ผูกไว้ — มีค่าใช้จ่ายตามปริมาณการเรียก",
                on_change=reset_results
            )
            if not google_api_key:
                st.sidebar.warning("⚠️ กรุณาใส่ Google API Key ก่อน ไม่งั้นระบบจะ fallback ไปใช้ระยะทางเส้นตรงแทนอัตโนมัติ")

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

    def format_days_to_string(days_list):
        if not days_list: return "ไม่ระบุ"
        day_names = {0: 'จันทร์', 1: 'อังคาร', 2: 'พุธ', 3: 'พฤหัสฯ', 4: 'ศุกร์', 5: 'เสาร์'}
        if len(days_list) == 6: return 'จ-ส'
        return ', '.join([day_names[d] for d in sorted(days_list)])

    # -----------------------------------------------------------------
    # PRIORITY 3: Daily Load Threshold — เกลี่ยวันจัดส่งภายในรถคันเดียวกัน
    # (ไม่ย้ายข้ามคัน ไม่แตะลูกค้าที่ล็อก) เพื่อดันโหลดรายวันเข้าใกล้โซนเหมาะสม
    # 140-155/วัน ถ้าเกิน 156 พยายามเกลี่ย ถ้าเกลี่ยแล้วยังเกิน 160 ให้ยอมรับเป็น
    # "รอบ 3" (180-190) แทนที่จะฝืนเกลี่ยจนลูกค้าซอยเดียวกันกระจายวันมั่ว
    # -----------------------------------------------------------------
    def smooth_daily_loads(opt_df, active_trucks_list):
        assigned_days = {idx: parse_days_from_string(opt_df.at[idx, day_col]) for idx in opt_df.index}
        vols_local = opt_df[vol_col].values
        idx_list = opt_df.index.tolist()
        idx_pos = {idx: pos for pos, idx in enumerate(idx_list)}

        def compute_daily():
            daily = {t: np.zeros(6) for t in active_trucks_list}
            for idx in idx_list:
                t = opt_df.at[idx, 'เบอร์รถใหม่']
                if t not in daily: continue
                d_list = assigned_days[idx]
                len_d = max(1, len(d_list))
                per_day = vols_local[idx_pos[idx]] / len_d / 4.333
                for d in d_list: daily[t][d] += per_day
            return daily

        for _pass in range(4):
            daily = compute_daily()
            changed = False
            for t in active_trucks_list:
                for d in range(6):
                    if daily[t][d] <= MAX_DAY_CAP:
                        continue
                    if daily[t][d] > ESCALATE_THRESHOLD:
                        # เกิน 160 แล้ว ปล่อยให้เป็นรอบ 3 (180-190) ไม่ฝืนเกลี่ยต่อ ตามกฎข้อ 5
                        continue
                    target_d = int(np.argmin(daily[t]))
                    if target_d == d or daily[t][target_d] >= MAX_DAY_CAP - 10:
                        continue
                    movable = [idx for idx in idx_list
                               if opt_df.at[idx, 'เบอร์รถใหม่'] == t and not opt_df.at[idx, 'is_locked']
                               and d in assigned_days[idx] and len(assigned_days[idx]) <= 3
                               and target_d not in assigned_days[idx]]
                    if not movable:
                        continue
                    excess = daily[t][d] - TARGET_DAY_CAP
                    shifted = 0.0
                    for idx in movable:
                        if shifted >= excess or daily[t][target_d] > MAX_DAY_CAP:
                            break
                        old_list = assigned_days[idx]
                        new_list = [target_d if x == d else x for x in old_list]
                        len_old = max(1, len(old_list))
                        v = vols_local[idx_pos[idx]] / len_old / 4.333
                        assigned_days[idx] = new_list
                        opt_df.at[idx, 'สถานะการย้ายวัน'] = f"ย้าย {format_days_to_string([d])} -> {format_days_to_string([target_d])}"
                        daily[t][d] -= v
                        daily[t][target_d] += v
                        shifted += v
                        changed = True
            if not changed:
                break

        for idx in idx_list:
            opt_df.at[idx, 'วันจัดส่ง(ใหม่)'] = format_days_to_string(assigned_days[idx])

        final_daily = compute_daily()
        daily_matrix = np.zeros((len(opt_df), 6))
        for idx in idx_list:
            d_list = assigned_days[idx]
            len_d = max(1, len(d_list))
            v = vols_local[idx_pos[idx]] / len_d / 4.333
            for d in d_list: daily_matrix[idx_pos[idx], d] = v
        return opt_df, daily_matrix, final_daily

    # -----------------------------------------------------------------
    # 🛣️ ระยะทางถนนจริง (กฎข้อ 3): เรียก API ครั้งเดียวต่อรอบประมวลผล เพื่อคำนวณระยะทาง
    # ขับรถจริงจาก "จุดจอดที่ยังไม่ถูกจัดสรร" ไปยัง "จุดศูนย์กลางเริ่มต้นของแต่ละรถ" (seed)
    # แทนระยะทางเส้นตรง — ใช้ seed คงที่ (ไม่ recompute ทุกรอบแบบโหมดเส้นตรง) เพื่อไม่ให้ยิง API
    # ซ้ำเป็นสิบๆ รอบจนโดน rate-limit ข้อแลกเปลี่ยนคือจะไม่ปรับศูนย์กลางแบบไดนามิกเหมือนโหมดเส้นตรง
    # -----------------------------------------------------------------
    @st.cache_data(ttl=3600, show_spinner=False)
    def fetch_osrm_distance_matrix(source_coords, dest_coords, base_url):
        import requests
        try:
            all_coords = list(source_coords) + list(dest_coords)
            coord_str = ";".join(f"{lon:.6f},{lat:.6f}" for lat, lon in all_coords)
            n_src = len(source_coords)
            n_dst = len(dest_coords)
            src_idx = ";".join(str(i) for i in range(n_src))
            dst_idx = ";".join(str(i) for i in range(n_src, n_src + n_dst))
            url = f"{base_url.rstrip('/')}/table/v1/driving/{coord_str}"
            resp = requests.get(url, params={"sources": src_idx, "destinations": dst_idx, "annotations": "distance"}, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") != "Ok":
                return None
            return np.array(data["distances"], dtype=float)  # เมตร, shape (n_src, n_dst)
        except Exception:
            return None

    @st.cache_data(ttl=3600, show_spinner=False)
    def fetch_google_distance_matrix(source_coords, dest_coords, api_key):
        import requests
        try:
            n_src, n_dst = len(source_coords), len(dest_coords)
            dist = np.full((n_src, n_dst), np.nan)
            dest_str = "|".join(f"{lat:.6f},{lon:.6f}" for lat, lon in dest_coords)
            CHUNK = 25  # ข้อจำกัดของ Google Distance Matrix API ต่อ request
            for start in range(0, n_src, CHUNK):
                chunk = source_coords[start:start + CHUNK]
                origin_str = "|".join(f"{lat:.6f},{lon:.6f}" for lat, lon in chunk)
                resp = requests.get(
                    "https://maps.googleapis.com/maps/api/distancematrix/json",
                    params={"origins": origin_str, "destinations": dest_str, "key": api_key, "mode": "driving"},
                    timeout=30
                )
                resp.raise_for_status()
                data = resp.json()
                if data.get("status") != "OK":
                    return None
                for i, row in enumerate(data["rows"]):
                    for j, elem in enumerate(row["elements"]):
                        if elem.get("status") == "OK":
                            dist[start + i, j] = elem["distance"]["value"]  # เมตร
            return dist
        except Exception:
            return None

    # ---------------------------------------------------------
    # 🧠 สมองกลหลัก: Unified Pool & Hard-Cap Zoning Engine
    # ลำดับความสำคัญ: 1) VIP/Manual Lock  2) Core Preservation Lock  3) (ทำต่อใน smooth_daily_loads)
    # 4) Strict Target Matching แบบมีค่าเผื่อ (tolerance)
    # ---------------------------------------------------------
    def run_unified_pool_zoning(data, base_t, new_t, pct_dict, manual_locks, core_ratio, tol_pct,
                                 use_road_dist=False, road_prov='osrm', osrm_server_url='', gmaps_key=''):
        opt_df = data.copy()
        
        opt_df['coord_key'] = opt_df[lat_col].round(5).astype(str) + "," + opt_df[lon_col].round(5).astype(str)
        locked_manual = [str(x).strip() for x in manual_locks]
        opt_df['is_vip_locked'] = (opt_df['VIP_Status'].str.upper().str.strip() == 'VIP') | (opt_df[id_col].str.strip().isin(locked_manual))
        opt_df['สถานะการย้ายวัน'] = '-'
        
        has_base = base_t != "(ไม่มี - เพิ่มรถคันใหม่กระจายงาน)"
        active_trucks = [t for t in available_trucks if t != base_t]
        if new_t and new_t not in active_trucks: 
            active_trucks.append(new_t)
            
        targets = {t: MONTHLY_CAPACITY_PER_TRUCK * (pct_dict.get(t, 100.0) / 100.0) for t in active_trucks}
        if has_base: targets[base_t] = 0.0
        tolerance_units = (tol_pct / 100.0) * MONTHLY_CAPACITY_PER_TRUCK

        stops = opt_df.groupby('coord_key').agg(
            lat=(lat_col, 'first'),
            lon=(lon_col, 'first'),
            total_vol=(vol_col, 'sum'),
            orig_truck=(truck_col, 'first'),
            has_vip_lock=('is_vip_locked', 'any')
        ).reset_index()

        # แก้ไข: เตือนถ้ามี "จุดจอด" (พิกัดเดียวกัน) ที่ยอดรวมใหญ่กว่าความจุของทุกคันรวมกัน —
        # กรณีนี้จุดนั้นจะตกไป Overflow เสมอไม่ว่าจะตั้งค่ายังไง เพราะเป็นก้อนที่แบ่งแยกไม่ได้
        if not stops.empty:
            max_stop_vol = stops['total_vol'].max()
            max_single_target = max(targets.values()) if targets else 0
            if max_stop_vol > max_single_target and max_single_target > 0:
                st.warning(f"⚠️ พบจุดพิกัดที่มียอดรวม {max_stop_vol:,.0f} ถัง/เดือน (ลูกค้าหลายรายพิกัดชนกัน) ซึ่งมากกว่าความจุสูงสุดต่อคันที่ตั้งไว้ ({max_single_target:,.0f}) จุดนี้จะตกไป '{OVERFLOW_LABEL}' เสมอ — ควรตรวจสอบพิกัด GPS ของลูกค้ากลุ่มนี้")

        # -------------------------------------------------------------
        # PRIORITY 2: Core Preservation — ล็อกกลุ่มลูกค้าแกนกลาง (เกาะกลุ่มแน่นใกล้ศูนย์กลาง
        # ของรถเดิม ตามสัดส่วนยอด core_ratio) ให้อยู่กับรถเดิม ไม่ยุ่งเกี่ยว เหลือแค่รอบนอกให้ดึงไปจัดใหม่
        # รถที่ถูกยุบ (base_t) ไม่มี core lock เลย เพราะลูกค้าทั้งหมดต้องถูกจัดสรรใหม่อยู่แล้ว
        # -------------------------------------------------------------
        core_keys = set()
        if core_ratio > 0:
            for t in available_trucks:
                if t == base_t:
                    continue
                t_stops = stops[stops['orig_truck'] == t].copy()
                if t_stops.empty:
                    continue
                c_lat, c_lon = t_stops['lat'].mean(), t_stops['lon'].mean()
                t_stops['dist'] = (t_stops['lat'] - c_lat) ** 2 + (t_stops['lon'] - c_lon) ** 2
                t_stops = t_stops.sort_values('dist')
                t_stops['cum_vol'] = t_stops['total_vol'].cumsum()
                total_t_vol = max(1e-6, t_stops['total_vol'].sum())
                core_mask = (t_stops['cum_vol'] / total_t_vol) <= (core_ratio / 100.0)
                if not core_mask.any() and len(t_stops) > 0:
                    core_mask.iloc[0] = True
                core_keys.update(t_stops.loc[core_mask, 'coord_key'].tolist())

        stops['is_core_locked'] = stops['coord_key'].isin(core_keys)
        stops['is_locked'] = stops['has_vip_lock'] | stops['is_core_locked']
        opt_df['is_locked'] = opt_df['is_vip_locked'] | opt_df['coord_key'].isin(core_keys)

        seeds = {}
        for t in available_trucks:
            if t == base_t: continue
            t_stops = stops[stops['orig_truck'] == t]
            if not t_stops.empty:
                seeds[t] = (t_stops['lat'].mean(), t_stops['lon'].mean())

        branch_lat = stops['lat'].mean()
        branch_lon = stops['lon'].mean()

        if new_t:
            if seeds:
                seeds[new_t] = (np.mean([s[0] for s in seeds.values()]), np.mean([s[1] for s in seeds.values()]))
            else:
                seeds[new_t] = (branch_lat, branch_lon)

        # แก้ไข (ใหม่): คำนวณระยะทางถนนจริงจาก "จุดจอดทุกจุด" ไปยัง "seed คงที่ของแต่ละคัน" ครั้งเดียว
        # ก่อนเริ่มจัดสรร (ไม่เรียก API ซ้ำทุกรอบ กันโดน rate-limit) ถ้าเรียกไม่สำเร็จจะ fallback
        # เป็นระยะทางเส้นตรงอัตโนมัติพร้อมแจ้งเตือน — ตามกฎข้อ 3 "อิงเส้นทางจราจรจริง"
        road_dist_matrix = None
        if use_road_dist and active_trucks and not stops.empty:
            dest_coords = [seeds.get(t, (branch_lat, branch_lon)) for t in active_trucks]
            src_coords = list(zip(stops['lat'].tolist(), stops['lon'].tolist()))
            if road_prov == 'osrm':
                mat = fetch_osrm_distance_matrix(tuple(src_coords), tuple(dest_coords), osrm_server_url)
            elif gmaps_key:
                mat = fetch_google_distance_matrix(tuple(src_coords), tuple(dest_coords), gmaps_key)
            else:
                mat = None
            if mat is None:
                st.warning("⚠️ เรียก API ระยะทางถนนจริงไม่สำเร็จ (เครือข่าย/โควตา/API Key ไม่ถูกต้อง) — รอบนี้ระบบจะใช้ระยะทางเส้นตรงแทนโดยอัตโนมัติ")
            else:
                road_dist_matrix = mat

        def get_dist(stop_pos, t, s_lat, s_lon, centroid_lat, centroid_lon):
            if road_dist_matrix is not None:
                dval = road_dist_matrix[stop_pos, active_trucks.index(t)]
                if not np.isnan(dval):
                    return dval
            return (s_lat - centroid_lat) ** 2 + (s_lon - centroid_lon) ** 2

        # เริ่มต้นให้ทุกจุดเป็น None (Unassigned Pool) ยกเว้นจุดที่ล็อกไว้ (VIP หรือ Core)
        stops['assigned_truck'] = None
        
        # 1. จัดสรรจุดที่ล็อก (VIP / Manual / Core Lock) — ทั้งหมดนี้ priority สูงกว่าการจัดสรรใหม่เสมอ
        # แก้ไข: เดิมถ้ารถต้นทางของลูกค้าที่ล็อกถูกยุบไป จะส่งไป active_trucks[0] แบบสุ่ม/ไม่สนใจภูมิศาสตร์
        # ตอนนี้ถ้ารถต้นทางไม่มีแล้ว จะหารถที่ "ใกล้ที่สุด" จาก seed แทน (ใช้ระยะทางถนนจริงถ้าเปิดใช้งาน)
        for idx, s in stops.iterrows():
            if s['is_locked']:
                orig = s['orig_truck']
                if orig in active_trucks and orig != base_t:
                    assigned = orig
                else:
                    best_t, best_d = None, float('inf')
                    for t in active_trucks:
                        ref_lat, ref_lon = seeds.get(t, (branch_lat, branch_lon))
                        d = get_dist(idx, t, s['lat'], s['lon'], ref_lat, ref_lon)
                        if d < best_d:
                            best_d, best_t = d, t
                    assigned = best_t if best_t else (active_trucks[0] if active_trucks else None)
                stops.at[idx, 'assigned_truck'] = assigned

        current_loads = {t: 0.0 for t in active_trucks}
        for _, s in stops[stops['assigned_truck'].notna()].iterrows():
            t = s['assigned_truck']
            if t in active_trucks: current_loads[t] += s['total_vol']

        # 2. แก้ไข: บั๊กสำคัญที่ทำให้โซนสีปะปน/ทับซ้อนกัน — เดิมให้ "รถแต่ละคันหยิบจุดที่ใกล้ตัวเองที่สุด"
        # ทีละคันสลับกันไปเรื่อยๆ โดยแต่ละคันเทียบระยะห่างจากตัวเองเท่านั้น ไม่เทียบกับคันอื่นเลย
        # ทำให้รถ 2 คันที่ seed อยู่ใกล้กันแย่งหยิบจุดสลับกันไปมาในโซนเดียวกัน (เห็นเป็นสีปนกันเป็นจุดๆ)
        # ตอนนี้เปลี่ยนเป็น: ในแต่ละรอบ หาว่าจุดที่ยังไม่ถูก assign แต่ละจุด "ใกล้คันไหนที่สุดจริงๆ"
        # โดยเทียบกับทุกคันที่ยังมีที่ว่างพร้อมกัน (เหมือนแบ่งเขต Voronoi ที่มีเพดานความจุ) แล้วเรียง
        # จากคู่ (จุด, คัน) ที่ใกล้กันที่สุดไปไกลสุดก่อนค่อยจัดสรรจริง ลดการแย่ง/กระโดดข้ามโซนกัน
        # PRIORITY 4: ใช้ tolerance_units (จาก % ค่าเผื่อที่ตั้งในไซด์บาร์) แทนเลข +10 ตายตัวเดิม
        MAX_ROUNDS = 60
        for _round in range(MAX_ROUNDS):
            eligible_trucks = [t for t in active_trucks if targets.get(t, 0.0) > current_loads[t]]
            if not eligible_trucks:
                break

            centroids = {}
            for t in active_trucks:
                t_assigned = stops[stops['assigned_truck'] == t]
                if t_assigned.empty:
                    centroids[t] = seeds.get(t, (branch_lat, branch_lon))
                else:
                    centroids[t] = (t_assigned['lat'].mean(), t_assigned['lon'].mean())

            candidate_indices = stops[stops['assigned_truck'].isna()].index
            if len(candidate_indices) == 0:
                break

            scored = []
            for idx in candidate_indices:
                s_row = stops.loc[idx]
                best_t, best_d = None, float('inf')
                for t in eligible_trucks:
                    if current_loads[t] + s_row['total_vol'] > targets[t] + tolerance_units:
                        continue
                    d = get_dist(idx, t, s_row['lat'], s_row['lon'], centroids[t][0], centroids[t][1])
                    if d < best_d:
                        best_d, best_t = d, t
                if best_t is not None:
                    scored.append((best_d, idx, best_t))

            if not scored:
                break

            scored.sort(key=lambda x: x[0])

            assigned_any = False
            for _, idx, t in scored:
                if pd.notna(stops.at[idx, 'assigned_truck']):
                    continue
                s_row = stops.loc[idx]
                if current_loads[t] + s_row['total_vol'] > targets[t] + tolerance_units:
                    continue  # เต็มไปแล้วระหว่างรอบนี้ รอบหน้าจะหาคันที่ใกล้รองลงมาให้ใหม่
                stops.at[idx, 'assigned_truck'] = t
                current_loads[t] += s_row['total_vol']
                assigned_any = True

            if not assigned_any: break

        # แก้ไข: เดิมจุดที่เหลือ (assign แบบพอดีเป๊ะไม่ได้เพราะเกิน target+tolerance ทุกคัน) จะถูกโยนเข้า
        # Overflow ทันทีโดยไม่ลองทางเลือกอื่น ทั้งที่รถบางคันอาจมีที่ว่างเหลือพอสมควร (แค่ไม่ถึงขนาดพอดี)
        # ตอนนี้เพิ่ม fallback pass: ลองใส่จุดที่เหลือให้รถที่มี "ที่ว่างเหลือมากที่สุด" (best-fit แบบผ่อนปรน)
        # ก่อนจะยอมให้ตกเป็น Overflow จริงๆ
        remaining = stops[stops['assigned_truck'].isna()].index.tolist()
        for idx in remaining:
            s_row = stops.loc[idx]
            eligible = [t for t in active_trucks if targets.get(t, 0.0) > 0.0]
            if not eligible:
                continue
            best_t = max(eligible, key=lambda t: targets[t] - current_loads[t])
            headroom = targets[best_t] - current_loads[best_t]
            # ยอมให้เกิน target ได้ไม่เกิน 20% ของความจุมาตรฐาน เพื่อไม่ทิ้งลูกค้าไปกองไว้เฉยๆ ถ้าพอมีที่ว่างเหลือบ้าง
            if headroom > -0.2 * MONTHLY_CAPACITY_PER_TRUCK:
                stops.loc[idx, 'assigned_truck'] = best_t
                current_loads[best_t] += s_row['total_vol']

        # จุดที่ยังเหลือแม้ fallback แล้วก็ยังไม่มีที่ไปจริงๆ ให้ปัดไป Overflow
        stops.loc[stops['assigned_truck'].isna(), 'assigned_truck'] = OVERFLOW_LABEL

        stop_to_truck = dict(zip(stops['coord_key'], stops['assigned_truck']))
        opt_df['เบอร์รถใหม่'] = opt_df['coord_key'].map(stop_to_truck)

        opt_df['สถานะ'] = np.where(opt_df[truck_col] == opt_df['เบอร์รถใหม่'], 'คงเดิม', 'ย้ายไปสาย ' + opt_df['เบอร์รถใหม่'])
        opt_df.loc[opt_df['is_locked'], 'สถานะ'] = opt_df.loc[opt_df['is_locked'], 'สถานะ'] + ' 🔒'

        # PRIORITY 3: เกลี่ยวันจัดส่งรายวันภายในแต่ละคัน (ไม่ย้ายข้ามคัน ไม่แตะจุดที่ล็อก)
        opt_df, daily_matrix, final_daily = smooth_daily_loads(opt_df, active_trucks)

        return opt_df, daily_matrix, final_daily, targets, current_loads

    st.sidebar.markdown("---")
    if st.sidebar.button("🚀 ประมวลผลตัดสายส่ง", use_container_width=True):
        if not new_truck_name and base_truck == "(ไม่มี - เพิ่มรถคันใหม่กระจายงาน)":
            st.sidebar.error("❌ กรุณาระบุชื่อเบอร์รถคันใหม่ก่อนประมวลผล")
            st.stop()
            
        calc_placeholder = st.empty()
        loader_msg = "กำลังประมวลผลจัดสรรเส้นทาง Unified Pool Architecture... 💧"
        if use_road_distance:
            loader_msg += " (กำลังเรียก API ระยะทางถนนจริง อาจใช้เวลาสักครู่)"
        try:
            with open("truck.jpg", "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode()
            loader_html = f'''<div class="custom-truck-loader"><img src="data:image/jpeg;base64,{encoded_string}" alt="รถกำลังวิ่ง..."><br>{loader_msg}</div>'''
        except FileNotFoundError:
            loader_html = f'<div class="custom-truck-loader">{loader_msg}</div>'
            
        calc_placeholder.markdown(loader_html, unsafe_allow_html=True)
        
        res_df, daily_matrix, final_daily, targets_used, loads_used = run_unified_pool_zoning(
            df, base_truck, new_truck_name, target_pcts, manual_vips, core_ratio_pct, tolerance_pct,
            use_road_distance, road_provider, osrm_url, google_api_key
        )
        st.session_state['result_df'] = res_df
        st.session_state['daily_matrix'] = daily_matrix
        st.session_state['final_daily'] = final_daily
        st.session_state['targets_used'] = targets_used
        time.sleep(0.5) 
        calc_placeholder.empty()

    if 'result_df' in st.session_state:
        res_df = st.session_state['result_df']
        daily_matrix = st.session_state['daily_matrix']
        all_trucks_after = sorted(res_df['เบอร์รถใหม่'].dropna().unique().tolist())
        if new_truck_name and new_truck_name not in all_trucks_after: all_trucks_after.append(new_truck_name)

        # แก้ไข: เพิ่มสรุปสั้นๆ ว่ามีลูกค้าตกไป Overflow กี่รายและกี่ถัง จะได้เห็นชัดเจนทันทีว่ามีปัญหาไหม
        overflow_df = res_df[res_df['เบอร์รถใหม่'] == OVERFLOW_LABEL]
        if not overflow_df.empty:
            st.error(f"🚨 มีลูกค้า {len(overflow_df)} ราย ({overflow_df[vol_col].sum():,.0f} ถัง/เดือน) จัดสรรเข้ารถคันใดไม่ได้เลย ('{OVERFLOW_LABEL}') — ลองเพิ่ม % เป้าหมายของรถบางคัน หรือเพิ่มรถ")

        st.markdown("### 📊 สรุปภาพรวมยอดการจัดส่ง")
        col1, col2 = st.columns(2)
        sum_before = df.groupby(truck_col).agg(จำนวนสมาชิก=pd.NamedAgg(column=truck_col, aggfunc='count'), **{'ยอดรับน้ำ(ถัง/เดือน)': pd.NamedAgg(column=vol_col, aggfunc='sum')}).reset_index()
        sum_after = res_df.groupby('เบอร์รถใหม่').agg(จำนวนสมาชิก=pd.NamedAgg(column='เบอร์รถใหม่', aggfunc='count'), **{'ยอดรับน้ำ(ถัง/เดือน)': pd.NamedAgg(column=vol_col, aggfunc='sum')}).reset_index()
        sum_after['ปริมาณงาน(%)'] = np.where(
            sum_after['เบอร์รถใหม่'] == OVERFLOW_LABEL,
            '-', 
            (sum_after['ยอดรับน้ำ(ถัง/เดือน)'] / MONTHLY_CAPACITY_PER_TRUCK * 100).round(1).astype(str) + '%'
        )

        # PRIORITY 4: แสดงส่วนต่างระหว่าง % เป้าหมายบนสไลเดอร์ กับ % ที่ทำได้จริง พร้อมสถานะ
        # ว่าอยู่ในค่าเผื่อ (tolerance) ที่ตั้งไว้หรือไม่ — เพราะ VIP/Core Lock อาจทำให้ตรงเป๊ะไม่ได้เสมอไป
        targets_used = st.session_state.get('targets_used', {})
        delta_rows = []
        for t, tgt in targets_used.items():
            actual = res_df[res_df['เบอร์รถใหม่'] == t][vol_col].sum()
            tgt_pct = tgt / MONTHLY_CAPACITY_PER_TRUCK * 100
            actual_pct = actual / MONTHLY_CAPACITY_PER_TRUCK * 100
            gap_pct = actual_pct - tgt_pct
            within_tol = abs(gap_pct) <= tolerance_pct
            delta_rows.append({
                'เบอร์รถ': t, 'เป้าหมาย(%)': round(tgt_pct, 1), 'ทำได้จริง(%)': round(actual_pct, 1),
                'ส่วนต่าง(%)': round(gap_pct, 1), 'อยู่ในค่าเผื่อ': '✅' if within_tol else '⚠️ เกินค่าเผื่อ'
            })
        if delta_rows:
            st.markdown("##### 🎯 เทียบเป้าหมายสไลเดอร์ vs ผลจริง (Priority 4: Strict Target Matching)")
            st.dataframe(pd.DataFrame(delta_rows), use_container_width=True)

        with col1:
            st.markdown("**ก่อนปรับโครงสร้างสายส่ง**")
            st.dataframe(sum_before, use_container_width=True)
        with col2:
            st.markdown("**หลังปรับโครงสร้าง (Unified Pool Zoning)**")
            st.dataframe(sum_after, use_container_width=True)
            
        st.markdown("### 🗺️ แผนที่เปรียบเทียบการกระจายตัว (เชิงพื้นที่)")
        map_trucks_view = [t for t in all_trucks_after if t != OVERFLOW_LABEL]
        view_options = ["แสดงทั้งหมด (แยกสีตามเบอร์รถ)"] + map_trucks_view
        
        col_filter, _ = st.columns([1, 1])
        with col_filter: selected_view = st.selectbox("🔍 เลือกรูปแบบการแสดงผลบนแผนที่:", options=view_options)

        day_color_map = {'จันทร์': '#FFD700', 'อังคาร': '#FF69B4', 'พุธ': '#28A745', 'พฤหัสบดี': '#FD7E14', 'ศุกร์': '#00BFFF', 'เสาร์': '#6F42C1', 'อาทิตย์': '#DC3545'}
        standard_palette = ['blue', 'green', 'orange', 'purple', 'darkblue', 'cadetblue', 'pink']
        color_map = {str(t): standard_palette[i % len(standard_palette)] for i, t in enumerate(map_trucks_view) if str(t) != new_truck_name}
        color_map[new_truck_name] = 'red' 

        if selected_view == "แสดงทั้งหมด (แยกสีตามเบอร์รถ)":
            map_df_before, map_df_after = df, res_df[res_df['เบอร์รถใหม่'] != OVERFLOW_LABEL]
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
            st.markdown("<div style='text-align:center; color:#FFD700; font-weight:bold; margin-bottom:8px;'>โซนการวิ่งสายใหม่ (Unified Zoning)</div>", unsafe_allow_html=True)
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

        st.markdown("### 📅 ตารางวิเคราะห์โหลดรายวัน (จันทร์-เสาร์)")
        st.caption(f"🟢 เหมาะสม {OPTIMAL_MIN}-{OPTIMAL_MAX} | 🟡 ควรเลี่ยง {AVOID_MIN}-{AVOID_MAX} | 🔴 เกินเพดาน >{MAX_DAY_CAP} | 🚚 รอบ 3 (ยอมรับ) {ESCALATE_TARGET_MIN}-{ESCALATE_TARGET_MAX}")

        def day_status(v):
            if v > ESCALATE_THRESHOLD: return "🚚 รอบ3"
            if v > MAX_DAY_CAP: return "🔴 เกิน"
            if OPTIMAL_MIN <= v <= OPTIMAL_MAX: return "🟢 เหมาะสม"
            if AVOID_MIN <= v <= AVOID_MAX: return "🟡 เลี่ยง"
            return ""

        daily_summary = []
        for t in all_trucks_after:
            if t == OVERFLOW_LABEL: continue
            t_mask = res_df['เบอร์รถใหม่'] == t
            t_daily = daily_matrix[t_mask].sum(axis=0) if t_mask.any() else np.zeros(6)
            max_load = max(t_daily) if len(t_daily) else 0
            daily_summary.append({
                'เบอร์รถ': t,
                'จันทร์': int(round(t_daily[0])),
                'อังคาร': int(round(t_daily[1])),
                'พุธ': int(round(t_daily[2])),
                'พฤหัสฯ': int(round(t_daily[3])),
                'ศุกร์': int(round(t_daily[4])),
                'เสาร์': int(round(t_daily[5])),
                'โหลดสูงสุด (ถัง/วัน)': int(round(max_load)),
                'สถานะ': day_status(max_load)
            })
        st.dataframe(pd.DataFrame(daily_summary), use_container_width=True)

        st.markdown("### 📋 รายละเอียดข้อมูลการโยกย้ายสมาชิก")
        final_cols = [id_col]
        if name_col and name_col in res_df.columns: final_cols.append(name_col)
        final_cols.extend([day_col, 'วันจัดส่ง(ใหม่)', 'สถานะการย้ายวัน', vol_col, truck_col, 'เบอร์รถใหม่', 'สถานะ'])

        detail_df = res_df.copy()
        detail_df['เบอร์รถเดิม (ก่อนปรับ)'] = detail_df[truck_col]
        detail_df = detail_df[[c for c in final_cols if c in detail_df.columns]].rename(columns={truck_col: 'เบอร์รถเดิม (ก่อนปรับ)', day_col: 'วันจัดส่ง(เดิม)'})
        st.dataframe(detail_df, use_container_width=True)
        
        st.markdown("---")
        st.markdown("<div style='text-align:center; margin-bottom: 10px;'><b>📌 เมื่อผลลัพธ์สมบูรณ์แบบแล้ว สามารถดาวน์โหลดข้อมูลไปใช้งานได้ทันที</b></div>", unsafe_allow_html=True)
        
        @st.cache_data
        def convert_df_to_bytes(input_df): return input_df.to_csv(index=False).encode('utf-8-sig')

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
