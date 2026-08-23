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
st.markdown("**ระบบวิเคราะห์และตัดสายส่งน้ำอัตโนมัติ (Anti-Overlap Zone & 2-Trip Fleet Model)**")

st.sidebar.markdown("### 📁 1. นำเข้าข้อมูล (Data Source)")
sheet_url = st.sidebar.text_input("🔗 ลิงก์ Google Sheets:", placeholder="วางลิงก์ที่นี่...")

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
        loader_html = f'''<div class="custom-truck-loader"><img src="data:image/jpeg;base64,{encoded_string}" alt="รถกำลังวิ่ง..."><br>กำลังจัดระเบียบพื้นที่และตัดสายส่ง... 💦</div>'''
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
    day_col = next((c for c in df.columns if 'สัปดาห์' in str(c) or 'วัน' in str(c)), None)
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
    
    st.sidebar.markdown("### ⚙️ 2. รูปแบบการสร้างสายใหม่")
    available_trucks = [str(x) for x in df[truck_col].unique() if str(x) != 'nan']
    base_truck_options = ["(ไม่มี - เพิ่มรถคันใหม่กระจายงาน)"] + available_trucks
    
    base_truck = st.sidebar.selectbox("เลือกรถที่จะถูกยุบ/ดึงงานออก", options=base_truck_options)
    new_truck_name = st.sidebar.text_input("ตั้งชื่อเบอร์รถคันใหม่", value="15112")
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🎛️ 3. ปรับเป้าหมายรายวัน (%)")
    target_pcts = {}
    for t in available_trucks:
        if t == base_truck: continue
        target_pcts[t] = st.sidebar.slider(f"เป้าหมายของรถ {t} (%)", min_value=0, max_value=120, value=100, step=1)
    target_pcts[new_truck_name] = st.sidebar.slider(f"เป้าหมายของรถสายใหม่ {new_truck_name} (%)", min_value=10, max_value=120, value=100, step=1)

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🔒 4. ล็อก Key Account")
    manual_vips = st.sidebar.multiselect("เลือกรหัสสมาชิกที่ห้ามย้ายสาย", options=df[id_col].astype(str).unique().tolist(), default=[])

    def get_daily_vols(data_df, override_day_col=None):
        col_to_use = override_day_col if override_day_col else day_col
        daily_matrix = np.zeros((len(data_df), 6)) 
        for i, row in data_df.iterrows():
            vol = row[vol_col]
            day_str = str(row.get(col_to_use, '')).replace(' ', '')
            days = []
            if 'จันทร์' in day_str or 'จ.' in day_str: days.append(0)
            if 'อังคาร' in day_str or 'อ.' in day_str: days.append(1)
            if 'พุธ' in day_str or 'พ.' in day_str and 'พฤ' not in day_str: days.append(2)
            if 'พฤหัส' in day_str or 'พฤ.' in day_str: days.append(3)
            if 'ศุกร์' in day_str or 'ศ.' in day_str: days.append(4)
            if 'เสาร์' in day_str or 'ส.' in day_str: days.append(5)
            
            if not days: days = [0, 1, 2, 3, 4, 5] 
            
            vol_per_day = vol / (len(days) * 4.333) 
            for d in days:
                daily_matrix[i, d] = vol_per_day
        return daily_matrix

    # 📌 อัปเกรดสมองกล: ป้องกันรถวิ่งทับซ้อนในพื้นที่ย่อย (Anti-Overlap Zone Allocation)
    def run_fast_allocation(data, base_t, new_t, pct_dict, manual_locks, override_col=None):
        opt_df = data.copy()
        opt_df['เบอร์รถใหม่'] = 'ยังไม่จัด'
        opt_df['is_locked'] = (opt_df['VIP_Status'].astype(str).str.upper() == 'VIP') | (opt_df[id_col].astype(str).isin(manual_locks))
        
        has_base = base_t != "(ไม่มี - เพิ่มรถคันใหม่กระจายงาน)"
        active_trucks = [t for t in available_trucks if t != base_t] + [new_t]
        
        daily_targets = {t: 150.0 * (pct_dict.get(t, 100) / 100) for t in active_trucks}
        if has_base: daily_targets[base_t] = 0 
        
        daily_matrix = get_daily_vols(opt_df, override_col)
        coords = opt_df[[lat_col, lon_col]].values
        
        centers = {}
        for t in available_trucks:
            t_data = opt_df[opt_df[truck_col].astype(str) == t]
            if not t_data.empty: centers[t] = (np.average(t_data[lat_col]), np.average(t_data[lon_col]))
            
        if has_base and base_t in centers: centers[new_t] = centers[base_t]
        else:
            ul_data = opt_df[~opt_df['is_locked']]
            if not ul_data.empty: centers[new_t] = (np.average(ul_data[lat_col]), np.average(ul_data[lon_col]))

        # 📌 ขั้นตอนพิเศษ: จัดกลุ่มหมุดที่อยู่ใกล้กันมากๆ (Micro-Clusters) ให้ไปอยู่รถคันเดียวกันแบบ 100%
        # เพื่อตัดปัญหาการส่งซ้ำซ้อนในพื้นที่ย่อย (Anti-Overlap)
        from sklearn.cluster import DBSCAN
        if len(coords) > 5:
            # ใช้พิกัดกรองกลุ่มย่อยในรัศมีใกล้เคียงกัน
            clustering = DBSCAN(eps=0.003, min_samples=2).fit(coords)
            opt_df['cluster_id'] = clustering.labels_
        else:
            opt_df['cluster_id'] = -1

        for iteration in range(2):
            current_daily_loads = {t: np.zeros(6) for t in active_trucks + ([base_t] if has_base else [])}
            locked_indices = np.where(opt_df['is_locked'].values)[0]
            
            for idx in locked_indices:
                orig_t = str(opt_df.at[idx, truck_col])
                opt_df.at[idx, 'เบอร์รถใหม่'] = orig_t
                if orig_t in current_daily_loads:
                    current_daily_loads[orig_t] += daily_matrix[idx]
                
            remaining_mask = ~opt_df['is_locked'].values
            
            # จัดสรรแบบเหมายกกลุ่มย่อย (Cluster-based Allocation) เพื่อความต่อเนื่องของพื้นที่
            unique_clusters = opt_df['cluster_id'].unique()
            for c_id in unique_clusters:
                if c_id == -1: continue # ข้ามจุดเดี่ยวที่ไม่อยู่ในกลุ่ม
                c_indices = opt_df[(opt_df['cluster_id'] == c_id) & remaining_mask].index.tolist()
                if not c_indices: continue
                
                # หาว่ากลุ่มนี้อยู่ใกล้รถคันไหนที่สุด
                c_lat = opt_df.loc[c_indices, lat_col].mean()
                c_lon = opt_df.loc[c_indices, lon_col].mean()
                
                best_t = None
                min_c_dist = float('inf')
                for t in active_trucks:
                    if t not in centers: continue
                    dist = (centers[t][0] - c_lat)**2 + (centers[t][1] - c_lon)**2
                    if dist < min_c_dist:
                        min_c_dist = dist
                        best_t = t
                if not best_t: best_t = active_trucks[0]
                
                # เหมาทั้งกลุ่มให้รถคันนี้
                for idx in c_indices:
                    opt_df.at[idx, 'เบอร์รถใหม่'] = best_t
                    current_daily_loads[best_t] += daily_matrix[idx]
                    remaining_mask[idx] = False

            # จัดสรรจุดที่เหลือรายจุด
            while remaining_mask.any():
                max_deficit_ratio = -float('inf')
                starving_truck = None
                
                for t in active_trucks:
                    if daily_targets[t] <= 0: continue
                    busiest_day_load = np.max(current_daily_loads[t])
                    ratio = (daily_targets[t] - busiest_day_load) / daily_targets[t]
                    if ratio > max_deficit_ratio:
                        max_deficit_ratio = ratio
                        starving_truck = t
                        
                if starving_truck is None: starving_truck = new_t
                
                c_lat, c_lon = centers[starving_truck]
                rem_indices = np.where(remaining_mask)[0]
                rem_coords = coords[rem_indices]
                
                dists = (rem_coords[:, 0] - c_lat)**2 + (rem_coords[:, 1] - c_lon)**2
                sorted_local_indices = np.argsort(dists)
                
                assigned = False
                for local_idx in sorted_local_indices:
                    global_idx = rem_indices[local_idx]
                    pt_daily = daily_matrix[global_idx]
                    
                    if np.all(current_daily_loads[starving_truck] + pt_daily <= 155.0):
                        opt_df.at[global_idx, 'เบอร์รถใหม่'] = starving_truck
                        current_daily_loads[starving_truck] += pt_daily
                        remaining_mask[global_idx] = False
                        assigned = True
                        break
                
                if not assigned:
                    global_idx = rem_indices[sorted_local_indices[0]]
                    opt_df.at[global_idx, 'เบอร์รถใหม่'] = starving_truck
                    current_daily_loads[starving_truck] += daily_matrix[global_idx]
                    remaining_mask[global_idx] = False
                
            for t in active_trucks:
                t_mask = opt_df['เบอร์รถใหม่'] == t
                if t_mask.any():
                    centers[t] = (np.average(coords[t_mask, 0]), np.average(coords[t_mask, 1]))
                
        opt_df['สถานะ'] = np.where(opt_df[truck_col].astype(str) == opt_df['เบอร์รถใหม่'], 'คงเดิม', 'ย้ายไปสาย ' + opt_df['เบอร์รถใหม่'])
        return opt_df, daily_matrix

    def get_recommendations(data_df, daily_mat):
        recs = []
        days_str_map = {0: 'จันทร์', 1: 'อังคาร', 2: 'พุธ', 3: 'พฤหัสฯ', 4: 'ศุกร์', 5: 'เสาร์'}
        trucks = data_df['เบอร์รถใหม่'].dropna().unique()
        
        for t in trucks:
            t_mask = data_df['เบอร์รถใหม่'] == t
            if not t_mask.any(): continue
            
            t_indices = data_df[t_mask].index.tolist()
            t_daily_vols = daily_mat[t_indices].sum(axis=0)
            
            over_days = [d for d in range(6) if t_daily_vols[d] > 155 or (121 <= t_daily_vols[d] <= 139)]
            under_days = [d for d in range(6) if t_daily_vols[d] < 140]
            
            if not over_days or not under_days: continue
            
            day_centers = {}
            pts_by_day = {i: [] for i in range(6)}
            
            for idx in t_indices:
                pt_daily = daily_mat[idx]
                active_days = np.where(pt_daily > 0)[0]
                if len(active_days) == 1:
                    pts_by_day[active_days[0]].append(idx)
                    
            for d in range(6):
                if pts_by_day[d]:
                    day_centers[d] = (data_df.loc[pts_by_day[d], lat_col].mean(), data_df.loc[pts_by_day[d], lon_col].mean())
            
            for d_over in over_days:
                target_drop = 150 if t_daily_vols[d_over] > 155 else (t_daily_vols[d_over] - 115)
                excess = t_daily_vols[d_over] - target_drop
                if excess <= 0 or d_over not in day_centers: continue
                
                best_under_day = None
                min_dist = float('inf')
                for d_under in under_days:
                    if d_under != d_over and d_under in day_centers:
                        dist = (day_centers[d_over][0] - day_centers[d_under][0])**2 + (day_centers[d_over][1] - day_centers[d_under][1])**2
                        if dist < min_dist:
                            min_dist = dist
                            best_under_day = d_under
                            
                if best_under_day is None: continue
                
                c_under = day_centers[best_under_day]
                c_over = day_centers[d_over]
                
                candidates = []
                for idx in pts_by_day[d_over]:
                    lat, lon = data_df.loc[idx, lat_col], data_df.loc[idx, lon_col]
                    dist_under = (lat - c_under[0])**2 + (lon - c_under[1])**2
                    dist_over = (lat - c_over[0])**2 + (lon - c_over[1])**2
                    score = dist_under - dist_over 
                    candidates.append({'idx': idx, 'score': score, 'vol': daily_mat[idx][d_over]})
                    
                candidates.sort(key=lambda x: x['score'])
                
                shifted_vol = 0
                for cand in candidates:
                    if shifted_vol >= excess: break
                    idx = cand['idx']
                    reason = "โซนไม่คุ้มค่า (121-139 ถัง)" if t_daily_vols[d_over] <= 139 else "ยอดทะลุ 155 ถัง"
                    recs.append({
                        'index': idx,
                        'เบอร์รถ': t,
                        'รหัสสมาชิก': data_df.loc[idx, id_col],
                        'ชื่อ': data_df.loc[idx, name_col] if name_col else '',
                        'ยอด(ถัง/วัน)': round(cand['vol'], 1),
                        'วันเดิม': days_str_map[d_over],
                        'แนะนำย้ายไป': days_str_map[best_under_day],
                        'เหตุผล': reason
                    })
                    shifted_vol += cand['vol']
                    
        return pd.DataFrame(recs)

    st.sidebar.markdown("---")
    if st.sidebar.button("🚀 ประมวลผลตัดสายส่ง", use_container_width=True):
        calc_placeholder = st.empty()
        try:
            with open("truck.jpg", "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode()
            loader_html = f'''<div class="custom-truck-loader"><img src="data:image/jpeg;base64,{encoded_string}" alt="รถกำลังวิ่ง..."><br>กำลังจัดระเบียบพื้นที่และตัดสายส่ง... 🚚💨</div>'''
        except FileNotFoundError:
            loader_html = '<div class="custom-truck-loader">กำลังประมวลผล...</div>'
            
        calc_placeholder.markdown(loader_html, unsafe_allow_html=True)
        
        res_df, daily_matrix = run_fast_allocation(df, base_truck, new_truck_name, target_pcts, manual_vips)
        st.session_state['result_df'] = res_df
        st.session_state['daily_matrix'] = daily_matrix
        if 'simulated_df' in st.session_state: del st.session_state['simulated_df']
        if 'simulated_matrix' in st.session_state: del st.session_state['simulated_matrix']
        time.sleep(0.5) 
        calc_placeholder.empty()

    if 'result_df' in st.session_state:
        res_df = st.session_state['result_df']
        daily_matrix = st.session_state['daily_matrix']
        all_trucks_after = sorted(res_df['เบอร์รถใหม่'].dropna().unique().tolist())
        
        active_res_df = st.session_state.get('simulated_df', res_df)
        active_matrix = st.session_state.get('simulated_matrix', daily_matrix)
        
        st.markdown("### 📊 สรุปภาพรวมยอดการจัดส่ง")
        if 'simulated_df' in st.session_state:
            st.info("🧪 **กำลังแสดงผลลัพธ์จำลอง (After Simulation)** - ตารางสรุปและโหลดรายวันด้านล่างถูกคำนวณใหม่ตามการย้ายวันเรียบร้อยแล้ว")
            
        col1, col2 = st.columns(2)
        
        sum_before = df.groupby(truck_col).agg(จำนวนสมาชิก=pd.NamedAgg(column=truck_col, aggfunc='count'), **{'ยอดรับน้ำ(ถัง/เดือน)': pd.NamedAgg(column=vol_col, aggfunc='sum')}).reset_index()
        sum_after = active_res_df.groupby('เบอร์รถใหม่').agg(จำนวนสมาชิก=pd.NamedAgg(column='เบอร์รถใหม่', aggfunc='count'), **{'ยอดรับน้ำ(ถัง/เดือน)': pd.NamedAgg(column=vol_col, aggfunc='sum')}).reset_index()
        sum_after['ปริมาณงาน(%)'] = (sum_after['ยอดรับน้ำ(ถัง/เดือน)'] / (150*26) * 100).round(1).astype(str) + '%'

        with col1:
            st.markdown("**ก่อนปรับโครงสร้างสายส่ง**")
            st.dataframe(sum_before, use_container_width=True)
        with col2:
            st.markdown("**หลังปรับโครงสร้าง (อัปเดตตามผลจำลอง)**" if 'simulated_df' in st.session_state else "**หลังปรับโครงสร้าง**")
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
        
        st.markdown("#### 💡 ระบบผู้ช่วยอัจฉริยะ (AI Day-Shift Optimization)")
        recs_df = get_recommendations(res_df, daily_matrix)
        
        if not recs_df.empty and 'simulated_df' not in st.session_state:
            st.warning("พบจุดที่อยู่นอกโซนคุ้มค่า ระบบมีคำแนะนำให้ย้ายวันจัดส่งดังตารางด้านล่าง:")
            st.dataframe(recs_df[['เบอร์รถ', 'รหัสสมาชิก', 'ชื่อ', 'ยอด(ถัง/วัน)', 'วันเดิม', 'แนะนำย้ายไป', 'เหตุผล']], use_container_width=True)
            
            if st.button("🧪 จำลองผลลัพธ์หลังทำตามคำแนะนำ (What-If Simulation)"):
                sim_df = res_df.copy()
                sim_col_name = day_col + '_simulated'
                sim_df[sim_col_name] = sim_df[day_col].astype(str)
                
                for _, r in recs_df.iterrows():
                    idx = r['index']
                    target_day = r['แนะนำย้ายไป']
                    sim_df.at[idx, sim_col_name] = target_day
                    
                sim_res_df, sim_daily_mat = run_fast_allocation(df, base_truck, new_truck_name, target_pcts, manual_vips, override_col=sim_col_name)
                st.session_state['simulated_df'] = sim_res_df
                st.session_state['simulated_matrix'] = sim_daily_mat
                st.success("✅ จำลองผลลัพธ์สำเร็จ! ตารางสรุปด้านบนอัปเดตเรียบร้อยแล้วครับ")
                st.rerun()
        elif 'simulated_df' in st.session_state:
            st.success("✅ แสดงผลลัพธ์จากการจำลองการย้ายวันเรียบร้อยแล้วครับ")
            if st.button("❌ ล้างผลการจำลอง (Reset Simulation)"):
                del st.session_state['simulated_df']
                del st.session_state['simulated_matrix']
                st.rerun()
        else:
            st.success("✅ ยอดเยี่ยม! โหลดรายวันอยู่ในโซนคุ้มค่าสมบูรณ์แบบ ไม่มีความจำเป็นต้องย้ายวัน")

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
            st.markdown("<div style='text-align:center; color:#002D62; font-weight:bold;'>โซนการวิ่งสายใหม่ (Anti-Overlap Optimized)</div>", unsafe_allow_html=True)
            m2 = folium.Map(location=[c_lat, c_lon], zoom_start=12 if color_mode=='truck' else 14)
            plugins.Fullscreen(position='topright').add_to(m2)
            for _, r in map_df_after.iterrows():
                t_new = str(r['เบอร์รถใหม่'])
                is_vip = str(r.get('VIP_Status', '')).upper() == 'VIP' or str(r[id_col]) in manual_vips
                m_color = color_map.get(t_new, 'gray') if color_mode == 'truck' else next((c for d, c in day_color_map.items() if d in str(r.get(day_col, '')).strip()), 'gray')
                popup_html = f"<b>รหัส:</b> {r[id_col]}<br><b>ชื่อ:</b> {get_name(r)}<br><b>ยอด:</b> {r[vol_col]} ถัง<br><b>รถล่าสุด:</b> {t_new}"
                folium.CircleMarker([r[lat_col], r[lon_col]], radius=8 if is_vip else 5, color='#002D62' if is_vip else m_color, weight=2 if is_vip else 1, fill=True, fillColor=m_color, fill_opacity=0.9, popup=folium.Popup(popup_html, max_width=300)).add_to(m2)
            components.html(m2.get_root().render(), height=450)

        st.markdown("### 📋 รายละเอียดข้อมูลการโยกย้ายสมาชิก")
        
        display_cols = [id_col]
        if name_col: display_cols.append(name_col)
        if day_col: display_cols.append(day_col) 
        display_cols.extend([vol_col, truck_col, 'เบอร์รถใหม่', 'สถานะ'])
        
        detail_df = active_res_df[display_cols].rename(columns={truck_col: 'เบอร์รถเดิม (ก่อนปรับ)'})
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
