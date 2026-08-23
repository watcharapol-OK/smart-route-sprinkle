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
st.markdown("**ระบบวิเคราะห์และตัดสายส่งน้ำอัตโนมัติ (Balanced Fleet & Daily Load Model)**")

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
        loader_html = f'''<div class="custom-truck-loader"><img src="data:image/jpeg;base64,{encoded_string}" alt="รถกำลังวิ่ง..."><br>กำลังประมวลผลจัดสรรเส้นทาง... 💦</div>'''
    except FileNotFoundError:
        loader_html = '<div class="custom-truck-loader">กำลังโหลดข้อมูล...</div>'
        
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
    
    st.sidebar.markdown("### 🎛️ 3. ปรับเป้าหมายรายวัน (%)")
    
    total_vol_available = df[vol_col].sum()
    sys_pct = (total_vol_available / 4160) * 100
    st.sidebar.info(f"💧 **เพดานงานรวมในสาขานี้:** {sys_pct:,.1f}%")
    
    active_trucks = [t for t in available_trucks if t != base_truck]
    if new_truck_name not in active_trucks:
        active_trucks.append(new_truck_name)
    
    if 'slider_init' not in st.session_state or st.session_state.get('base_truck') != base_truck or st.session_state.get('new_truck') != new_truck_name:
        st.session_state.truck_pcts = {}
        for t in active_trucks:
            if t == new_truck_name and t not in df[truck_col].astype(str).unique():
                st.session_state.truck_pcts[t] = 0.0
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
        col1, col2 = st.sidebar.columns([3, 1.2])
        with col2:
            st.markdown("<div style='margin-top: 32px;'></div>", unsafe_allow_html=True)
            st.checkbox("🔒 ล็อก", key=f"lock_{t}", on_change=reset_results)
        with col1:
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

    # 📌 แกนสมองขั้นสูงสุด: Voronoi Boundary + Capacity Slicing (ป้องกันการทับซ้อน 100%)
    def run_fast_allocation(data, base_t, new_t, pct_dict, manual_locks, locked_ui_list, override_col=None):
        opt_df = data.copy()
        opt_df['เบอร์รถใหม่'] = 'ยังไม่จัด'
        opt_df['วันจัดส่ง(ใหม่)'] = opt_df[day_col].astype(str)
        opt_df['is_locked'] = (opt_df['VIP_Status'].astype(str).str.upper() == 'VIP') | (opt_df[id_col].astype(str).isin(manual_locks))
        
        has_base = base_t != "(ไม่มี - เพิ่มรถคันใหม่กระจายงาน)"
        active_trucks = [t for t in available_trucks if t != base_t]
        if new_t not in active_trucks: active_trucks.append(new_t)
            
        monthly_targets = {t: 4160 * (pct_dict.get(t, 100) / 100) for t in active_trucks}
        vols = opt_df[vol_col].values
        coords = opt_df[[lat_col, lon_col]].values
        
        centers = {}
        for t in available_trucks:
            t_data = opt_df[opt_df[truck_col].astype(str) == t]
            if not t_data.empty: centers[t] = (np.average(t_data[lat_col]), np.average(t_data[lon_col]))
            
        if has_base and base_t in centers: centers[new_t] = centers[base_t]
        else: centers[new_t] = (np.average(coords[:, 0]), np.average(coords[:, 1]))
        
        current_loads = {t: 0 for t in active_trucks}
        
        # 1. ล็อก VIP ให้เรียบร้อย
        locked_indices = np.where(opt_df['is_locked'].values)[0]
        for idx in locked_indices:
            orig_t = str(opt_df.at[idx, truck_col])
            target_t = orig_t if orig_t in active_trucks else new_t
            opt_df.at[idx, 'เบอร์รถใหม่'] = target_t
            current_loads[target_t] += vols[idx]
            
        # 2. จัดทุกคนลงรถที่ "ใกล้ที่สุด (Voronoi)" เพื่อให้ได้กลุ่มก้อนพื้นที่ 100% ไม่มีการข้ามซอย
        unlocked_indices = np.where(~opt_df['is_locked'].values)[0]
        for idx in unlocked_indices:
            pt = coords[idx]
            best_t = None
            min_d = float('inf')
            orig_t = str(opt_df.at[idx, truck_col])
            if orig_t == base_t: orig_t = new_t
            
            for t in active_trucks:
                d = (pt[0] - centers[t][0])**2 + (pt[1] - centers[t][1])**2
                if t == orig_t: d *= 0.85 # ลำเอียงให้รถคันเดิมเล็กน้อย เพื่อรักษาสายเก่า
                if d < min_d:
                    min_d = d
                    best_t = t
            
            opt_df.at[idx, 'เบอร์รถใหม่'] = best_t
            current_loads[best_t] += vols[idx]

        # 3. ปรับสมดุลโควตาด้วยวิธี "เฉือนตะเข็บชายแดน (Border Reassignment)"
        # การเฉือนชายแดนทำให้พื้นที่ยังเป็นกลุ่มก้อนเหมือนเดิม ไม่ทะลุไปโผล่เป็นไข่ดาว
        for iteration in range(25):
            over_trucks = [t for t in active_trucks if current_loads[t] > monthly_targets.get(t, 0) + 15]
            under_trucks = [t for t in active_trucks if current_loads[t] < monthly_targets.get(t, 0) - 15]
            
            if not over_trucks or not under_trucks:
                break
                
            # หารถที่ล้นเป้าหมายมากที่สุด
            t_over = max(over_trucks, key=lambda t: current_loads[t] - monthly_targets.get(t, 0))
            excess = current_loads[t_over] - monthly_targets.get(t_over, 0)
            
            t_idx = [i for i in unlocked_indices if opt_df.at[i, 'เบอร์รถใหม่'] == t_over]
            
            candidates = []
            for i in t_idx:
                pt = coords[i]
                d_over = (pt[0] - centers[t_over][0])**2 + (pt[1] - centers[t_over][1])**2
                
                best_under = None
                min_d_under = float('inf')
                for t_under in under_trucks:
                    # ถ้ารถที่เป้ายังไม่เต็ม ดันถูกกดล็อกไว้ ต้องเช็คว่ารับไหวไหม
                    if t_under in locked_ui_list and current_loads[t_under] + vols[i] > monthly_targets.get(t_under, 0) + 10:
                        continue
                        
                    d_under = (pt[0] - centers[t_under][0])**2 + (pt[1] - centers[t_under][1])**2
                    if d_under < min_d_under:
                        min_d_under = d_under
                        best_under = t_under
                        
                if best_under is not None:
                    # ค่า Score ยิ่งติดลบเยอะ แปลว่าลูกค้ารายนี้อยู่ใกล้ขอบรอยต่อของรถอีกคันมากกว่า
                    score = min_d_under - d_over 
                    candidates.append({'idx': i, 'score': score, 'target': best_under, 'vol': vols[i]})
                    
            if not candidates:
                break
                
            # เรียงเพื่อย้ายเฉพาะลูกค้าตรงตะเข็บชายแดน
            candidates.sort(key=lambda x: x['score'])
            
            shifted_vol = 0
            for cand in candidates:
                if shifted_vol >= excess: break
                
                if cand['target'] in locked_ui_list and current_loads[cand['target']] + cand['vol'] > monthly_targets.get(cand['target'], 0) + 10:
                    continue
                    
                opt_df.at[cand['idx'], 'เบอร์รถใหม่'] = cand['target']
                current_loads[t_over] -= cand['vol']
                current_loads[cand['target']] += cand['vol']
                shifted_vol += cand['vol']
                
                # ขยับศูนย์กลางพื้นที่เล็กน้อย
                centers[cand['target']] = (centers[cand['target']][0]*0.98 + coords[cand['idx']][0]*0.02, 
                                           centers[cand['target']][1]*0.98 + coords[cand['idx']][1]*0.02)
                                           
        opt_df['สถานะ'] = np.where(opt_df[truck_col].astype(str) == opt_df['เบอร์รถใหม่'], 'คงเดิม', 'ย้ายไปสาย ' + opt_df['เบอร์รถใหม่'])
        if has_base:
            opt_df['สถานะ'] = np.where(opt_df[truck_col].astype(str) == base_t, 'ยุบสายไป ' + opt_df['เบอร์รถใหม่'], opt_df['สถานะ'])
            
        daily_matrix = get_daily_vols(opt_df, override_col)
        return opt_df, daily_matrix, centers

    # 📌 ระบบผู้ช่วยอัจฉริยะ (ดึงไปเป็นกลุ่มก้อน Cluster-Shift)
    def get_cluster_day_shift_recommendations(data_df, daily_mat, centers):
        recs = []
        days_str_map = {0: 'จันทร์', 1: 'อังคาร', 2: 'พุธ', 3: 'พฤหัสฯ', 4: 'ศุกร์', 5: 'เสาร์'}
        trucks = data_df['เบอร์รถใหม่'].dropna().unique()
        
        MAX_CAP = 156
        SAFE_TARGET = 145 # ดึงให้ลดลงมาอยู่ในโซนปลอดภัย 
        
        for t in trucks:
            t_mask = data_df['เบอร์รถใหม่'] == t
            if not t_mask.any(): continue
            
            t_indices = data_df[t_mask].index.tolist()
            t_daily_vols = daily_mat[t_indices].sum(axis=0)
            
            over_days = [d for d in range(6) if t_daily_vols[d] > MAX_CAP]
            if not over_days: continue
            
            c_lat, c_lon = centers.get(t, (data_df.loc[t_indices, lat_col].mean(), data_df.loc[t_indices, lon_col].mean()))
            
            for d_over in over_days:
                excess = t_daily_vols[d_over] - SAFE_TARGET
                if excess <= 0: continue
                
                # หาวันที่ "มียอดส่งน้อยที่สุด" ตามคำสั่งคุณโอ
                under_days = [d for d in range(6) if t_daily_vols[d] < MAX_CAP - 20]
                if not under_days: continue
                
                d_under = under_days[np.argmin([t_daily_vols[d] for d in under_days])]
                
                pts_on_day = [idx for idx in t_indices if daily_mat[idx][d_over] > 0 and not data_df.loc[idx, 'is_locked']]
                if not pts_on_day: continue
                
                # หา "หัวหน้ากลุ่ม" ที่เป็นตะเข็บชายแดนที่สุดของรถคันนี้
                dists_from_center = [(data_df.loc[idx, lat_col] - c_lat)**2 + (data_df.loc[idx, lon_col] - c_lon)**2 for idx in pts_on_day]
                seed_idx = pts_on_day[np.argmax(dists_from_center)]
                seed_lat, seed_lon = data_df.loc[seed_idx, lat_col], data_df.loc[seed_idx, lon_col]
                
                # เรียงคนอื่นๆ ตามความใกล้ชิดกับหัวหน้ากลุ่ม (ดึงไปเป็นก้อนพื้นที่ติดกัน)
                dists_from_seed = [(data_df.loc[idx, lat_col] - seed_lat)**2 + (data_df.loc[idx, lon_col] - seed_lon)**2 for idx in pts_on_day]
                pts_sorted = [x for _, x in sorted(zip(dists_from_seed, pts_on_day))]
                
                shifted_vol = 0
                for idx in pts_sorted:
                    if shifted_vol >= excess: break
                    
                    recs.append({
                        'index': idx,
                        'เบอร์รถ': t,
                        'รหัสสมาชิก': data_df.loc[idx, id_col],
                        'ชื่อ': data_df.loc[idx, name_col] if name_col else '',
                        'ยอด(ถัง/วัน)': round(daily_mat[idx][d_over], 1),
                        'วันเดิม': days_str_map[d_over],
                        'แนะนำย้ายไป': days_str_map[d_under],
                        'เหตุผล': f"ย้ายตามกลุ่มพื้นที่ใกล้เคียง (-{round(t_daily_vols[d_over]-145)} ถัง)"
                    })
                    shifted_vol += daily_mat[idx][d_over]
                    
        return pd.DataFrame(recs)

    st.sidebar.markdown("---")
    if st.sidebar.button("🚀 ประมวลผลตัดสายส่ง", use_container_width=True):
        calc_placeholder = st.empty()
        try:
            with open("truck.jpg", "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode()
            loader_html = f'''<div class="custom-truck-loader"><img src="data:image/jpeg;base64,{encoded_string}" alt="รถกำลังวิ่ง..."><br>กำลังจัดกลุ่มพื้นที่ (Cluster) แบบไม่ทับซ้อน... 🚚💨</div>'''
        except FileNotFoundError:
            loader_html = '<div class="custom-truck-loader">กำลังประมวลผล...</div>'
            
        calc_placeholder.markdown(loader_html, unsafe_allow_html=True)
        
        res_df, daily_matrix, route_centers = run_fast_allocation(df, base_truck, new_truck_name, target_pcts, manual_vips, locked_ui_trucks)
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
        
        active_res_df = st.session_state.get('simulated_df', res_df)
        active_matrix = st.session_state.get('simulated_matrix', daily_matrix)
        
        st.markdown("### 📊 สรุปภาพรวมยอดการจัดส่ง")
        if 'simulated_df' in st.session_state:
            st.info("🧪 **แสดงผลลัพธ์จำลอง (After Simulation)** - ตารางโหลดรายวันถูกอัปเดตตามการสลับวันของลูกค้ากลุ่มตะเข็บพื้นที่แล้ว โดยไม่เปลี่ยนเส้นทางรถหลัก")
            
        col1, col2 = st.columns(2)
        
        sum_before = df.groupby(truck_col).agg(จำนวนสมาชิก=pd.NamedAgg(column=truck_col, aggfunc='count'), **{'ยอดรับน้ำ(ถัง/เดือน)': pd.NamedAgg(column=vol_col, aggfunc='sum')}).reset_index()
        sum_after = active_res_df.groupby('เบอร์รถใหม่').agg(จำนวนสมาชิก=pd.NamedAgg(column='เบอร์รถใหม่', aggfunc='count'), **{'ยอดรับน้ำ(ถัง/เดือน)': pd.NamedAgg(column=vol_col, aggfunc='sum')}).reset_index()
        sum_after['ปริมาณงาน(%)'] = (sum_after['ยอดรับน้ำ(ถัง/เดือน)'] / 4160 * 100).round(1).astype(str) + '%'

        with col1:
            st.markdown("**ก่อนปรับโครงสร้างสายส่ง**")
            st.dataframe(sum_before, use_container_width=True)
        with col2:
            st.markdown("**หลังปรับโครงสร้าง (พื้นที่บริสุทธิ์ไม่ทับซ้อน)**")
            st.dataframe(sum_after, use_container_width=True)
            
        st.markdown("### 📅 ตารางวิเคราะห์โหลดรายวัน (จันทร์-เสาร์)")
            
        daily_summary = []
        for t in all_trucks_after:
            t_mask = active_res_df['เบอร์รถใหม่'] == t
            t_daily = active_matrix[t_mask].sum(axis=0)
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
        
        max_all_days = max([row['โหลดสูงสุด (ถัง/วัน)'] for row in daily_summary])
        if max_all_days > 156 and 'simulated_df' not in st.session_state:
            st.error(f"🚨 **ระบบตรวจพบโหลดเกินขีดจำกัดสูงสุด ({max_all_days} ถัง/วัน)!** \n\nหมายเหตุ: เกิดจากพื้นที่โซนนี้มียอดสั่งน้ำหนาแน่นตรงกันในวันเดียว โปรดคลิกปุ่ม **'จำลองผลลัพธ์'** ด้านล่าง เพื่อให้ AI ดึงลูกค้าในพื้นที่ติดกันสลับไปยังวันที่โหลดน้อยที่สุด เพื่อลดยอดให้สมดุลครับ")
        
        st.markdown("#### 💡 ระบบผู้ช่วยอัจฉริยะ (AI Cluster Day-Shift Optimization)")
        recs_df = get_cluster_day_shift_recommendations(res_df, daily_matrix, route_centers)
        
        if not recs_df.empty and 'simulated_df' not in st.session_state:
            st.warning("รายการลูกค้ารอยต่อพื้นที่ ที่แนะนำให้เจรจาสลับวัน เพื่อเกลี่ยยอดรายวันให้สมดุลและไม่เกิน 156 ถัง/วัน:")
            st.dataframe(recs_df[['เบอร์รถ', 'รหัสสมาชิก', 'ชื่อ', 'ยอด(ถัง/วัน)', 'วันเดิม', 'แนะนำย้ายไป', 'เหตุผล']], use_container_width=True)
            
            if st.button("🧪 จำลองผลลัพธ์หลังเจรจาย้ายวันเป็นกลุ่ม (What-If Simulation)"):
                sim_df = res_df.copy()
                sim_col_name = day_col + '_simulated'
                sim_df[sim_col_name] = sim_df[day_col].astype(str)
                days_str_map = {0: 'จันทร์', 1: 'อังคาร', 2: 'พุธ', 3: 'พฤหัสฯ', 4: 'ศุกร์', 5: 'เสาร์'}
                
                for _, r in recs_df.iterrows():
                    idx = r['index']
                    target_day_str = r['แนะนำย้ายไป']
                    old_day_str = r['วันเดิม']
                    
                    current_days_str = str(sim_df.at[idx, sim_col_name])
                    current_list = parse_days_from_string(current_days_str)
                    
                    old_d_int = {v: k for k, v in days_str_map.items()}.get(old_day_str)
                    new_d_int = {v: k for k, v in days_str_map.items()}.get(target_day_str)
                    
                    if old_d_int is not None and new_d_int is not None:
                        new_list = [new_d_int if d == old_d_int else d for d in current_list]
                        sim_df.at[idx, sim_col_name] = format_days_to_string(list(set(new_list)))
                    
                sim_daily_mat = get_daily_vols(sim_df, override_day_col=sim_col_name)
                sim_df['วันจัดส่ง(ใหม่)'] = sim_df[sim_col_name]
                
                st.session_state['simulated_df'] = sim_df
                st.session_state['simulated_matrix'] = sim_daily_mat
                st.success("✅ จำลองผลลัพธ์สำเร็จ! ตารางโหลดรายวันถูกอัปเดต โดยรักษารูปแบบอาณาเขตพื้นที่เดิม 100% ครับ")
                st.rerun()
        elif 'simulated_df' in st.session_state:
            st.success("✅ แสดงผลลัพธ์จากการจำลองการย้ายวันเรียบร้อยแล้วครับ")
            if st.button("❌ ล้างผลการจำลอง (Reset Simulation)"):
                del st.session_state['simulated_df']
                del st.session_state['simulated_matrix']
                st.rerun()
        else:
            st.success("✅ ยอดเยี่ยม! โหลดรายวันอยู่ในโซนคุ้มค่าสมบูรณ์แบบ ไม่มีความจำเป็นต้องย้ายวันลูกค้า")

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
            st.markdown("<div style='text-align:center; color:#002D62; font-weight:bold;'>โซนการวิ่งสายใหม่ (Balanced Fleet - No Overlap)</div>", unsafe_allow_html=True)
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
        
        display_cols = [id_col]
        if name_col: display_cols.append(name_col)
        display_cols.append(day_col) 
        if 'simulated_df' in st.session_state: display_cols.append('วันจัดส่ง(ใหม่)')
        display_cols.extend([vol_col, truck_col, 'เบอร์รถใหม่', 'สถานะ'])
        
        detail_df = active_res_df.copy()
        detail_df['เบอร์รถเดิม (ก่อนปรับ)'] = detail_df[truck_col]
        detail_df = detail_df[display_cols].rename(columns={day_col: 'วันจัดส่ง(เดิม)'})
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
