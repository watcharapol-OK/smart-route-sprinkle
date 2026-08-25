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
    keys_to_clear = ['result_df', 'daily_matrix']
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]

st.markdown('''
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;600&display=swap');
        html, body, [class*="css"] { font-family: 'Sarabun', sans-serif; }
        .stApp { background-color: #F8F9FA; }
        h1, h2, h3 { color: #002D62 !important; font-weight: 600; text-shadow: 1px 1px 2px rgba(0,0,0,0.05); }
        [data-testid="stSidebar"] { background-color: #001F3F !important; border-right: 2px solid #D4AF37; }
        [data-testid="stSidebar"] * { color: #E8EEF2 !important; }
        [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { color: #D4AF37 !important; }
        div[data-baseweb="select"] > div, input { background-color: #003366 !important; border: 1px solid #557A95 !important; color: white !important;}
        .stButton>button { background-color: #D4AF37 !important; color: #001F3F !important; border: none !important; border-radius: 4px; font-weight: 600; padding: 0.5rem 2rem; width: 100%; transition: all 0.3s ease; }
        .stButton>button:hover { background-color: #F3E5AB !important; box-shadow: 0 4px 8px rgba(212, 175, 55, 0.4); transform: translateY(-2px); }
        div[data-testid="stVerticalBlock"] > div.element-container { background-color: transparent; }
        .stDataFrame { background-color: white; padding: 1rem; border-radius: 8px; box-shadow: 0 4px 10px rgba(0,0,0,0.08); border-top: 4px solid #002D62; }
        #MainMenu {visibility: hidden;} footer {visibility: hidden;}
        
        .stSpinner > div > div { display: none !important; }
        @keyframes drive { 0% { transform: translateX(-100%); } 50% { transform: translateX(100%); } 100% { transform: translateX(-100%); } }
        .custom-truck-loader { text-align: center; padding: 2rem; color: #002D62; font-weight: bold; font-size: 1.2rem; overflow: hidden; border-radius: 10px; background-color: #E8F4F8; border: 2px dashed #002D62; margin-bottom: 20px; }
        .custom-truck-loader img { width: 150px; animation: drive 3s infinite ease-in-out; }
        
        [data-testid="stDownloadButton"] > button { background-color: #28A745 !important; color: white !important; border: none !important; padding: 0.8rem 2rem; font-size: 1.1rem; }
        [data-testid="stDownloadButton"] > button:hover { background-color: #218838 !important; box-shadow: 0 4px 8px rgba(40, 167, 69, 0.4); }
    </style>
''', unsafe_allow_html=True)

st.title("🚛 Smart Route Rebalancer Dashboard")
st.markdown("**ระบบวิเคราะห์และตัดสายส่งน้ำอัตโนมัติ (Strict Compact Patch & Baseline Model)**")

st.sidebar.markdown("### 📁 1. นำเข้าข้อมูล (Data Source)")
sheet_url = st.sidebar.text_input("🔗 ลิงก์ Google Sheets:", placeholder="วางลิงก์ที่นี่...", on_change=reset_results)
sheet_gid = st.sidebar.text_input("แท็บชีต (GID):", value="0", on_change=reset_results)

@st.cache_data(ttl=300)
def load_data_from_sheet(url, gid):
    try:
        match = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
        if not match: return None, "ลิงก์ Google Sheets ไม่ถูกต้อง"
        sheet_id = match.group(1)
        export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
        df = pd.read_csv(export_url, dtype=str) # บังคับอ่านเป็น String ทั้งหมดเพื่อป้องกันเบอร์รถเพี้ยน
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
            loader_html = f'''<div class="custom-truck-loader"><img src="data:image/jpeg;base64,{encoded_string}" alt="รถกำลังวิ่ง..."><br>กำลังโหลดข้อมูลต้นฉบับ... 💦</div>'''
        except FileNotFoundError:
            loader_html = '<div class="custom-truck-loader">กำลังโหลดข้อมูล...</div>'
            
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

    # แปลงชนิดข้อมูลให้ถูกต้อง
    df[lat_col] = pd.to_numeric(df[lat_col], errors='coerce')
    df[lon_col] = pd.to_numeric(df[lon_col], errors='coerce')
    df[vol_col] = pd.to_numeric(df[vol_col], errors='coerce').fillna(0.0)
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
    new_truck_name = st.sidebar.text_input("ตั้งชื่อเบอร์รถคันใหม่", value="15112", on_change=reset_results)

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🎛️ 4. ปรับเป้าหมายรายวัน (%)")
    st.sidebar.caption("100% = 4,160 ถัง/เดือน (คำนวณจากยอดจริงของแต่ละคันเทียบฐานมาตรฐาน)")

    active_trucks = [t for t in available_trucks if t != base_truck]
    if new_truck_name not in active_trucks: active_trucks.append(new_truck_name)

    # 📌 เซ็ตค่าเริ่มต้นเปอร์เซ็นต์จากยอดจริงในชีต (ยอดจริง / 4160 * 100) อย่างแม่นยำ
    if 'slider_init' not in st.session_state or st.session_state.get('base_truck') != base_truck or st.session_state.get('new_truck') != new_truck_name:
        st.session_state.truck_pcts = {}
        for t in active_trucks:
            if t == new_truck_name and t not in available_trucks:
                st.session_state.truck_pcts[t] = 0.0
            else:
                actual_vol = df[df[truck_col] == t][vol_col].sum()
                st.session_state.truck_pcts[t] = float(round((actual_vol / 4160.0) * 100, 1))
                    
        for t in active_trucks:
            st.session_state[f"slider_{t}"] = float(round(st.session_state.truck_pcts[t], 1))
            
        st.session_state['slider_init'] = True
        st.session_state['base_truck'] = base_truck
        st.session_state['new_truck'] = new_truck_name

    target_pcts = {}
    for t in active_trucks:
        col_s1, col_s2 = st.sidebar.columns([3, 1.2])
        with col_s2:
            st.markdown("<div style='margin-top: 32px;'></div>", unsafe_allow_html=True)
            st.checkbox("🔒 ล็อก", key=f"lock_{t}", on_change=reset_results)
        with col_s1:
            if f"slider_{t}" not in st.session_state:
                st.session_state[f"slider_{t}"] = st.session_state.truck_pcts.get(t, 100.0)
            val = st.slider(
                f"รถ {t} (%)", 
                min_value=0.0, 
                max_value=200.0, 
                step=0.1, 
                key=f"slider_{t}"
            )
            target_pcts[t] = val
            st.session_state.truck_pcts[t] = val

    locked_ui_trucks = [t for t in active_trucks if st.session_state.get(f"lock_{t}", False)]

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🔒 5. ล็อก Key Account")
    manual_vips = st.sidebar.multiselect("เลือกรหัสสมาชิกที่ห้ามย้ายสาย", options=df[id_col].unique().tolist(), default=[], on_change=reset_results)

    def parse_days_from_string(val_str):
        val = str(val_str).strip().replace(' ', '').lower()
        days = set()
        if 'ทุกวัน' in val or 'จ-ส' in val or 'จันทร์-เสาร์' in val: return [0, 1, 2, 3, 4, 5]
        if re.search(r'(จันทร์|จ\.|^จ$|^จ,|,จ,|,จ$|1)', val): days.add(0)
        if re.search(r'(อังคาร|อ\.|^อ$|^อ,|,อ,|,อ$|2)', val): days.add(1)
        val_no_thu = val.replace('พฤ', '')
        if re.search(r'(พุธ|พ\.|^พ$|^พ,|,พ,|,พ$|3)', val_no_thu): days.add(2)
        if re.search(r'(พฤหัส|พฤ|4)', val): days.add(3)
        if re.search(r'(ศุกร์|ศ\.|^ศ$|^ศ,|,ศ,|,ศ$|5)', val): days.add(4)
        if re.search(r'(เสาร์|ส\.|^ส$|^ส,|,ส,|,ส$|6)', val): days.add(5)
        d_list = list(days)
        return d_list if d_list else [0, 1, 2, 3, 4, 5]

    def format_days_to_string(days_list):
        if not days_list: return "ไม่ระบุ"
        day_names = {0:'จันทร์', 1:'อังคาร', 2:'พุธ', 3:'พฤหัสฯ', 4:'ศุกร์', 5:'เสาร์'}
        if len(days_list) == 6: return 'จ-ส'
        return ', '.join([day_names[d] for d in sorted(days_list)])

    def get_daily_vols(data_df):
        daily_matrix = np.zeros((len(data_df), 6)) 
        for i, row in data_df.iterrows():
            vol = row[vol_col]
            val = str(row.get(day_col, ''))
            days = parse_days_from_string(val)
            vol_per_day = vol / (len(days) * 4.333) 
            for d in days: daily_matrix[i, d] = vol_per_day
        return daily_matrix

    # ---------------------------------------------------------
    # สมองกลหลัก: Compact Patch Allocation
    # ---------------------------------------------------------
    def run_compact_patch_allocation(data, base_t, new_t, pct_dict, manual_locks):
        opt_df = data.copy()
        opt_df['เบอร์รถใหม่'] = opt_df[truck_col].values
        opt_df['วันจัดส่ง(ใหม่)'] = opt_df[day_col].values
        
        locked_manual = [str(x).strip() for x in manual_locks]
        opt_df['is_locked'] = (opt_df['VIP_Status'].str.upper().str.strip() == 'VIP') | (opt_df[id_col].str.strip().isin(locked_manual))
        
        has_base = base_t != "(ไม่มี - เพิ่มรถคันใหม่กระจายงาน)"
        active_trucks = [t for t in available_trucks if t != base_t]
        if new_t not in active_trucks: active_trucks.append(new_t)
            
        targets = {t: math.floor(4160 * (pct_dict.get(t, 100) / 100)) for t in active_trucks}
        if has_base: targets[base_t] = 0
        
        vols = opt_df[vol_col].values
        coords = opt_df[[lat_col, lon_col]].values
        
        if has_base:
            base_mask = (opt_df[truck_col] == base_t) & (~opt_df['is_locked'])
            opt_df.loc[base_mask, 'เบอร์รถใหม่'] = 'POOL'

        centers = {}
        for t in available_trucks:
            if t == base_t: continue
            t_data = opt_df[opt_df[truck_col] == t]
            if not t_data.empty: centers[t] = (np.average(t_data[lat_col]), np.average(t_data[lon_col]))
            
        branch_lat = np.mean(coords[:, 0])
        branch_lon = np.mean(coords[:, 1])
        if new_t not in centers: centers[new_t] = (branch_lat, branch_lon)

        unlocked_indices = np.where(~opt_df['is_locked'].values)[0]
        
        # จัดสรรงานตามเป้าหมายสไลเดอร์
        for iteration in range(2):
            current_loads = {t: opt_df[opt_df['เบอร์รถใหม่'] == t][vol_col].sum() for t in active_trucks}
            remaining_pts = [i for i in unlocked_indices if opt_df.at[i, 'เบอร์รถใหม่'] == 'POOL' or opt_df.at[i, 'เบอร์รถใหม่'] == str(base_t)]
            
            for t in active_trucks:
                target_v = targets.get(t, 0)
                curr_v = current_loads.get(t, 0)
                if curr_v < target_v - 50:
                    needed = target_v - curr_v
                    candidates = [i for i in unlocked_indices if opt_df.at[i, 'เบอร์รถใหม่'] != t]
                    if not candidates: continue
                    c_lat, c_lon = centers.get(t, (branch_lat, branch_lon))
                    cand_coords = coords[candidates]
                    dists = (cand_coords[:, 0] - c_lat)**2 + (cand_coords[:, 1] - c_lon)**2
                    sorted_cand = np.array(candidates)[np.argsort(dists)]
                    
                    taken = 0
                    for idx in sorted_cand:
                        if taken >= needed or current_loads[t] >= target_v: break
                        opt_df.at[idx, 'เบอร์รถใหม่'] = t
                        current_loads[t] += vols[idx]
                        taken += vols[idx]

        unassigned = opt_df[opt_df['เบอร์รถใหม่'] == 'POOL'].index.tolist()
        for idx in unassigned:
            closest_t = min(active_trucks, key=lambda t: (centers[t][0] - opt_df.at[idx, lat_col])**2 + (centers[t][1] - opt_df.at[idx, lon_col])**2)
            opt_df.at[idx, 'เบอร์รถใหม่'] = closest_t

        opt_df['สถานะ'] = np.where(opt_df[truck_col] == opt_df['เบอร์รถใหม่'], 'คงเดิม', 'ย้ายไปสาย ' + opt_df['เบอร์รถใหม่'])
        daily_matrix = get_daily_vols(opt_df)
        
        return opt_df, daily_matrix

    # AI Cluster Day-Shift คำแนะนำตามหลักการโลจิสติกส์จริง
    def get_smart_cluster_day_shift_recommendations(data_df, daily_mat):
        recs = []
        days_str_map = {0: 'จันทร์', 1: 'อังคาร', 2: 'พุธ', 3: 'พฤหัสฯ', 4: 'ศุกร์', 5: 'เสาร์'}
        trucks = data_df['เบอร์รถใหม่'].dropna().unique()
        sim_truck_daily = {t: daily_mat[data_df['เบอร์รถใหม่'] == t].sum(axis=0).copy() for t in trucks}
        
        for t in trucks:
            t_mask = data_df['เบอร์รถใหม่'] == t
            if not t_mask.any(): continue
            for d in range(6):
                load = sim_truck_daily[t][d]
                if 121 <= load <= 139:
                    recs.append({
                        'เบอร์รถ': t, 'วัน': days_str_map[d], 'โหลดปัจจุบัน': round(load, 1),
                        'คำแนะนำ': 'อยู่ในโซนภาระงานน้อยเกินไป (121-139 ถัง) แนะนำเกลี่ยเพิ่มให้อยู่ในช่วง 140-155 ถัง'
                    })
                elif 160 < load < 180:
                    recs.append({
                        'เบอร์รถ': t, 'วัน': days_str_map[d], 'โหลดปัจจุบัน': round(load, 1),
                        'คำแนะนำ': 'เกิน 160 ถังแต่ยังไม่ถึงเกณฑ์คุ้มค่าเที่ยว 3 แนะนำพิจารณาผลักขึ้นไปช่วง 180-190 ถังเพื่อเบิกน้ำเที่ยว 3 (+40 ถัง) หรืออนุโลมตามพื้นที่ซอยเดียวกัน'
                    })
        return pd.DataFrame(recs)

    st.sidebar.markdown("---")
    if st.sidebar.button("🚀 ประมวลผลตัดสายส่ง", use_container_width=True):
        calc_placeholder = st.empty()
        try:
            with open("truck.jpg", "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode()
            loader_html = f'''<div class="custom-truck-loader"><img src="data:image/jpeg;base64,{encoded_string}" alt="รถกำลังวิ่ง..."><br>กำลังประมวลผลจัดสรรเส้นทางตามเป้าหมาย... 🚚💨</div>'''
        except FileNotFoundError:
            loader_html = '<div class="custom-truck-loader">กำลังประมวลผล...</div>'
            
        calc_placeholder.markdown(loader_html, unsafe_allow_html=True)
        
        res_df, daily_matrix = run_compact_patch_allocation(df, base_truck, new_truck_name, target_pcts, manual_vips)
        st.session_state['result_df'] = res_df
        st.session_state['daily_matrix'] = daily_matrix
        time.sleep(0.5) 
        calc_placeholder.empty()

    if 'result_df' in st.session_state:
        res_df = st.session_state['result_df']
        daily_matrix = st.session_state['daily_matrix']
        all_trucks_after = sorted(res_df['เบอร์รถใหม่'].dropna().unique().tolist())
        
        if new_truck_name and new_truck_name not in all_trucks_after:
            all_trucks_after.append(new_truck_name)
        
        st.markdown("### 📊 สรุปภาพรวมยอดการจัดส่ง")
            
        col1, col2 = st.columns(2)
        sum_before = df.groupby(truck_col).agg(จำนวนสมาชิก=pd.NamedAgg(column=truck_col, aggfunc='count'), **{'ยอดรับน้ำ(ถัง/เดือน)': pd.NamedAgg(column=vol_col, aggfunc='sum')}).reset_index()
        sum_after = res_df.groupby('เบอร์รถใหม่').agg(จำนวนสมาชิก=pd.NamedAgg(column='เบอร์รถใหม่', aggfunc='count'), **{'ยอดรับน้ำ(ถัง/เดือน)': pd.NamedAgg(column=vol_col, aggfunc='sum')}).reset_index()
        sum_after['ปริมาณงาน(%)'] = (sum_after['ยอดรับน้ำ(ถัง/เดือน)'] / 4160 * 100).round(1).astype(str) + '%'

        with col1:
            st.markdown("**ก่อนปรับโครงสร้างสายส่ง**")
            st.dataframe(sum_before, use_container_width=True)
        with col2:
            st.markdown("**หลังปรับโครงสร้าง (Compact Patch)**")
            st.dataframe(sum_after, use_container_width=True)
            
        st.markdown("### 📅 ตารางวิเคราะห์โหลดรายวัน (จันทร์-เสาร์)")
            
        daily_summary = []
        for t in all_trucks_after:
            t_mask = res_df['เบอร์รถใหม่'] == t
            t_daily = daily_matrix[t_mask].sum(axis=0) if t_mask.any() else np.zeros(6)
            daily_summary.append({
                'เบอร์รถ': t,
                'จันทร์': round(t_daily[0]),
                'อังคาร': round(t_daily[1]),
                'พุธ': round(t_daily[2]),
                'พฤหัสฯ': round(t_daily[3]),
                'ศุกร์': round(t_daily[4]),
                'เสาร์': round(t_daily[5]),
                'โหลดสูงสุด (ถัง/วัน)': round(max(t_daily))
            })
        st.dataframe(pd.DataFrame(daily_summary), use_container_width=True)
        
        st.markdown("#### 💡 คำแนะนำการบริหารโหลดรายวันตามเกณฑ์โลจิสติกส์จริง")
        recs_df = get_smart_cluster_day_shift_recommendations(res_df, daily_matrix)
        if not recs_df.empty:
            st.dataframe(recs_df, use_container_width=True)
        else:
            st.success("✅ โหลดรายวันทุกวันอยู่ในเกณฑ์เหมาะสมตามมาตรฐาน")

        st.markdown("### 🗺️ แผนที่เปรียบเทียบการกระจายตัว (เชิงพื้นที่)")
        view_options = ["แสดงทั้งหมด (แยกสีตามเบอร์รถ)"] + all_trucks_after
        
        col_filter, _ = st.columns([1, 1])
        with col_filter: selected_view = st.selectbox("🔍 เลือกรูปแบบการแสดงผลบนแผนที่:", options=view_options)

        day_color_map = {'จันทร์': '#FFD700', 'อังคาร': '#FF69B4', 'พุธ': '#28A745', 'พฤหัสบดี': '#FD7E14', 'ศุกร์': '#00BFFF', 'เสาร์': '#6F42C1', 'อาทิตย์': '#DC3545'}
        standard_palette = ['blue', 'green', 'orange', 'purple', 'darkblue', 'cadetblue', 'pink']
        color_map = {str(t): standard_palette[i % len(standard_palette)] for i, t in enumerate(all_trucks_after) if str(t) != new_truck_name}
        color_map[new_truck_name] = 'red' 

        if selected_view == "แสดงทั้งหมด (แยกสีตามเบอร์รถ)":
            map_df_before, map_df_after = df, res_df
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
            st.markdown("<div style='text-align:center; color:#002D62; font-weight:bold;'>โซนการวิ่งรถเดิม (Before - ข้อมูลดิบต้นฉบับ)</div>", unsafe_allow_html=True)
            m1 = folium.Map(location=[c_lat, c_lon], zoom_start=12 if color_mode=='truck' else 14)
            plugins.Fullscreen(position='topright').add_to(m1)
            for _, r in map_df_before.iterrows():
                t_id = str(r[truck_col])
                is_vip = str(r.get('VIP_Status', '')).upper() == 'VIP' or str(r[id_col]) in manual_vips
                m_color = color_map.get(t_id, 'gray') if color_mode == 'truck' else next((c for d, c in day_color_map.items() if d in str(r.get(day_col, '')).strip()), 'gray')
                popup_html = f"<b>รหัส:</b> {r[id_col]}<br><b>ชื่อ:</b> {get_name(r)}<br><b>ยอด:</b> {r[vol_col]} ถัง<br><b>รถ:</b> {t_id}"
                folium.CircleMarker([r[lat_col], r[lon_col]], radius=8 if is_vip else 5, color='#002D62' if is_vip else m_color, weight=2 if is_vip else 1, fill=True, fillColor=m_color, fill_opacity=0.9, popup=folium.Popup(popup_html, max_width=300)).add_to(m1)
            components.html(m1.get_root().render(), height=450)

        with map_col2:
            st.markdown("<div style='text-align:center; color:#002D62; font-weight:bold;'>โซนการวิ่งสายใหม่ (Compact Patch Allocation)</div>", unsafe_allow_html=True)
            m2 = folium.Map(location=[c_lat, c_lon], zoom_start=12 if color_mode=='truck' else 14)
            plugins.Fullscreen(position='topright').add_to(m2)
            for _, r in map_df_after.iterrows():
                t_new = str(r['เบอร์รถใหม่'])
                is_vip = str(r.get('VIP_Status', '')).upper() == 'VIP' or str(r[id_col]) in manual_vips
                
                display_day = str(r.get(day_col, ''))
                m_color = color_map.get(t_new, 'gray') if color_mode == 'truck' else next((c for d, c in day_color_map.items() if d in display_day.strip()), 'gray')
                
                popup_html = f"<b>รหัส:</b> {r[id_col]}<br><b>ชื่อ:</b> {get_name(r)}<br><b>ยอด:</b> {r[vol_col]} ถัง<br><b>รถล่าสุด:</b> {t_new}"
                folium.CircleMarker([r[lat_col], r[lon_col]], radius=8 if is_vip else 5, color='#002D62' if is_vip else m_color, weight=2 if is_vip else 1, fill=True, fillColor=m_color, fill_opacity=0.9, popup=folium.Popup(popup_html, max_width=300)).add_to(m2)
            components.html(m2.get_root().render(), height=450)

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
        def convert_df_to_bytes(df):
            return df.to_csv(index=False).encode('utf-8-sig')

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
