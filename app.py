import streamlit as st
import streamlit.components.v1 as components
import pandas as pd
import numpy as np
import folium
from folium import plugins
import re
import math

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
    </style>
''', unsafe_allow_html=True)

st.title("🚛 Smart Route Rebalancer Dashboard")
st.markdown("**ระบบวิเคราะห์และตัดสายส่งน้ำอัตโนมัติ (Proportional Target Allocation)**")

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
    with st.spinner('กำลังโหลดข้อมูล...'):
        df = load_data_from_sheet(sheet_url)

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
    df = df.dropna(subset=[lat_col, lon_col])
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
    st.sidebar.markdown("### 🎛️ 3. ปรับโควตางานรายคัน (%)")
    st.sidebar.caption("100% = 4,160 ถัง/เดือน")
    
    target_pcts = {}
    for t in available_trucks:
        if t == base_truck: continue
        target_pcts[t] = st.sidebar.slider(f"เป้าหมายของรถ {t} (%)", min_value=0, max_value=120, value=95, step=1)
    target_pcts[new_truck_name] = st.sidebar.slider(f"เป้าหมายของรถสายใหม่ {new_truck_name} (%)", min_value=10, max_value=120, value=100, step=1)

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 🔒 4. ล็อก Key Account")
    manual_vips = st.sidebar.multiselect("เลือกรหัสสมาชิกที่ห้ามย้ายสาย", options=df[id_col].astype(str).unique().tolist(), default=[])

    def run_proportional_allocation(data, base_t, new_t, pct_dict, manual_locks):
        opt_df = data.copy()
        opt_df['เบอร์รถใหม่'] = 'ยังไม่จัด'
        opt_df['is_locked'] = (opt_df['VIP_Status'].astype(str).str.upper() == 'VIP') | (opt_df[id_col].astype(str).isin(manual_locks))
        
        has_base = base_t != "(ไม่มี - เพิ่มรถคันใหม่กระจายงาน)"
        active_trucks = [t for t in available_trucks if t != base_t] + [new_t]
        
        targets = {t: math.floor(4160 * (pct_dict.get(t, 100) / 100)) for t in active_trucks}
        if has_base: targets[base_t] = 0 
        current_loads = {t: 0 for t in active_trucks + ([base_t] if has_base else [])}
        
        for idx, row in opt_df[opt_df['is_locked']].iterrows():
            orig_t = str(row[truck_col])
            opt_df.at[idx, 'เบอร์รถใหม่'] = orig_t
            if orig_t in current_loads: current_loads[orig_t] += row[vol_col]
            
        centers = {}
        for t in available_trucks:
            t_data = opt_df[opt_df[truck_col].astype(str) == t]
            if not t_data.empty: centers[t] = (np.average(t_data[lat_col]), np.average(t_data[lon_col]))
            
        if has_base and base_t in centers:
            centers[new_t] = centers[base_t]
        else:
            ul_data = opt_df[~opt_df['is_locked']]
            if not ul_data.empty: centers[new_t] = (np.average(ul_data[lat_col]), np.average(ul_data[lon_col]))

        unlocked_indices = opt_df[~opt_df['is_locked']].index.tolist()
        
        for iteration in range(2):
            current_loads = {t: 0 for t in active_trucks + ([base_t] if has_base else [])}
            for idx, row in opt_df[opt_df['is_locked']].iterrows():
                current_loads[str(row[truck_col])] += row[vol_col]
            
            remaining_pts = set(unlocked_indices)
            
            while remaining_pts:
                max_deficit_ratio = -float('inf')
                starving_truck = None
                
                for t in active_trucks:
                    if targets[t] <= 0: continue
                    ratio = (targets[t] - current_loads[t]) / targets[t]
                    if ratio > max_deficit_ratio:
                        max_deficit_ratio = ratio
                        starving_truck = t
                        
                if starving_truck is None: starving_truck = new_t
                
                c_lat, c_lon = centers[starving_truck]
                best_idx = None
                min_dist = float('inf')
                
                for idx in remaining_pts:
                    dist = (opt_df.at[idx, lat_col] - c_lat)**2 + (opt_df.at[idx, lon_col] - c_lon)**2
                    if dist < min_dist:
                        min_dist = dist
                        best_idx = idx
                
                opt_df.at[best_idx, 'เบอร์รถใหม่'] = starving_truck
                current_loads[starving_truck] += opt_df.at[best_idx, vol_col]
                remaining_pts.remove(best_idx)
                
            for t in active_trucks:
                t_data = opt_df[opt_df['เบอร์รถใหม่'] == t]
                if not t_data.empty: centers[t] = (np.average(t_data[lat_col]), np.average(t_data[lon_col]))
                
        opt_df['สถานะ'] = np.where(opt_df[truck_col].astype(str) == opt_df['เบอร์รถใหม่'], 'คงเดิม', 'ย้ายไปสาย ' + opt_df['เบอร์รถใหม่'])
        return opt_df

    with st.spinner('ระบบกำลังประมวลผลจัดสรรงาน...'):
        res_df = run_proportional_allocation(df, base_truck, new_truck_name, target_pcts, manual_vips)

    st.markdown("### 📊 สรุปภาพรวมยอดการจัดส่ง")
    col1, col2 = st.columns(2)
    sum_before = df.groupby(truck_col).agg(จำนวนร้าน=pd.NamedAgg(column=truck_col, aggfunc='count'), ยอดรวม=pd.NamedAgg(column=vol_col, aggfunc='sum')).reset_index()
    sum_after = res_df.groupby('เบอร์รถใหม่').agg(จำนวนร้าน=pd.NamedAgg(column='เบอร์รถใหม่', aggfunc='count'), ยอดรวม=pd.NamedAgg(column=vol_col, aggfunc='sum')).reset_index()
    sum_after['ความหนาแน่น (%)'] = (sum_after['ยอดรวม'] / 4160 * 100).round(1).astype(str) + '%'

    with col1:
        st.markdown("**ก่อนปรับโครงสร้างสายส่ง**")
        st.dataframe(sum_before, use_container_width=True)
    with col2:
        st.markdown("**หลังปรับโครงสร้าง**")
        st.dataframe(sum_after, use_container_width=True)

    st.markdown("### 🗺️ แผนที่เปรียบเทียบการกระจายตัว (เชิงพื้นที่)")
    all_trucks_after = sorted(res_df['เบอร์รถใหม่'].dropna().unique().tolist())
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
        else: map_df_before = df[df[truck_col].astype(str) == (base_truck if selected_view == new_truck_name else selected_view)]
        map_df_after = res_df[res_df['เบอร์รถใหม่'].astype(str) == selected_view]
        color_mode = 'day'

    c_lat, c_lon = (map_df_after[lat_col].mean(), map_df_after[lon_col].mean()) if not map_df_after.empty else (res_df[lat_col].mean(), res_df[lon_col].mean())
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
        st.markdown("<div style='text-align:center; color:#002D62; font-weight:bold;'>โซนการวิ่งสายใหม่ (After)</div>", unsafe_allow_html=True)
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
    display_cols = [id_col, vol_col, truck_col, 'เบอร์รถใหม่', 'สถานะ']
    if name_col: display_cols.insert(1, name_col)
    st.dataframe(res_df[display_cols].rename(columns={truck_col: 'เบอร์รถเดิม (ก่อนปรับ)'}), use_container_width=True)
else:
    st.info("👈 กรุณาวางลิงก์ Google Sheets ที่แถบเมนูด้านซ้าย เพื่อเริ่มต้นใช้งาน Dashboard")
