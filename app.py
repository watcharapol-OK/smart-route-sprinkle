# =====================================================================================
#  MODERN PREMIUM UI/CSS REBUILD — STREAMLIT
# =====================================================================================

# 1. การกำหนดสไตล์ CSS ภาพรวม (Modern Enterprise & Glassmorphism)
st.markdown(f'''
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Sarabun:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] {{
    font-family: 'Sarabun', 'Plus+Jakarta+Sans', sans-serif !important;
}}

.stApp {{
    background: #F8FAFC !important;
}}

/* -------------------------------------------------------------
   SIDEBAR STYLING (Modern Dark Navy Glass)
   ------------------------------------------------------------- */
[data-testid="stSidebar"] {{
    background: #0F172A !important;
    border-right: 1px solid #1E293B !important;
}}
[data-testid="stSidebar"] * {{
    color: #F8FAFC !important;
}}
[data-testid="stSidebar"] label, [data-testid="stSidebar"] .stMarkdown p {{
    color: #38BDF8 !important;
    font-weight: 600 !important;
    font-size: 0.95rem !important;
}}
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {{
    color: #38BDF8 !important;
    border-bottom: 1px solid #1E293B !important;
    padding-bottom: 8px !important;
}}

/* -------------------------------------------------------------
   MODERN TABS NAVIGATION
   ------------------------------------------------------------- */
.stTabs [data-baseweb="tab-list"] {{
    gap: 8px;
    background-color: #E2E8F0;
    padding: 6px;
    border-radius: 12px;
}}
.stTabs [data-baseweb="tab"] {{
    height: 44px;
    background-color: transparent;
    border-radius: 8px;
    color: #475569;
    font-weight: 700;
    padding: 0 20px;
    border: none;
}}
.stTabs [aria-selected="true"] {{
    background-color: #FFFFFF !important;
    color: #0284C7 !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.08);
}}

/* -------------------------------------------------------------
   CARDS & CONTAINERS
   ------------------------------------------------------------- */
.metric-card-modern {{
    background: #FFFFFF;
    border-radius: 14px;
    padding: 20px;
    border: 1px solid #E2E8F0;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    transition: transform 0.2s;
}}
.metric-card-modern:hover {{
    transform: translateY(-2px);
    box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.08);
}}

/* -------------------------------------------------------------
   BUTTONS & INPUTS
   ------------------------------------------------------------- */
.stButton>button {{
    background: linear-gradient(135deg, #0284C7 0%, #0369A1 100%) !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 10px;
    font-weight: 700;
    padding: 0.6rem 1.2rem;
    box-shadow: 0 4px 12px rgba(2,132,199,0.25);
    transition: all 0.2s;
}}
.stButton>button:hover {{
    background: linear-gradient(135deg, #0369A1 0%, #075985 100%) !important;
    box-shadow: 0 6px 16px rgba(2,132,199,0.35);
}}

/* -------------------------------------------------------------
   CUSTOM TABLES
   ------------------------------------------------------------- */
.enterprise-table {{
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    background: #FFFFFF;
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid #E2E8F0;
    box-shadow: 0 4px 6px -1px rgba(0,0,0,0.02);
}}
.enterprise-table th {{
    background: #F1F5F9;
    color: #334155;
    font-weight: 700;
    padding: 12px 16px;
    text-align: center;
    border-bottom: 2px solid #E2E8F0;
}}
.enterprise-table td {{
    padding: 12px 16px;
    text-align: center;
    border-bottom: 1px solid #F1F5F9;
    color: #475569;
    font-size: 0.95rem;
}}
.enterprise-table tr:hover td {{
    background: #F8FAFC;
}}
</style>
''', unsafe_allow_html=True)


# 2. ฟังก์ชันเรนเดอร์การ์ดสถิติแบบพรีเมียม
def render_enterprise_metric(label: str, value: str, delta: str = "", status: str = "normal"):
    border_colors = {"good": "#10B981", "warning": "#F59E0B", "danger": "#EF4444", "normal": "#0284C7"}
    bg_delta = {"good": "#ECFDF5", "warning": "#FFFBEB", "danger": "#FEF2F2", "normal": "#F0F9FF"}
    txt_delta = {"good": "#059669", "warning": "#D97706", "danger": "#DC2626", "normal": "#0284C7"}
    
    bc = border_colors.get(status, "#0284C7")
    dc = bg_delta.get(status, "#F0F9FF")
    tc = txt_delta.get(status, "#0284C7")
    
    delta_html = ""
    if delta:
        delta_html = f'''
        <div style="margin-top: 8px;">
            <span style="background:{dc}; color:{tc}; padding:3px 10px; border-radius:6px; font-weight:700; font-size:0.85rem; display:inline-block;">
                {delta}
            </span>
        </div>
        '''
        
    html = f'''
    <div class="metric-card-modern" style="border-left: 5px solid {bc};">
        <div style="color: #64748B; font-size: 0.9rem; font-weight: 600; margin-bottom: 4px;">{label}</div>
        <div style="color: #0F172A; font-size: 1.8rem; font-weight: 800; line-height: 1.2;">{value}</div>
        {delta_html}
    </div>
    '''
    st.markdown(html, unsafe_allow_html=True)


# 3. โครงสร้างหลักจัดระเบียบหน้าจอด้วย Tabs (แทนการเลื่อนยาวๆ)
st.title("🚛 Smart Route Rebalancer — Enterprise")
st.caption("ระบบวิเคราะห์และจัดสายส่งน้ำอัจฉริยะ (Zero-Overlap Satellite Pocket Architecture)")

# แบ่งหน้าจอเป็น 3 แท็บหลักสะอาดตา
tab1, tab2, tab3 = st.tabs(["📊 1. ภาพรวมและวินิจฉัย (Dashboard)", "⚙️ 2. ตั้งค่าเงื่อนไขและจัดการรถ (Fleet Rules)", "🗺️ 3. แผนที่และตารางจัดสาย (Interactive Maps)"])

with tab1:
    st.markdown("### 📈 ตัวชี้วัดผลลัพธ์เพื่อการตัดสินใจ (Executive KPIs)")
    # แสดง KPI Cards ด้วยฟังก์ชันใหม่
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        render_enterprise_metric("รถเกินเพดาน", "2 คัน", delta="-1 คัน", status="danger")
    with col2:
        render_enterprise_metric("โหลดสูงสุด", "341 ถัง/วัน", delta="+79 ถัง", status="warning")
    with col3:
        render_enterprise_metric("ความกระชับโซน", "5.25 กม.", delta="-1.55 กม.", status="good")
    with col4:
        render_enterprise_metric("ลูกค้าที่โยกย้าย", "548 ราย", delta="35.9% ของสาขา", status="normal")
        
    st.markdown("---")
    st.markdown("### 🩺 ผลวินิจฉัยสถานะรถปัจจุบัน (ก่อนปรับ)")
    # ใส่ตารางข้อมูลสรุปภาพรวม

with tab2:
    st.markdown("### 🎛️ กำหนดเงื่อนไขการควบคุมและจัดการรถ")
    col_a, col_b = st.columns(2)
    with col_a:
        st.info("ตั้งค่าสัดส่วนแกนกลาง (Core Ratio) และค่าเผื่อเป้าหมาย")
    with col_b:
        st.info("เลือกรถผู้ให้ (Donors) และล็อกรถที่ไม่ต้องการให้คำนวณ")

with tab3:
    st.markdown("### 🗺️ แผนที่เปรียบเทียบเชิงพื้นที่ (Before vs. After)")
    st.markdown("เปรียบเทียบการกระจายตัวของหมุดจุดจัดส่งก่อนและหลังการปรับเกลี่ยงาน")
    # พื้นที่แสดงแผนที่ Side-by-Side
