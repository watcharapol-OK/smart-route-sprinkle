# =====================================================================================
#  MODERN PREMIUM UI/CSS REBUILD — STREAMLIT (Fixed Syntax)
# =====================================================================================

st.markdown('''
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&family=Sarabun:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'Sarabun', 'Plus+Jakarta+Sans', sans-serif !important;
}

.stApp {
    background: #F8FAFC !important;
}

/* -------------------------------------------------------------
   SIDEBAR STYLING (Modern Dark Navy Glass)
   ------------------------------------------------------------- */
[data-testid="stSidebar"] {
    background: #0F172A !important;
    border-right: 1px solid #1E293B !important;
}
[data-testid="stSidebar"] * {
    color: #F8FAFC !important;
}
[data-testid="stSidebar"] label, [data-testid="stSidebar"] .stMarkdown p {
    color: #38BDF8 !important;
    font-weight: 600 !important;
    font-size: 0.95rem !important;
}
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
    color: #38BDF8 !important;
    border-bottom: 1px solid #1E293B !important;
    padding-bottom: 8px !important;
}

/* -------------------------------------------------------------
   MODERN TABS NAVIGATION
   ------------------------------------------------------------- */
.stTabs [data-baseweb="tab-list"] {
    gap: 8px;
    background-color: #E2E8F0;
    padding: 6px;
    border-radius: 12px;
}
.stTabs [data-baseweb="tab"] {
    height: 44px;
    background-color: transparent;
    border-radius: 8px;
    color: #475569;
    font-weight: 700;
    padding: 0 20px;
    border: none;
}
.stTabs [aria-selected="true"] {
    background-color: #FFFFFF !important;
    color: #0284C7 !important;
    box-shadow: 0 4px 12px rgba(0,0,0,0.08);
}

/* -------------------------------------------------------------
   CARDS & CONTAINERS
   ------------------------------------------------------------- */
.metric-card-modern {
    background: #FFFFFF;
    border-radius: 14px;
    padding: 20px;
    border: 1px solid #E2E8F0;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    transition: transform 0.2s;
}
.metric-card-modern:hover {
    transform: translateY(-2px);
    box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.08);
}

/* -------------------------------------------------------------
   BUTTONS & INPUTS
   ------------------------------------------------------------- */
.stButton>button {
    background: linear-gradient(135deg, #0284C7 0%, #0369A1 100%) !important;
    color: #FFFFFF !important;
    border: none !important;
    border-radius: 10px;
    font-weight: 700;
    padding: 0.6rem 1.2rem;
    box-shadow: 0 4px 12px rgba(2,132,199,0.25);
    transition: all 0.2s;
}
.stButton>button:hover {
    background: linear-gradient(135deg, #0369A1 0%, #075985 100%) !important;
    box-shadow: 0 6px 16px rgba(2,132,199,0.35);
}

/* -------------------------------------------------------------
   CUSTOM TABLES
   ------------------------------------------------------------- */
.enterprise-table {
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    background: #FFFFFF;
    border-radius: 12px;
    overflow: hidden;
    border: 1px solid #E2E8F0;
    box-shadow: 0 4px 6px -1px rgba(0,0,0,0.02);
}
.enterprise-table th {
    background: #F1F5F9;
    color: #334155;
    font-weight: 700;
    padding: 12px 16px;
    text-align: center;
    border-bottom: 2px solid #E2E8F0;
}
.enterprise-table td {
    padding: 12px 16px;
    text-align: center;
    border-bottom: 1px solid #F1F5F9;
    color: #475569;
    font-size: 0.95rem;
}
.enterprise-table tr:hover td {
    background: #F8FAFC;
}
</style>
''', unsafe_allow_html=True)
