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
    keys_to_clear = ['result_df', 'daily_matrix', 'simulated_df', 'simulated_matrix']
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
st.markdown("**ระบบวิเคราะห์และตัดสายส่งน้ำอัตโนมัติ (Guaranteed New Truck Allocation Model)**")

st.sidebar.markdown("### 📁 1. นำเข้าข้อมูล (Data Source)")
sheet_url = st.sidebar.text_input("🔗 ลิงก์ Google Sheets:", placeholder="วางลิงก์ที่นี่...", on_change=reset_results)

@st.cache_data(ttl=300)
def load_data_from_sheet(url):
    try:
        match = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
        if match:
            sheet_id = match.group(1)
            export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid=0"
            return pd.read_csv(export_url)
        return None
    except Exception: return None

df = None
if sheet_url:
    loading_placeholder = st.empty()
    try:
        with open("truck.jpg", "rb") as image_file:
            encoded_string = base64.b64encode(image_file.read()).decode()
        loader_html = f'''<div class="custom-truck-loader"><img src="data:image/jpeg;base64,{encoded_string}" alt="รถกำลังวิ่ง..."><br>กำลังประมวลผลจัดสรรเส้นทางและรถใหม่... 💦</div>'''
    except FileNotFoundError:
        loader_html = '<div class="custom-truck-loader">กำลังประมวลผล...</div>'
        
    loading_placeholder.markdown(loader_html, unsafe_allow_html=True)
    df = load_data_from_sheet(sheet_url)
    time.sleep(1) 
    loading_placeholder.empty() 

if df is not None and not df.empty:
    vol_col = next((c for c in df.columns if 'ยอด' in str(c) or 'เดือน' in str(c)), df.columns[-1])
    lat_col = next((c for c in df.columns if 'ละติจูด' in str(c) or 'lat' in str(c).lower()), None)
    lon_col = next((c for c in df.columns if 'ลอง' in str(c) or 'lon' in str(c).lower()), None)
    truck_col = next((c for c in df.columns if 'เบอร์รถ' in str(c) or 'รถ' in str(c)), None)
    vip_col = next((c for c in df.columns if 'VIP' in str(c).upper() or 'เงื่อนไข' in str(c)), None)
    id_col = next((c for c in df.columns if 'รหัส' in str(c) or 'ID' in str(c).upper()), df.columns[0])
    name_col = next((c for c in df.columns if 'ชื่อ' in str(c) or 'name' in str(c).lower()), None)
    
    if not lat_col or not lon_col: st.error("❌ ขาดคอลัมน์ พิกัด (ละติจูด/ลองติจูด)"); st.stop()

    df[lat_col] = pd.to_numeric(df[lat_col], errors='coerce')
    df[lon_col] = pd.to_numeric(df[lon_col], errors='coerce')
    df = df.dropna(subset=[lat_col, lon_col]).reset_index(drop=True) 
    df[vol_col] = pd.to_numeric(df[vol_col], errors='coerce').fillna(0)
    df['VIP_Status'] = df[vip_col] if vip_col in df.columns else 'ปกติ'

    st.sidebar.success(f"✅ โหลดข้อมูลสำเร็จ: {len(df)} รายการ")
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚙️ 2. ตั้งค่าคอลัมน์และสายใหม่")
    
    guessed_day = next((c for c in df.columns if 'สัปดาห์' in str(c) or 'วัน' in str(c) or 'รอบ' in str(c) or 'day' in str(c).lower()), df.columns[0])
    day_col = st.sidebar.selectbox("📅 เลือกคอลัมน์ 'วันจัดส่ง':", options=df.columns, index=df.columns.tolist().index(guessed_day) if guessed_day in df.columns else 0, on_change=reset_results)
    
    available_trucks = [str(x) for x in df[truck_col].unique() if str(x) != 'nan']
    base_truck_options = ["(ไม่มี - เพิ่มรถคันใหม่กระจายงาน)"] + available_trucks
    
    base_truck = st.sidebar.selectbox("เลือกรถที่จะถูกยุบ/ดึงงานออก", options=base_truck_options, on_change=reset_results)
    new_truck_name = st.sidebar.text_input("ตั้งชื่อเบอร์รถคันใหม่", value="15112", on_change=reset_results)
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🎛️ 3. ปรับเป้าหมายรายวัน (%) พร้อมปุ่มล็อก")
    st.sidebar.caption("100% = 4,160 ถัง/เดือน (เมื่อปรับเปอร์เซ็นต์ รถที่ไม่ได้ล็อกจะปรับบาลานซ์ให้อัตโนมัติ)")
    
    active_trucks = [t for t in available_trucks if t != base_truck]
    if new_truck_name not in active_trucks:
        active_trucks.append(new_truck_name)
    
    if 'slider_init' not in st.session_state or st.session_state.get('base_truck') != base_truck or st.session_state.get('new_truck') != new_truck_name:
        st.session_state.truck_pcts = {}
        for t in active_trucks:
            if t == new_truck_name and t not in df[truck_col].astype(str).unique():
                st.session_state.truck_pcts[t] = 95.0 # กำหนดค่าตั้งต้นให้รถใหม่มีเป้าหมายชัดเจน
            else:
                vol = df[df[truck_col].astype(str) == t][vol_col].sum()
                st.session_state.truck_pcts[t] = float(round((vol / 4160) * 100, 1))
        
        if base_truck != "(ไม่มี - เพิ่มรถคันใหม่กระจายงาน)":
            base_vol = df[df[truck_col].astype(str) == base_truck][vol_col].sum()
            base_pct = float(round((base_vol / 4160) * 100, 1))
            if len(active_trucks) > 0:
                split = base_pct / len(active_trucks)
                for t in active_trucks:
                    st.session_state.truck_pcts[t] += split
                    
        for t in active_trucks:
            st.session_state[f"slider_{t}"] = float(round(st.session_state.truck_pcts[t], 1))
            
        st.session_state['slider_init'] = True
        st.session_state['base_truck'] = base_truck
        st.session_state['new_truck'] = new_truck_name

    def on_slider_change(changed_truck):
        new_val = st.session_state[f"slider_{changed_truck}"]
        old_val = st.session_state.truck_pcts[changed_truck]
        diff = new_val - old_val
        
        unlocked = [t for t in active_trucks if not st.session_state.get(f"lock_{t}", False) and t != changed_truck]
        
        if len(unlocked) > 0 and abs(diff) > 0.01:
            split_diff = diff / len(unlocked)
            can_move = True
            for t in unlocked:
                if st.session_state.truck_pcts[t] - split_diff < -0.01:
                    can_move = False
                    break
            
            if can_move:
                for t in unlocked:
                    st.session_state.truck_pcts[t] = round(st.session_state.truck_pcts[t] - split_diff, 1)
                    st.session_state[f"slider_{t}"] = st.session_state.truck_pcts[t]
                st.session_state.truck_pcts[changed_truck] = round(new_val, 1)
            else:
                st.session_state[f"slider_{changed_truck}"] = old_val 
        elif len(unlocked) == 0 and abs(diff) > 0.01:
            st.session_state[f"slider_{changed_truck}"] = old_val 
            
        reset_results() 

    target_pcts = {}
    for t in active_trucks:
        col_s1, col_s2 = st.sidebar.columns([3, 1.2])
        with col_s2:
            st.markdown("<div style='margin-top: 32px;'></div>", unsafe_allow_html=True)
            st.checkbox("🔒 ล็อก", key=f"lock_{t}", on_change=reset_results)
        with col_s1:
            if f"slider_{t}" not in st.session_state:
                st.session_state[f"slider_{t}"] = st.session_state.truck_pcts[t]
            val = st.slider(
                f"รถ {t} (%)", 
                min_value=0.0, 
                max_value=200.0, 
                step=0.1, 
                key=f"slider_{t}", 
                on_change=on_slider_change, 
                args=(t,)
            )
            target_pcts[t] = val
            st.session_state.truck_pcts[t] = val

    locked_ui_trucks = [t for t in active_trucks if st.session_state.get(f"lock_{t}", False)]

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🔒 4. ล็อก Key Account")
    manual_vips = st.sidebar.multiselect("เลือกรหัสสมาชิกที่ห้ามย้ายสาย", options=df[id_col].astype(str).unique().tolist(), default=[], on_change=reset_results)

    def parse_days_from_string(val_str):
        val = str(val_str).strip().replace(' ', '').lower()
        days = set()
        if 'ทุกวัน' in val or 'จ-ส' in val or 'จันทร์-เสาร์' in val:
            return [0, 1, 2, 3, 4, 5]
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

    def get_daily_vols(data_df, override_day_col=None):
        col_to_use = override_day_col if override_day_col else day_col
        daily_matrix = np.zeros((len(data_df), 6)) 
        for i, row in data_df.iterrows():
            vol = row[vol_col]
            val = str(row.get(col_to_use, ''))
            days = parse_days_from_string(val)
            vol_per_day = vol / (len(days) * 4.333) 
            for d in days:
                daily_matrix[i, d] = vol_per_day
        return daily_matrix

    # ---------------------------------------------------------
    # สมองกลหลัก: Guaranteed New Truck Allocation (บังคับดึงงานให้รถใหม่เสมอ)
    # ---------------------------------------------------------
    def run_guaranteed_new_truck_allocation(data, base_t, new_t, pct_dict, manual_locks, locked_ui_list):
        opt_df = data.copy()
        opt_df['เบอร์รถใหม่'] = opt_df[truck_col].astype(str)
        opt_df['วันจัดส่ง(ใหม่)'] = opt_df[day_col].astype(str)
        
        locked_manual = [str(x).strip() for x in manual_locks]
        opt_df['is_locked'] = (opt_df['VIP_Status'].astype(str).str.upper().str.strip() == 'VIP') | (opt_df[id_col].astype(str).str.strip().isin(locked_manual))
        
        has_base = base_t != "(ไม่มี - เพิ่มรถคันใหม่กระจายงาน)"
        active_trucks = [t for t in available_trucks if t != base_t]
        if new_t not in active_trucks: active_trucks.append(new_t)
            
        monthly_targets = {t: 4160 * (pct_dict.get(t, 100) / 100) for t in active_trucks}
        vols = opt_df[vol_col].values
        coords = opt_df[[lat_col, lon_col]].values
        
        branch_lat = np.mean(coords[:, 0])
        branch_lon = np.mean(coords[:, 1])
        
        centers = {}
        for t in active_trucks:
            t_data = opt_df[opt_df[truck_col].astype(str) == t]
            if not t_data.empty:
                centers[t] = (np.average(t_data[lat_col]), np.average(t_data[lon_col]))
            else:
                centers[t] = (branch_lat, branch_lon)
                
        if new_t not in centers:
            centers[new_t] = (branch_lat, branch_lon)

        unlocked_indices = np.where(~opt_df['is_locked'].values)[0]
        
        # บังคับดึงงานให้รถใหม่ (new_t) ตามเป้าหมายที่ตั้งไว้ โดยดึงจากขอบรอยต่อของรถอื่น ๆ
        new_truck_target = monthly_targets.get(new_t, 0)
        if new_truck_target > 0:
            candidates = [i for i in unlocked_indices if opt_df.at[i, 'เบอร์รถใหม่'] != new_t]
            if len(candidates) > 0:
                cand_coords = coords[candidates]
                c_new_lat, c_new_lon = centers[new_t]
                dists = (cand_coords[:, 0] - c_new_lat)**2 + (cand_coords[:, 1] - c_new_lon)**2
                sorted_cand = np.array(candidates)[np.argsort(dists)]
                
                taken = 0
                for idx in sorted_cand:
                    if taken >= new_truck_target: break
                    opt_df.at[idx, 'เบอร์รถใหม่'] = new_t
                    taken += vols[idx]

        # ปรับสมดุลโควตาระหว่างรถที่เหลือ
        for iteration in range(25):
            current_loads = {t: opt_df[opt_df['เบอร์รถใหม่'] == t][vol_col].sum() for t in active_trucks}
            over_trucks = [t for t in active_trucks if current_loads[t] > monthly_targets.get(t, 0) + 15 and t != new_t and t not in locked_ui_list]
            under_trucks = [t for t in active_trucks if current_loads[t] < monthly_targets.get(t, 0) - 15 and t not in locked_ui_list]
            
            if not over_trucks or not under_trucks: break
            
            t_over = max(over_trucks, key=lambda t: current_loads[t] - monthly_targets.get(t, 0))
            t_under = min(under_trucks, key=lambda t: current_loads[t] - monthly_targets.get(t, 0))
            
            t_idx = [i for i in unlocked_indices if opt_df.at[i, 'เบอร์รถใหม่'] == t_over]
            if not t_idx: break
            
            t_coords = coords[t_idx]
            c_lat, c_lon = centers[t_over]
            dists = (t_coords[:, 0] - c_lat)**2 + (t_coords[:, 1] - c_lon)**2
            sorted_border = np.array(t_idx)[np.argsort(dists)[::-1]]
            
            opt_df.at[sorted_border[0], 'เบอร์รถใหม่'] = t_under

        # 4. 🔴 HARD-CAP DAILY BALANCER: ควบคุมเพดานรายวันไม่ให้เกิน 190 ถังเด็ดขาด
        MAX_HARD_CAP = 190
        OPTIMAL_CAP = 156
        assigned_days_dict = {idx: parse_days_from_string(opt_df.at[idx, day_col]) for idx in opt_df.index}
        
        for iteration in range(25):
            daily_loads = {t: np.zeros(6) for t in active_trucks}
            for idx in opt_df.index:
                t = opt_df.at[idx, 'เบอร์รถใหม่']
                if t not in active_trucks: continue
                d_list = assigned_days_dict[idx]
                d_vol = vols[idx] / len(d_list) / 4.333
                for d in d_list: daily_loads[t][d] += d_vol
                    
            violation_found = False
            for t in active_trucks:
                for d in range(6):
                    while daily_loads[t][d] > MAX_HARD_CAP:
                        violation_found = True
                        excess_d = daily_loads[t][d] - OPTIMAL_CAP
                        
                        valid_days = [target_d for target_d in range(6) if target_d != d and daily_loads[t][target_d] < MAX_HARD_CAP - 10]
                        if not valid_days: break
                        target_d = min(valid_days, key=lambda target_d: daily_loads[t][target_d])
                        
                        t_indices = [idx for idx in opt_df.index if opt_df.at[idx, 'เบอร์รถใหม่'] == t and not opt_df.at[idx, 'is_locked']]
                        pts_on_day = [idx for idx in t_indices if d in assigned_days_dict[idx]]
                        if not pts_on_day: break
                        
                        c_lat, c_lon = centers.get(t, (branch_lat, branch_lon))
                        dists_from_center = [(opt_df.loc[idx, lat_col] - c_lat)**2 + (opt_df.loc[idx, lon_col] - c_lon)**2 for idx in pts_on_day]
                        seed_idx = pts_on_day[np.argmax(dists_from_center)]
                        seed_lat, seed_lon = opt_df.loc[seed_idx, lat_col], opt_df.loc[seed_idx, lon_col]
                        
                        dists_from_seed = [(opt_df.loc[idx, lat_col] - seed_lat)**2 + (opt_df.loc[idx, lon_col] - seed_lon)**2 for idx in pts_on_day]
                        pts_sorted = np.array(pts_on_day)[np.argsort(dists_from_seed)]
                        
                        moved_v = 0
                        item_moved = False
                        for idx in pts_sorted:
                            if moved_v >= excess_d or daily_loads[t][d] <= MAX_HARD_CAP: break
                            v_unit = vols[idx] / len(assigned_days_dict[idx]) / 4.333
                            if daily_loads[t][target_d] + v_unit > MAX_HARD_CAP: continue
                            
                            old_l = assigned_days_dict[idx]
                            new_l = [target_d if x == d else x for x in old_l]
                            assigned_days_dict[idx] = new_l
                            
                            daily_loads[t][d] -= v_unit
                            daily_loads[t][target_d] += v_unit
                            moved_v += v_unit
                            item_moved = True
                        if not item_moved: break
            if not violation_found: break

        for idx in opt_df.index:
            opt_df.at[idx, 'วันจัดส่ง(ใหม่)'] = format_days_to_string(assigned_days_dict[idx])
            
        daily_matrix = np.zeros((len(opt_df), 6))
        for idx in opt_df.index:
            d_list = assigned_days_dict[idx]
            v = vols[idx] / len(d_list) / 4.333
            for d in d_list: daily_matrix[idx, d] = v
            
        return opt_df, daily_matrix, centers

    # 📌 ระบบผู้ช่วยอัจฉริยะ (AI Cluster Day-Shift) ควบคุม Hard Cap ไม่เกิน 190 ถังเด็ดขาด
    def get_smart_cluster_day_shift_recommendations(data_df, daily_mat, centers):
        recs = []
        days_str_map = {0: 'จันทร์', 1: 'อังคาร', 2: 'พุธ', 3: 'พฤหัสฯ', 4: 'ศุกร์', 5: 'เสาร์'}
        trucks = data_df['เบอร์รถใหม่'].dropna().unique()
        
        MAX_SAFE_CAP = 190
        OPTIMAL_CAP = 156
        
        sim_truck_daily = {t: daily_mat[data_df['เบอร์รถใหม่'] == t].sum(axis=0).copy() for t in trucks}
        
        for t in trucks:
            t_mask = data_df['เบอร์รถใหม่'] == t
            if not t_mask.any(): continue
            
            t_indices = data_df[t_mask].index.tolist()
            c_lat, c_lon = centers.get(t, (data_df.loc[t_indices, lat_col].mean(), data_df.loc[t_indices, lon_col].mean()))
            
            while True:
                over_days = [d for d in range(6) if sim_truck_daily[t][d] > OPTIMAL_CAP]
                if not over_days: break
                
                over_days.sort(key=lambda d: sim_truck_daily[t][d], reverse=True)
                d_over = over_days[0]
                excess = sim_truck_daily[t][d_over] - OPTIMAL_CAP
                
                under_days = [d for d in range(6) if sim_truck_daily[t][d] < OPTIMAL_CAP and (sim_truck_daily[t][d] + excess <= MAX_SAFE_CAP)]
                if not under_days: under_days = [d for d in range(6) if d != d_over and sim_truck_daily[t][d] < MAX_SAFE_CAP]
                if not under_days: break
                
                d_under = min(under_days, key=lambda d: sim_truck_daily[t][d])
                capacity_available = MAX_SAFE_CAP - sim_truck_daily[t][d_under]
                target_move = min(excess, capacity_available)
                if target_move <= 0: break
                
                already_rec_idx = [r['index'] for r in recs]
                pts_on_over_day = [idx for idx in t_indices if daily_mat[idx][d_over] > 0 and not data_df.loc[idx, 'is_locked'] and idx not in already_rec_idx]
                if not pts_on_over_day: break
                
                dists_from_center = [(data_df.loc[idx, lat_col] - c_lat)**2 + (data_df.loc[idx, lon_col] - c_lon)**2 for idx in pts_on_over_day]
                seed_idx = pts_on_over_day[np.argmax(dists_from_center)]
                seed_lat, seed_lon = data_df.loc[seed_idx, lat_col], data_df.loc[seed_idx, lon_col]
                
                dists_from_seed = [(data_df.loc[idx, lat_col] - seed_lat)**2 + (data_df.loc[idx, lon_col] - seed_lon)**2 for idx in pts_on_over_day]
                pts_sorted = np.array(pts_on_over_day)[np.argsort(dists_from_seed)]
                
                shifted_vol = 0
                for idx in pts_sorted:
                    if shifted_vol >= target_move: break
                    vol = daily_mat[idx][d_over]
                    
                    if sim_truck_daily[t][d_under] + vol > MAX_SAFE_CAP: continue
                    
                    recs.append({
                        'index': idx,
                        'เบอร์รถ': t,
                        'รหัสสมาชิก': data_df.loc[idx, id_col],
                        'ชื่อ': data_df.loc[idx, name_col] if name_col else '',
                        'ยอด(เฉลี่ย/เที่ยว)': round(vol, 1),
                        'วันเดิม': days_str_map[d_over],
                        'แนะนำย้ายไป': days_str_map[d_under],
                        'เหตุผล': f"เกลี่ยโหลดรอยต่อ (ไม่เกิน 190 ถัง)"
                    })
                    
                    sim_truck_daily[t][d_over] -= vol
                    sim_truck_daily[t][d_under] += vol
                    shifted_vol += vol
                    
                if shifted_vol == 0: break
                    
        return pd.DataFrame(recs)

    st.sidebar.markdown("---")
    if st.sidebar.button("🚀 ประมวลผลตัดสายส่ง", use_container_width=True):
        calc_placeholder = st.empty()
        try:
            with open("truck.jpg", "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode()
            loader_html = f'''<div class="custom-truck-loader"><img src="data:image/jpeg;base64,{encoded_string}" alt="รถกำลังวิ่ง..."><br>กำลังประมวลผลจัดสรรเส้นทางและรถใหม่... 🚚💨</div>'''
        except FileNotFoundError:
            loader_html = '<div class="custom-truck-loader">กำลังประมวลผล...</div>'
            
        calc_placeholder.markdown(loader_html, unsafe_allow_html=True)
        
        res_df, daily_matrix, route_centers = run_guaranteed_new_truck_allocation(df, base_truck, new_truck_name, target_pcts, manual_vips, locked_ui_trucks)
        st.session_state['result_df'] = res_df
        st.session_state['daily_matrix'] = daily_matrix
        st.session_state['route_centers'] = route_centers
        
        if 'simulated_df' in st.session_state: del st.session_state['simulated_df']
        if 'simulated_matrix' in st.session_state: del st.session_state['simulated_matrix']
        time.sleep(0.5) 
        calc_placeholder.empty()

    if 'result_df' in st.session_state:
        res_df = st.session_state['result_df']
        daily_matrix = st.session_state['daily_matrix']
        route_centers = st.session_state.get('route_centers', {})
        all_trucks_after = sorted(res_df['เบอร์รถใหม่'].dropna().unique().tolist())
        
        # บังคับเพิ่มชื่อรถใหม่ลงไปในลิสต์แสดงผลเสมอแม้ว่าตอนแรกจะยังไม่ได้รันข้อมูลเต็มที่
        if new_truck_name and new_truck_name not in all_trucks_after:
            all_trucks_after.append(new_truck_name)
        
        active_res_df = st.session_state.get('simulated_df', res_df)
        active_matrix = st.session_state.get('simulated_matrix', daily_matrix)
        
        st.markdown("### 📊 สรุปภาพรวมยอดการจัดส่ง")
        if 'simulated_df' in st.session_state:
            st.info("🧪 **แสดงผลลัพธ์จำลอง (After Simulation)** - ตารางโหลดรายวันถูกอัปเดตตามการย้ายวันโดยควบคุมเพดานสูงสุดไม่เกิน 190 ถังเรียบร้อยแล้ว")
            
        col1, col2 = st.columns(2)
        
        sum_before = df.groupby(truck_col).agg(จำนวนสมาชิก=pd.NamedAgg(column=truck_col, aggfunc='count'), **{'ยอดรับน้ำ(ถัง/เดือน)': pd.NamedAgg(column=vol_col, aggfunc='sum')}).reset_index()
        sum_after = active_res_df.groupby('เบอร์รถใหม่').agg(จำนวนสมาชิก=pd.NamedAgg(column='เบอร์รถใหม่', aggfunc='count'), **{'ยอดรับน้ำ(ถัง/เดือน)': pd.NamedAgg(column=vol_col, aggfunc='sum')}).reset_index()
        sum_after['ปริมาณงาน(%)'] = (sum_after['ยอดรับน้ำ(ถัง/เดือน)'] / 4160 * 100).round(1).astype(str) + '%'

        with col1:
            st.markdown("**ก่อนปรับโครงสร้างสายส่ง**")
            st.dataframe(sum_before, use_container_width=True)
        with col2:
            st.markdown("**หลังปรับโครงสร้าง (Guaranteed New Truck Allocation)**")
            st.dataframe(sum_after, use_container_width=True)
            
        st.markdown("### 📅 ตารางวิเคราะห์โหลดรายวัน (จันทร์-เสาร์)")
            
        daily_summary = []
        for t in all_trucks_after:
            t_mask = active_res_df['เบอร์รถใหม่'] == t
            t_daily = active_matrix[t_mask].sum(axis=0) if t_mask.any() else np.zeros(6)
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
        
        max_all_days = max([row['โหลดสูงสุด (ถัง/วัน)'] for row in daily_summary]) if daily_summary else 0
        if max_all_days > 190 and 'simulated_df' not in st.session_state:
            st.error(f"🚨 **ระบบตรวจพบโหลดเกินขีดจำกัดสูงสุด 190 ถัง ({max_all_days} ถัง/วัน)!** \n\nโปรดคลิกปุ่ม **'จำลองผลลัพธ์'** ด้านล่าง เพื่อให้ระบบช่วยเกลี่ยวันจัดส่งสำหรับลูกค้ากลุ่มขอบพื้นที่ตามคำแนะนำครับ")
        elif max_all_days > 156 and 'simulated_df' not in st.session_state:
            st.warning(f"⚠️ **โหลดบางวันเกินมาตรฐาน 156 ถัง (สูงสุด {max_all_days} ถัง)** แต่ยังอยู่ในเกณฑ์อนุโลมวิ่งเที่ยว 3 (ไม่เกิน 190 ถัง)")
        elif 'simulated_df' not in st.session_state:
            st.success("✅ **สมบูรณ์แบบ:** โหลดรายวันอยู่ในโซนคุ้มค่ามาตรฐาน (<= 156 ถัง) และอาณาเขตพื้นที่ไม่ทับซ้อนกัน 100%")
        
        st.markdown("#### 💡 ระบบผู้ช่วยอัจฉริยะ (AI Cluster Day-Shift Optimization)")
        recs_df = get_smart_cluster_day_shift_recommendations(res_df, daily_matrix, route_centers)
        
        if not recs_df.empty and 'simulated_df' not in st.session_state:
            st.warning("รายการลูกค้ารอยต่อพื้นที่ ที่แนะนำให้เจรจาสลับวัน (ควบคุมไม่ให้วันปลายทางพุ่งเกิน 190 ถังเด็ดขาด):")
            st.dataframe(recs_df[['เบอร์รถ', 'รหัสสมาชิก', 'ชื่อ', 'ยอด(เฉลี่ย/เที่ยว)', 'วันเดิม', 'แนะนำย้ายไป', 'เหตุผล']], use_container_width=True)
            
            if st.button("🧪 จำลองผลลัพธ์หลังเจรจาย้ายวันเป็นกลุ่ม (What-If Simulation)"):
                sim_df = res_df.copy()
                sim_col_name = day_col + '_simulated'
                sim_df[sim_col_name] = sim_df[day_col].astype(str)
                days_str_map = {0: 'จันทร์', 1: 'อังคาร', 2: 'พุธ', 3: 'พฤหัสฯ', 4: 'ศุกร์', 5: 'เสาร์'}
                
                current_sim_matrix = get_daily_vols(sim_df, override_day_col=sim_col_name)
                
                for _, r in recs_df.iterrows():
                    idx = r['index']
                    t = sim_df.at[idx, 'เบอร์รถใหม่']
                    target_day_str = r['แนะนำย้ายไป']
                    old_day_str = r['วันเดิม']
                    
                    old_d_int = {v: k for k, v in days_str_map.items()}.get(old_day_str)
                    new_d_int = {v: k for k, v in days_str_map.items()}.get(target_day_str)
                    
                    if old_d_int is not None and new_d_int is not None:
                        t_mask = sim_df['เบอร์รถใหม่'] == t
                        t_daily_loads = current_sim_matrix[t_mask].sum(axis=0)
                        customer_vol = current_sim_matrix[idx][old_d_int]
                        
                        if t_daily_loads[new_d_int] + customer_vol <= 190:
                            current_days_str = str(sim_df.at[idx, sim_col_name])
                            current_list = parse_days_from_string(current_days_str)
                            new_list = [new_d_int if d == old_d_int else d for d in current_list]
                            sim_df.at[idx, sim_col_name] = format_days_to_string(list(set(new_list)))
                            
                            current_sim_matrix[idx, old_d_int] = 0
                            current_sim_matrix[idx, new_d_int] = customer_vol
                    
                sim_daily_mat = get_daily_vols(sim_df, override_day_col=sim_col_name)
                sim_df['วันจัดส่ง(ใหม่)'] = sim_df[sim_col_name]
                
                st.session_state['simulated_df'] = sim_df
                st.session_state['simulated_matrix'] = sim_daily_mat
                st.success("✅ จำลองผลลัพธ์สำเร็จ! ตารางโหลดรายวันถูกอัปเดตตามการย้ายวันแบบควบคุมเพดานไม่เกิน 190 ถังเรียบร้อยแล้วครับ")
                st.rerun()
        elif 'simulated_df' in st.session_state:
            st.success("✅ แสดงผลลัพธ์จากการจำลองการย้ายวันเรียบร้อยแล้วครับ")
            if st.button("❌ ล้างผลการจำลอง (Reset Simulation)"):
                del st.session_state['simulated_df']
                del st.session_state['simulated_matrix']
                st.rerun()
        else:
            st.success("✅ ยอดเยี่ยม! โหลดรายวันอยู่ในโซนคุ้มค่าสมบูรณ์แบบ ไม่มีความจำเป็นต้องเจรจาย้ายวันลูกค้า")

        st.markdown("### 🗺️ แผนที่เปรียบเทียบการกระจายตัว (เชิงพื้นที่)")
        view_options = ["แสดงทั้งหมด (แยกสีตามเบอร์รถ)"] + all_trucks_after
        
        col_filter, _ = st.columns([1, 1])
        with col_filter: selected_view = st.selectbox("🔍 เลือกรูปแบบการแสดงผลบนแผนที่:", options=view_options)

        day_color_map = {'จันทร์': '#FFD700', 'อังคาร': '#FF69B4', 'พุธ': '#28A745', 'พฤหัสบดี': '#FD7E14', 'ศุกร์': '#00BFFF', 'เสาร์': '#6F42C1', 'อาทิตย์': '#DC3545'}
        standard_palette = ['blue', 'green', 'orange', 'purple', 'darkblue', 'cadetblue', 'pink']
        color_map = {str(t): standard_palette[i % len(standard_palette)] for i, t in enumerate(all_trucks_after) if str(t) != new_truck_name}
        color_map[new_truck_name] = 'red' 

        if selected_view == "แสดงทั้งหมด (แยกสีตามเบอร์รถ)":
            map_df_before, map_df_after = df, active_res_df
            color_mode = 'truck'
        else:
            if selected_view == new_truck_name and base_truck == "(ไม่มี - เพิ่มรถคันใหม่กระจายงาน)": map_df_before = pd.DataFrame(columns=df.columns) 
            else: map_df_before = df[df[truck_col].astype(str) == (base_truck if selected_view == new_truck_name else selected_view)]
            map_df_after = active_res_df[active_res_df['เบอร์รถใหม่'].astype(str) == selected_view]
            color_mode = 'day'

        c_lat, c_lon = (map_df_after[lat_col].mean(), map_df_after[lon_col].mean()) if not map_df_after.empty else (active_res_df[lat_col].mean(), active_res_df[lon_col].mean())
        if pd.isna(c_lat): c_lat, c_lon = df[lat_col].mean(), df[lon_col].mean()

        map_col1, map_col2 = st.columns(2)
        def get_name(row): return str(row[name_col]) if name_col else "ไม่ระบุ"

        with map_col1:
            st.markdown("<div style='text-align:center; color:#002D62; font-weight:bold;'>โซนการวิ่งรถเดิม (Before)</div>", unsafe_allow_html=True)
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
            st.markdown("<div style='text-align:center; color:#002D62; font-weight:bold;'>โซนการวิ่งสายใหม่ (Guaranteed Allocation)</div>", unsafe_allow_html=True)
            m2 = folium.Map(location=[c_lat, c_lon], zoom_start=12 if color_mode=='truck' else 14)
            plugins.Fullscreen(position='topright').add_to(m2)
            for _, r in map_df_after.iterrows():
                t_new = str(r['เบอร์รถใหม่'])
                is_vip = str(r.get('VIP_Status', '')).upper() == 'VIP' or str(r[id_col]) in manual_vips
                
                display_day = str(r.get('วันจัดส่ง(ใหม่)', r.get(day_col, ''))) if 'simulated_df' in st.session_state else str(r.get(day_col, ''))
                m_color = color_map.get(t_new, 'gray') if color_mode == 'truck' else next((c for d, c in day_color_map.items() if d in display_day.strip()), 'gray')
                
                popup_html = f"<b>รหัส:</b> {r[id_col]}<br><b>ชื่อ:</b> {get_name(r)}<br><b>ยอด:</b> {r[vol_col]} ถัง<br><b>รถล่าสุด:</b> {t_new}"
                folium.CircleMarker([r[lat_col], r[lon_col]], radius=8 if is_vip else 5, color='#002D62' if is_vip else m_color, weight=2 if is_vip else 1, fill=True, fillColor=m_color, fill_opacity=0.9, popup=folium.Popup(popup_html, max_width=300)).add_to(m2)
            components.html(m2.get_root().render(), height=450)

        st.markdown("### 📋 รายละเอียดข้อมูลการโยกย้ายสมาชิก")
        
        final_cols = [id_col]
        if name_col and name_col in active_res_df.columns: final_cols.append(name_col)
        final_cols.append(day_col)
        if 'วันจัดส่ง(ใหม่)' in active_res_df.columns: final_cols.append('วันจัดส่ง(ใหม่)')
        final_cols.extend([vol_col, truck_col, 'เบอร์รถใหม่', 'สถานะ'])

        detail_df = active_res_df.copy()
        detail_df['เบอร์รถเดิม (ก่อนปรับ)'] = detail_df[truck_col]
        if 'วันจัดส่ง(ใหม่)' not in detail_df.columns:
            detail_df['วันจัดส่ง(ใหม่)'] = detail_df[day_col]

        detail_df = detail_df[[c for c in final_cols if c in detail_df.columns]].rename(columns={day_col: 'วันจัดส่ง(เดิม)'})
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
        st.info("👈 กดปุ่ม 'ประมวลผลตัดสายส่ง' ที่แถบเมนูด้านซ้าย เพื่อดูผลลัพธ์การคำนวณ")
else:
    st.info("👈 กรุณาวางลิงก์ Google Sheets ที่แถบเมนูด้านซ้าย เพื่อเริ่มต้นใช้งาน Dashboard")
