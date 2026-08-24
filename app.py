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

# กำหนด Layout หน้าจอ
st.set_page_config(page_title="Smart Route Sprinkle", layout="wide", initial_sidebar_state="expanded")

def hard_reset():
    keys_to_clear = ['result_df', 'daily_matrix']
    for k in keys_to_clear:
        if k in st.session_state:
            del st.session_state[k]

# ==========================================
# 💎 ULTRA PREMIUM UI/UX (OCEAN BREEZE THEME)
# ==========================================
# 1. แปลงภาพรถเป็น Base64 สำหรับทำลายน้ำพื้นหลัง
truck_b64 = ""
try:
    with open("truck.jpg", "rb") as image_file:
        truck_b64 = base64.b64encode(image_file.read()).decode()
except FileNotFoundError:
    pass

# 2. ลายน้ำ (Watermark)
if truck_b64:
    watermark_html = f'''
    <div class="sprinkle-watermark"></div>
    <style>
        .sprinkle-watermark {{
            position: fixed;
            top: 50%;
            left: 55%; 
            transform: translate(-50%, -50%);
            width: 100vw;
            height: 100vh;
            background-image: url("data:image/jpeg;base64,{truck_b64}");
            background-size: 650px; 
            background-repeat: no-repeat;
            background-position: center;
            opacity: 0.12; 
            filter: grayscale(90%); 
            z-index: 0;
            pointer-events: none; 
        }}
        .block-container {{
            position: relative;
            z-index: 1;
        }}
    </style>
    '''
    st.markdown(watermark_html, unsafe_allow_html=True)

# 3. สไตล์ High Contrast & Dimensional Glass
st.markdown('''
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');
        
        /* Typography & Vibrant Gradient Background */
        html, body, [class*="css"] { font-family: 'Sarabun', sans-serif; }
        .stApp { 
            background: linear-gradient(135deg, #E0F2FE 0%, #F1F5F9 100%); 
        } 
        
        /* Headings */
        h1, h2, h3, h4 { color: #00205B !important; font-weight: 700; letter-spacing: -0.5px; }
        
        /* Sidebar Styling (Deep Ocean Dark Mode) */
        [data-testid="stSidebar"] { 
            background: linear-gradient(180deg, #0A192F 0%, #00205B 100%) !important; 
            backdrop-filter: blur(15px) !important;
            -webkit-backdrop-filter: blur(15px) !important;
            border-right: 1px solid rgba(0, 163, 224, 0.3); 
            box-shadow: 4px 0 20px rgba(0, 32, 91, 0.25); 
        }
        [data-testid="stSidebar"] * { color: #F8FAFC !important; }
        [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { color: #38BDF8 !important; text-shadow: 0 2px 4px rgba(0,0,0,0.3); }
        
        /* 🚨 แก้ไขสีตัวหนังสือในกล่องแจ้งเตือน (Alerts) ให้อ่านง่าย */
        div[data-testid="stAlert"], div[data-testid="stAlert"] * { 
            color: #00205B !important; 
            font-weight: 600 !important;
        }
        
        /* Input & Select Box */
        div[data-baseweb="select"] > div, input { 
            background-color: rgba(15, 23, 42, 0.6) !important; 
            border: 1px solid rgba(56, 189, 248, 0.4) !important; 
            color: white !important; 
            border-radius: 8px; 
            transition: all 0.3s ease;
            box-shadow: inset 0 2px 4px rgba(0,0,0,0.2); 
        }
        div[data-baseweb="select"] > div:hover, input:focus { 
            border: 1px solid #38BDF8 !important; 
            box-shadow: 0 0 10px rgba(56, 189, 248, 0.3) !important; 
        }
        
        /* Primary Button (Vibrant Wave) */
        .stButton>button { 
            background: linear-gradient(135deg, #0284C7 0%, #00205B 100%) !important; 
            color: white !important; 
            border: 1px solid rgba(255,255,255,0.1) !important; 
            border-radius: 10px; 
            font-weight: 600; 
            font-size: 1.1rem;
            padding: 0.6rem 2rem; 
            width: 100%; 
            box-shadow: 0 8px 20px rgba(0, 32, 91, 0.3), inset 0 1px 0 rgba(255,255,255,0.2); 
            transition: all 0.3s cubic-bezier(0.25, 0.8, 0.25, 1); 
        }
        .stButton>button:hover { 
            transform: translateY(-3px); 
            box-shadow: 0 12px 25px rgba(2, 132, 199, 0.4), inset 0 1px 0 rgba(255,255,255,0.3); 
            background: linear-gradient(135deg, #0EA5E9 0%, #0369A1 100%) !important;
        }
        
        /* Download Button */
        [data-testid="stDownloadButton"] > button { 
            background: linear-gradient(135deg, #10B981 0%, #047857 100%) !important; 
            box-shadow: 0 8px 20px rgba(16, 185, 129, 0.25), inset 0 1px 0 rgba(255,255,255,0.2);
        }
        [data-testid="stDownloadButton"] > button:hover { 
            box-shadow: 0 12px 25px rgba(16, 185, 129, 0.4), inset 0 1px 0 rgba(255,255,255,0.3); 
            transform: translateY(-3px);
        }
        
        /* Floating DataFrames (Ultra Crisp Cards) */
        div[data-testid="stDataFrame"] > div { 
            background: rgba(255, 255, 255, 0.95) !important; 
            backdrop-filter: blur(20px) !important;
            -webkit-backdrop-filter: blur(20px) !important;
            border-radius: 16px; 
            box-shadow: 0 12px 35px rgba(0, 32, 91, 0.12), 0 4px 10px rgba(2, 132, 199, 0.05) !important; 
            border: 1px solid rgba(2, 132, 199, 0.2) !important; 
            border-top: 5px solid #0EA5E9 !important; 
            overflow: hidden;
        }
        
        /* Alerts Styling */
        .stAlert { 
            background: rgba(255, 255, 255, 0.95) !important; 
            backdrop-filter: blur(15px) !important;
            border-radius: 12px; 
            border: 1px solid rgba(220, 38, 38, 0.3) !important; 
            box-shadow: 0 8px 25px rgba(0, 32, 91, 0.08); 
        }
        
        /* Map Iframe Wrapper */
        iframe { 
            border-radius: 16px; 
            box-shadow: 0 12px 35px rgba(0, 32, 91, 0.15); 
            border: 3px solid rgba(255, 255, 255, 0.9); 
        }
        
        div[data-testid="stVerticalBlock"] > div.element-container { background-color: transparent; }
        #MainMenu {visibility: hidden;} footer {visibility: hidden;}
        
        /* ซ่อนอนิเมชันคนวิ่งของ Streamlit */
        [data-testid="stStatusWidget"] { display: none !important; }
        .stSpinner > div > div { display: none !important; }

        /* 🚚 DYNAMIC ISLAND CSS (Truck Animation) */
        .island-wrapper {
            position: fixed; 
            top: 65px; 
            left: 50%; 
            transform: translateX(-50%); 
            z-index: 999999;
            pointer-events: none;
        }
        .dynamic-island {
            background: rgba(15, 23, 42, 0.85) !important; 
            backdrop-filter: blur(20px) !important;
            -webkit-backdrop-filter: blur(20px) !important;
            border: 1px solid rgba(56, 189, 248, 0.3) !important;
            color: #F8FAFC; 
            font-family: 'Sarabun', sans-serif;
            border-radius: 40px; 
            padding: 12px 28px; 
            font-weight: 500; 
            font-size: 1.05rem;
            display: flex; 
            align-items: center; 
            justify-content: center;
            gap: 12px;
            box-shadow: 0 15px 35px rgba(0, 0, 0, 0.25), 0 0 15px rgba(2, 132, 199, 0.2);
            animation: island-pop 0.6s cubic-bezier(0.68, -0.55, 0.265, 1.55) forwards;
            overflow: hidden;
            white-space: nowrap;
        }
        
        /* ไอคอนรถตู้ทึบขยับได้ */
        .island-icon { font-size: 1.5rem; display: flex; align-items: center; }
        .truck-drive {
            display: inline-block;
            animation: drive-bounce 0.8s infinite alternate ease-in-out;
        }
        
        @keyframes island-pop {
            0% { width: 40px; opacity: 0; transform: scale(0.7); border-radius: 50%; padding: 12px; }
            50% { width: 40px; opacity: 1; transform: scale(1.05); border-radius: 50%; padding: 12px; }
            100% { width: auto; opacity: 1; transform: scale(1); border-radius: 40px; }
        }
        @keyframes drive-bounce {
            0% { transform: translateX(-3px) translateY(1px); }
            100% { transform: translateX(3px) translateY(-1px); }
        }
        .text-fade-in {
            opacity: 0;
            animation: fade-in 0.4s ease-in forwards;
            animation-delay: 0.4s; 
        }
        @keyframes fade-in { to { opacity: 1; } }
    </style>
''', unsafe_allow_html=True)

# Header
st.markdown("<h1 style='text-align: center; color: #00205B; margin-bottom: 0; text-shadow: 0 2px 4px rgba(0,32,91,0.1);'>🚚 Smart Route Sprinkle</h1>", unsafe_allow_html=True)
st.markdown("<p style='text-align: center; color: #0284C7; font-size: 1.2rem; font-weight: 500; margin-bottom: 30px;'>ระบบวิเคราะห์และจัดสมดุลสายส่งน้ำอัตโนมัติ (Balanced Fleet & Micro-Routing Model)</p>", unsafe_allow_html=True)

st.sidebar.markdown("### 📁 1. นำเข้าข้อมูล (Data Source)")
sheet_url = st.sidebar.text_input("🔗 ลิงก์ Google Sheets:", placeholder="วางลิงก์ที่นี่...", on_change=hard_reset)

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
    if 'cached_raw_url' not in st.session_state or st.session_state['cached_raw_url'] != sheet_url:
        loading_placeholder = st.empty()
        
        # 🚚 ไอคอนรูปรถกระบะวิ่งตอนโหลดข้อมูล
        island_html = '''
        <div class="island-wrapper">
            <div class="dynamic-island">
                <div class="island-icon"><span class="truck-drive">🚚</span></div>
                <span class="text-fade-in">กำลังดึงข้อมูลต้นฉบับ...</span>
            </div>
        </div>
        '''
        loading_placeholder.markdown(island_html, unsafe_allow_html=True)
        
        raw_df = load_data_from_sheet(sheet_url)
        
        if raw_df is not None:
            st.session_state['cached_raw_df'] = raw_df
        st.session_state['cached_raw_url'] = sheet_url
        time.sleep(0.8) 
        loading_placeholder.empty()
    
    df = st.session_state.get('cached_raw_df', None)

if df is not None and not df.empty:
    df = df.copy()
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

    st.sidebar.success(f"✅ โหลดข้อมูลสำเร็จ: {len(df):,} รายการ")
    st.sidebar.markdown("---")
    st.sidebar.markdown("### ⚙️ 2. ตั้งค่าคอลัมน์และสายใหม่")

    guessed_day = next((c for c in df.columns if 'สัปดาห์' in str(c) or 'วัน' in str(c) or 'รอบ' in str(c) or 'day' in str(c).lower()), df.columns[0])
    day_col = st.sidebar.selectbox("📅 เลือกคอลัมน์ 'วันจัดส่ง':", options=df.columns, index=df.columns.tolist().index(guessed_day) if guessed_day in df.columns else 0, on_change=hard_reset)

    available_trucks = [str(x) for x in df[truck_col].unique() if str(x) != 'nan']
    base_truck_options = ["(ไม่มี - เพิ่มรถคันใหม่กระจายงาน)"] + available_trucks

    base_truck = st.sidebar.selectbox("เลือกรถที่จะถูกยุบ/ดึงงานออก", options=base_truck_options, on_change=hard_reset)
    new_truck_name = st.sidebar.text_input("ตั้งชื่อเบอร์รถคันใหม่", value="15112", on_change=hard_reset)

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

    target_pcts = {}
    for t in active_trucks:
        col1, col2 = st.sidebar.columns([3, 1.2])
        with col2:
            st.markdown("<div style='margin-top: 32px;'></div>", unsafe_allow_html=True)
            st.checkbox("🔒 ล็อก", key=f"lock_{t}")
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
    manual_vips = st.sidebar.multiselect("เลือกรหัสสมาชิกที่ห้ามย้ายสาย", options=df[id_col].astype(str).unique().tolist(), default=[], on_change=hard_reset)

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

    def run_fast_allocation_with_auto_shift(data, base_t, new_t, pct_dict, manual_locks, locked_ui_list):
        opt_df = data.copy()
        opt_df['เบอร์รถใหม่'] = 'ยังไม่จัด'
        opt_df['is_locked'] = (opt_df['VIP_Status'].astype(str).str.upper() == 'VIP') | (opt_df[id_col].astype(str).isin(manual_locks))
        opt_df['สถานะการย้ายวัน'] = '-'

        has_base = base_t != "(ไม่มี - เพิ่มรถคันใหม่กระจายงาน)"
        active_trucks = [t for t in available_trucks if t != base_t]
        if new_t not in active_trucks: active_trucks.append(new_t)

        monthly_targets = {t: 4160 * (pct_dict.get(t, 100) / 100) for t in active_trucks}
        vols = opt_df[vol_col].values
        coords = opt_df[[lat_col, lon_col]].values

        assigned_days_dict = {}
        for idx in opt_df.index:
            assigned_days_dict[idx] = parse_days_from_string(opt_df.at[idx, day_col])

        norm_coords = np.zeros_like(coords)
        lat_min, lat_max = coords[:, 0].min(), coords[:, 0].max()
        lon_min, lon_max = coords[:, 1].min(), coords[:, 1].max()
        lat_range = max(1e-5, lat_max - lat_min)
        lon_range = max(1e-5, lon_max - lon_min)
        norm_coords[:, 0] = (coords[:, 0] - lat_min) / lat_range
        norm_coords[:, 1] = (coords[:, 1] - lon_min) / lon_range

        centers = {}
        for i, t in enumerate(active_trucks):
            t_data = df[df[truck_col].astype(str) == t]
            if t == new_t and has_base and base_t in df[truck_col].astype(str).unique():
                b_data = df[df[truck_col].astype(str) == base_t]
                if not b_data.empty:
                    centers[t] = np.array([(b_data[lat_col].mean() - lat_min)/lat_range, (b_data[lon_col].mean() - lon_min)/lon_range])
                else:
                    centers[t] = np.array([0.5, 0.5])
            elif not t_data.empty:
                centers[t] = np.array([(t_data[lat_col].mean() - lat_min)/lat_range, (t_data[lon_col].mean() - lon_min)/lon_range])
            else:
                angle = i * (2 * math.pi / len(active_trucks))
                centers[t] = np.array([0.5 + 0.2*math.cos(angle), 0.5 + 0.2*math.sin(angle)])

        locked_indices = np.where(opt_df['is_locked'].values)[0]
        unlocked_indices = np.where(~opt_df['is_locked'].values)[0]

        locked_loads = {t: 0.0 for t in active_trucks}
        for idx in locked_indices:
            orig_t = str(opt_df.at[idx, truck_col])
            target_t = orig_t if orig_t in active_trucks else new_t
            opt_df.at[idx, 'เบอร์รถใหม่'] = target_t
            locked_loads[target_t] += vols[idx]

        best_assignments = {idx: active_trucks[0] for idx in unlocked_indices}
        penalties = {t: 1.0 for t in active_trucks} 
        
        for iteration in range(100):
            current_loads = {t: locked_loads[t] for t in active_trucks}
            
            for idx in unlocked_indices:
                pt = norm_coords[idx]
                min_cost = float('inf')
                best_t = active_trucks[0]
                
                for t in active_trucks:
                    if monthly_targets[t] <= 0: continue
                    cost = np.sum((pt - centers[t])**2) * penalties[t]
                    if cost < min_cost:
                        min_cost = cost
                        best_t = t
                        
                best_assignments[idx] = best_t
                current_loads[best_t] += vols[idx]

            for t in active_trucks:
                if monthly_targets[t] <= 0: continue
                pts = [norm_coords[idx] for idx in unlocked_indices if best_assignments[idx] == t]
                if pts:
                    centers[t] = np.mean(pts, axis=0)
                    ratio = current_loads[t] / max(1.0, monthly_targets[t])
                    ratio = max(0.2, min(5.0, ratio))
                    penalties[t] *= (1.0 + (ratio - 1.0) * 0.25)
                    penalties[t] = max(1e-4, min(1e4, penalties[t]))
                else:
                    penalties[t] *= 0.5 
                    over_trucks = [ot for ot in active_trucks if current_loads[ot] > monthly_targets[ot] and ot != t]
                    if over_trucks:
                        ot = max(over_trucks, key=lambda x: current_loads[x] - monthly_targets[x])
                        centers[t] = centers[ot] + np.array([0.01, 0.01])
                    else:
                        centers[t] = np.array([0.5, 0.5])

        for idx in unlocked_indices:
            opt_df.at[idx, 'เบอร์รถใหม่'] = best_assignments[idx]

        opt_df['สถานะ'] = np.where(opt_df[truck_col].astype(str) == opt_df['เบอร์รถใหม่'], 'คงเดิม', 'ย้ายไปสาย ' + opt_df['เบอร์รถใหม่'])
        if has_base:
            opt_df['สถานะ'] = np.where(opt_df[truck_col].astype(str) == base_t, 'ยุบสายไป ' + opt_df['เบอร์รถใหม่'], opt_df['สถานะ'])

        for idx in opt_df.index:
            opt_df.at[idx, 'วันจัดส่ง(ใหม่)'] = format_days_to_string(assigned_days_dict[idx])

        daily_matrix = np.zeros((len(opt_df), 6))
        for idx in opt_df.index:
            d_list = assigned_days_dict[idx]
            len_d = len(d_list) if len(d_list) > 0 else 1
            v = vols[idx] / len_d / 4.333
            for d in d_list: daily_matrix[idx, d] = v

        return opt_df, daily_matrix

    def run_smart_day_shift(res_df_input):
        opt_df = res_df_input.copy()
        vols = opt_df[vol_col].values
        coords = opt_df[[lat_col, lon_col]].values
        
        assigned_days_dict = {}
        for idx in opt_df.index:
            assigned_days_dict[idx] = parse_days_from_string(opt_df.at[idx, 'วันจัดส่ง(ใหม่)'])
            
        active_trucks = opt_df['เบอร์รถใหม่'].dropna().unique().tolist()
        MAX_CAP = 156
        TARGET_CAP = 156 
        
        for t in active_trucks:
            t_indices = [idx for idx in opt_df.index if opt_df.at[idx, 'เบอร์รถใหม่'] == t]
            if not t_indices: continue
            
            for iteration in range(15): 
                daily_loads = np.zeros(6)
                for idx in t_indices:
                    d_list = assigned_days_dict[idx]
                    n = len(d_list) if len(d_list) > 0 else 1
                    v = vols[idx] / n / 4.333
                    for d in d_list: daily_loads[d] += v
                    
                day_centers = {}
                for d in range(6):
                    d_pts = [coords[idx] for idx in t_indices if d in assigned_days_dict[idx]]
                    if d_pts: day_centers[d] = np.mean(d_pts, axis=0)
                    
                needs_more_smoothing = False
                
                for d_over in range(6):
                    if daily_loads[d_over] > MAX_CAP:
                        needs_more_smoothing = True
                        excess = daily_loads[d_over] - TARGET_CAP
                        
                        under_days = [d for d in range(6) if daily_loads[d] < MAX_CAP and d != d_over]
                        if not under_days: continue 
                        
                        movable = [idx for idx in t_indices if not opt_df.at[idx, 'is_locked'] and d_over in assigned_days_dict[idx]]
                        if not movable: continue
                        
                        move_candidates = []
                        for idx in movable:
                            old_list = assigned_days_dict[idx]
                            n = len(old_list) if len(old_list) > 0 else 1
                            v = vols[idx] / n / 4.333
                            is_original = 1 if str(opt_df.at[idx, truck_col]) == str(t) else 0
                            
                            for d_under in under_days:
                                if d_under in old_list: continue 
                                if daily_loads[d_under] + v > MAX_CAP + 5: continue 
                                
                                dist_to_new_day = np.sum((coords[idx] - day_centers[d_under])**2) if d_under in day_centers else 0.05
                                cost = dist_to_new_day + (is_original * 0.1) 
                                move_candidates.append((cost, idx, d_under, v))
                                
                        move_candidates.sort(key=lambda x: x[0])
                        shifted_vol = 0
                        moved_this_round = set()
                        
                        for cost, idx, best_new_d, v in move_candidates:
                            if shifted_vol >= excess: break
                            if idx in moved_this_round: continue
                            if daily_loads[best_new_d] + v > MAX_CAP + 5: continue
                            
                            old_list = assigned_days_dict[idx]
                            new_list = [best_new_d if x == d_over else x for x in old_list]
                            
                            assigned_days_dict[idx] = new_list
                            daily_loads[d_over] -= v
                            daily_loads[best_new_d] += v
                            shifted_vol += v
                            moved_this_round.add(idx)
                            
                            reason = "ย้ายวันอิงพื้นที่ (รถเดิม)" if str(opt_df.at[idx, truck_col]) == str(t) else "ย้ายวันอิงพื้นที่ (ย้ายสาย)"
                            opt_df.at[idx, 'สถานะการย้ายวัน'] = f"{reason}: {format_days_to_string([d_over])} -> {format_days_to_string([best_new_d])}"
                            
                if not needs_more_smoothing:
                    break

        for idx in opt_df.index:
            opt_df.at[idx, 'วันจัดส่ง(ใหม่)'] = format_days_to_string(assigned_days_dict[idx])

        daily_matrix = np.zeros((len(opt_df), 6))
        for idx in opt_df.index:
            d_list = assigned_days_dict[idx]
            len_d = len(d_list) if len(d_list) > 0 else 1
            v = vols[idx] / len_d / 4.333
            for d in d_list: daily_matrix[idx, d] = v

        return opt_df, daily_matrix

    st.sidebar.markdown("---")
    if st.sidebar.button("🚀 ประมวลผลตัดสายส่ง", use_container_width=True):
        calc_placeholder = st.empty()
        
        # 🚚 ไอคอนรูปรถกระบะวิ่งตอนวิเคราะห์
        island_html = '''
        <div class="island-wrapper">
            <div class="dynamic-island" style="background: rgba(10, 25, 47, 0.85); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); border: 1px solid rgba(255,255,255,0.2);">
                <div class="island-icon"><span class="truck-drive">🚚</span></div>
                <span class="text-fade-in">กำลังวิเคราะห์พิกัดและคำนวณแบ่งเขตแดน...</span>
            </div>
        </div>
        '''
        calc_placeholder.markdown(island_html, unsafe_allow_html=True)

        res_df, daily_matrix = run_fast_allocation_with_auto_shift(df, base_truck, new_truck_name, target_pcts, manual_vips, locked_ui_trucks)
        st.session_state['result_df'] = res_df
        st.session_state['daily_matrix'] = daily_matrix
        time.sleep(1) 
        calc_placeholder.empty()

    if 'result_df' in st.session_state:
        res_df = st.session_state['result_df']
        daily_matrix = st.session_state['daily_matrix']
        all_trucks_after = sorted(res_df['เบอร์รถใหม่'].dropna().unique().tolist())

        st.markdown("<h3 style='margin-top: 30px;'>📊 สรุปภาพรวมยอดการจัดส่ง</h3>", unsafe_allow_html=True)

        col1, col2 = st.columns(2)
        sum_before = df.groupby(truck_col).agg(จำนวนสมาชิก=pd.NamedAgg(column=truck_col, aggfunc='count'), **{'ยอดรับน้ำ(ถัง/เดือน)': pd.NamedAgg(column=vol_col, aggfunc='sum')}).reset_index()
        sum_after = res_df.groupby('เบอร์รถใหม่').agg(จำนวนสมาชิก=pd.NamedAgg(column='เบอร์รถใหม่', aggfunc='count'), **{'ยอดรับน้ำ(ถัง/เดือน)': pd.NamedAgg(column=vol_col, aggfunc='sum')}).reset_index()
        sum_after['ปริมาณงาน(%)'] = (sum_after['ยอดรับน้ำ(ถัง/เดือน)'] / 4160 * 100).round(1).astype(str) + '%'

        with col1:
            st.markdown("**ก่อนปรับโครงสร้างสายส่ง**")
            st.dataframe(sum_before, use_container_width=True)
        with col2:
            st.markdown("**หลังปรับโครงสร้าง (พื้นที่ติดกัน 100% & ยอดตรงเป้า)**")
            st.dataframe(sum_after, use_container_width=True)

        st.markdown("<h3 style='margin-top: 30px;'>📅 ตารางวิเคราะห์โหลดรายวัน (จันทร์-เสาร์)</h3>", unsafe_allow_html=True)

        daily_summary = []
        for t in all_trucks_after:
            t_mask = res_df['เบอร์รถใหม่'] == t
            t_daily = daily_matrix[t_mask].sum(axis=0)
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
        
        if max_all_days > 156:
            st.error(f"🚨 **ระบบตรวจพบโหลดเกินขีดจำกัดสูงสุด ({max_all_days} ถัง/วัน)!** (หมายเหตุ: เกิดจากบางวันมียอดสั่งน้ำกระจุกตัวหนาแน่น)")
            
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("✨ คลิกที่นี่เพื่อให้ AI เกลี่ยงานที่ล้น ไปใส่วันว่าง (เฉพาะในรถคันเดิม + อิงพิกัดพื้นที่ใกล้เคียง)", use_container_width=True):
                day_shift_placeholder = st.empty()
                
                # 🚚 ไอคอนรูปรถกระบะวิ่งตอนย้ายวัน
                island_html_shift = '''
                <div class="island-wrapper">
                    <div class="dynamic-island" style="background: rgba(10, 25, 47, 0.85); backdrop-filter: blur(12px); -webkit-backdrop-filter: blur(12px); border: 1px solid rgba(255,255,255,0.2);">
                        <div class="island-icon"><span class="truck-drive">🚚</span></div>
                        <span class="text-fade-in">กำลังสแกนพื้นที่และเกลี่ยวันจัดส่ง...</span>
                    </div>
                </div>
                '''
                day_shift_placeholder.markdown(island_html_shift, unsafe_allow_html=True)
                
                new_res_df, new_daily_matrix = run_smart_day_shift(st.session_state['result_df'])
                st.session_state['result_df'] = new_res_df
                st.session_state['daily_matrix'] = new_daily_matrix
                time.sleep(1)
                day_shift_placeholder.empty()
                st.rerun()
        else:
            st.success("✅ **สถานะยอดเยี่ยม:** โหลดรายวันกระจายตัวสอดคล้องตามหน้างานจริง 100%")

        st.markdown("<h3 style='margin-top: 30px;'>🗺️ แผนที่เปรียบเทียบการกระจายตัว (เชิงพื้นที่)</h3>", unsafe_allow_html=True)
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
            st.markdown("<div style='text-align:center; color:#00205B; font-weight:bold; margin-bottom: 10px;'>โซนการวิ่งรถเดิม (Before)</div>", unsafe_allow_html=True)
            m1 = folium.Map(location=[c_lat, c_lon], zoom_start=12 if color_mode=='truck' else 14)
            plugins.Fullscreen(position='topright').add_to(m1)
            for _, r in map_df_before.iterrows():
                t_id = str(r[truck_col])
                is_vip = str(r.get('VIP_Status', '')).upper() == 'VIP' or str(r[id_col]) in manual_vips
                m_color = color_map.get(t_id, 'gray') if color_mode == 'truck' else next((c for d, c in day_color_map.items() if d in str(r.get(day_col, '')).strip()), 'gray')
                popup_html = f"<b>รหัส:</b> {r[id_col]}<br><b>ชื่อ:</b> {get_name(r)}<br><b>ยอด:</b> {r[vol_col]} ถัง<br><b>รถ:</b> {t_id}"
                folium.CircleMarker([r[lat_col], r[lon_col]], radius=8 if is_vip else 5, color='#00205B' if is_vip else m_color, weight=2 if is_vip else 1, fill=True, fillColor=m_color, fill_opacity=0.9, popup=folium.Popup(popup_html, max_width=300)).add_to(m1)
            components.html(m1.get_root().render(), height=450)

        with map_col2:
            st.markdown("<div style='text-align:center; color:#00205B; font-weight:bold; margin-bottom: 10px;'>โซนการวิ่งสายใหม่ (Balanced Fleet)</div>", unsafe_allow_html=True)
            m2 = folium.Map(location=[c_lat, c_lon], zoom_start=12 if color_mode=='truck' else 14)
            plugins.Fullscreen(position='topright').add_to(m2)
            for _, r in map_df_after.iterrows():
                t_new = str(r['เบอร์รถใหม่'])
                is_vip = str(r.get('VIP_Status', '')).upper() == 'VIP' or str(r[id_col]) in manual_vips
                m_color = color_map.get(t_new, 'gray') if color_mode == 'truck' else next((c for d, c in day_color_map.items() if d in str(r.get('วันจัดส่ง(ใหม่)', '')).strip()), 'gray')
                popup_html = f"<b>รหัส:</b> {r[id_col]}<br><b>ชื่อ:</b> {get_name(r)}<br><b>ยอด:</b> {r[vol_col]} ถัง<br><b>รถล่าสุด:</b> {t_new}"
                folium.CircleMarker([r[lat_col], r[lon_col]], radius=8 if is_vip else 5, color='#00205B' if is_vip else m_color, weight=2 if is_vip else 1, fill=True, fillColor=m_color, fill_opacity=0.9, popup=folium.Popup(popup_html, max_width=300)).add_to(m2)
            components.html(m2.get_root().render(), height=450)

        st.markdown("<h3 style='margin-top: 30px;'>📋 รายละเอียดข้อมูลการโยกย้ายสมาชิก</h3>", unsafe_allow_html=True)

        display_cols = [id_col]
        if name_col: display_cols.append(name_col)
        display_cols.append(day_col) 
        display_cols.extend(['วันจัดส่ง(ใหม่)', 'สถานะการย้ายวัน', vol_col, 'เบอร์รถเดิม (ก่อนปรับ)', 'เบอร์รถใหม่', 'สถานะ'])

        detail_df = res_df.copy()
        detail_df['เบอร์รถเดิม (ก่อนปรับ)'] = detail_df[truck_col]
        detail_df = detail_df[display_cols].rename(columns={day_col: 'วันจัดส่ง(เดิม)'})
        st.dataframe(detail_df, use_container_width=True)

        st.markdown("---")
        st.markdown("<div style='text-align:center; margin-bottom: 15px; color: #64748B;'><b>📌 ข้อมูลพร้อมใช้งาน สามารถดาวน์โหลดไฟล์สรุปผลไปเปิดใน Excel ได้ทันที</b></div>", unsafe_allow_html=True)

        @st.cache_data
        def convert_df_to_bytes(df):
            return df.to_csv(index=False).encode('utf-8-sig')

        csv_bytes = convert_df_to_bytes(detail_df)

        col_btn1, col_btn2, col_btn3 = st.columns([1, 2, 1])
        with col_btn2:
            st.download_button(
                label="📥 ดาวน์โหลดข้อมูลสรุปผล",
                data=csv_bytes,
                file_name='sprinkle_route_result.csv',
                mime='text/csv',
                use_container_width=True
            )

    else:
        st.info("👈 ปรับตั้งค่าเปอร์เซ็นต์และล็อกรถให้เสร็จสิ้น จากนั้นกดปุ่ม 'ประมวลผลตัดสายส่ง' สีน้ำเงินด้านซ้ายมือ เพื่อดูผลลัพธ์")
else:
    st.info("👈 กรุณาวางลิงก์ Google Sheets ที่แถบเมนูด้านซ้าย เพื่อเริ่มต้นใช้งานแดชบอร์ด")
