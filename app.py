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

# -------------------------------------------------------------
# 💎 ABSOLUTE HIGH-CONTRAST LIQUID GLASS SYSTEM (CRITICAL DROPDOWN FIX)
# -------------------------------------------------------------
st.markdown('''
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Sarabun:wght@300;400;500;600;700&display=swap');
        
        /* 1. Global High-Contrast Text Reset */
        html, body, [class*="css"], p, span, label, div, small, li, a, h1, h2, h3, h4, h5, h6 { 
            font-family: 'Sarabun', sans-serif !important; 
            color: #FFFFFF !important;
            font-weight: 400;
        }

        /* App Background: Rich Midnight Gradient for Liquid Glass Effect */
        .stApp { 
            background: linear-gradient(135deg, #000B18 0%, #001F3F 50%, #002D62 100%) !important;
            background-attachment: fixed;
        }

        /* 2. Headings: Absolute Clarity with Gold Accent */
        h1, h2, h3, h4, h5, h6 { 
            color: #FFD700 !important; 
            font-weight: 700 !important; 
            letter-spacing: 0.5px;
            text-shadow: 0 2px 4px rgba(0,0,0,0.6);
        }
        
        /* Subheaders, Captions and Markdown descriptions */
        .stMarkdown p, span, div[data-testid="stMarkdownContainer"] p, [data-testid="stCaptionContainer"], .stCaption {
            color: #F1F5F9 !important;
            opacity: 1 !important;
        }

        /* 3. Sidebar: Frosted Liquid Glass with Crisp Bright Text */
        [data-testid="stSidebar"] { 
            background: rgba(0, 15, 31, 0.9) !important; 
            backdrop-filter: blur(25px);
            -webkit-backdrop-filter: blur(25px);
            border-right: 1px solid rgba(212, 175, 55, 0.35); 
        }
        [data-testid="stSidebar"] label, [data-testid="stSidebar"] .stMarkdown p {
            color: #F3E5AB !important;
            font-weight: 600 !important;
        }
        [data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 { 
            color: #FFD700 !important; 
            border-bottom: 1px solid rgba(212, 175, 55, 0.3);
            padding-bottom: 8px;
        }

        /* 4. Input Fields & Selectboxes (High Contrast Glass) */
        div[data-baseweb="select"] > div, input { 
            background: rgba(0, 40, 80, 0.75) !important; 
            backdrop-filter: blur(12px);
            border: 1px solid rgba(212, 175, 55, 0.55) !important; 
            color: #FFFFFF !important;
            border-radius: 8px !important;
            font-weight: 500;
        }
        input::placeholder {
            color: #CBD5E1 !important;
            opacity: 1 !important;
        }
        input:focus, div[data-baseweb="select"] > div:focus-within {
            border-color: #FFD700 !important;
            box-shadow: 0 0 12px rgba(255, 215, 0, 0.4) !important;
        }

        /* 🚨 CRITICAL FIX: Dropdown Options List (Legibility) 🚨 */
        /* Target the BaseWeb Dropdown Menu container */
        div[role="listbox"],
        ul[role="listbox"],
        div[data-baseweb="menu"],
        [data-baseweb="select-dropdown"] {
            background: #F8FAFC !important; /* Clean white background for list */
            border: 1px solid #D4AF37 !important;
            border-radius: 8px !important;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4) !important;
        }
        /* Target the Options (List Items) */
        div[role="option"],
        ul[role="listbox"] > li {
            color: #0F172A !important; /* Dark crisp text for options */
            font-weight: 500 !important;
            padding: 10px 16px !important;
            border-bottom: 1px solid #E2E8F0 !important;
        }
        /* Last option shouldn't have a border */
        div[role="option"]:last-child {
             border-bottom: none !important;
        }
        /* Target the Option Text (Force dark color inside options) */
        div[role="option"] > div,
        div[role="option"] span {
            color: #0F172A !important;
            font-weight: 500 !important;
        }
        /* Hover State for Options */
        div[role="option"]:hover {
            background-color: #FFF8E1 !important; /* Soft gold hover */
        }
        /* Selected State for Options */
        div[role="option"][aria-selected="true"] {
            background-color: #FFD700 !important; /* Gold for selected */
            color: #000B18 !important;
        }
        div[role="option"][aria-selected="true"] div,
        div[role="option"][aria-selected="true"] span {
            color: #000B18 !important;
        }

        /* 5. Luxury Gold Gradient Buttons */
        .stButton>button { 
            background: linear-gradient(135deg, #D4AF37 0%, #AA8C2C 100%) !important; 
            color: #000B18 !important; 
            border: none !important; 
            border-radius: 8px; 
            font-weight: 700; 
            padding: 0.6rem 2rem; 
            width: 100%; 
            letter-spacing: 0.5px;
            box-shadow: 0 4px 15px rgba(212, 175, 55, 0.4);
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1); 
        }
        .stButton>button:hover { 
            background: linear-gradient(135deg, #F3E5AB 0%, #D4AF37 100%) !important; 
            box-shadow: 0 6px 20px rgba(255, 215, 0, 0.6); 
            transform: translateY(-2px); 
        }

        /* 6. DataFrames: Glass Card Container with Crystal Clear Legibility */
        .stDataFrame { 
            background: rgba(0, 31, 63, 0.7) !important; 
            backdrop-filter: blur(16px);
            -webkit-backdrop-filter: blur(16px);
            padding: 1.2rem; 
            border-radius: 14px; 
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.45); 
            border: 1px solid rgba(212, 175, 55, 0.35); 
            border-top: 3px solid #D4AF37;
        }
        .stDataFrame td, .stDataFrame th, .stDataFrame div {
            color: #0F172A !important; /* Force dark crisp text inside table cells for absolute clarity against white table grid */
            font-weight: 500 !important;
        }

        /* 7. Premium Smooth Highway Loader (Truck Steady, Road Moving) */
        .stSpinner > div > div { display: none !important; }
        
        @keyframes moveRoad {
            0% { background-position: 0 0; }
            100% { background-position: -120px 0; }
        }
        @keyframes truckVibration {
            0% { transform: translateY(0px); }
            50% { transform: translateY(-2px); }
            100% { transform: translateY(0px); }
        }

        .custom-truck-loader { 
            text-align: center; 
            padding: 2.2rem; 
            color: #FFD700; 
            font-weight: bold; 
            font-size: 1.2rem; 
            border-radius: 14px; 
            background: rgba(0, 31, 63, 0.9); 
            backdrop-filter: blur(16px);
            border: 1px solid rgba(212, 175, 55, 0.5); 
            margin-bottom: 20px; 
            box-shadow: 0 8px 32px 0 rgba(0, 0, 0, 0.45);
            position: relative;
            overflow: hidden;
        }
        .custom-truck-loader::after {
            content: "";
            position: absolute;
            bottom: 10px;
            left: 0;
            width: 100%;
            height: 4px;
            background: repeating-linear-gradient(90deg, #D4AF37, #D4AF37 35px, transparent 35px, transparent 70px);
            animation: moveRoad 1s linear infinite;
        }
        .custom-truck-loader img { 
            width: 150px; 
            animation: truckVibration 0.35s ease-in-out infinite; 
            filter: drop-shadow(0 4px 8px rgba(0,0,0,0.6));
            display: inline-block;
            margin-bottom: 8px;
        }

        /* 8. Download Button: Emerald Glass Style */
        [data-testid="stDownloadButton"] > button { 
            background: linear-gradient(135deg, #28A745 0%, #1E7E34 100%) !important; 
            color: #FFFFFF !important; 
            border: 1px solid rgba(40, 167, 69, 0.5) !important; 
            border-radius: 8px !important;
            padding: 0.8rem 2rem; 
            font-size: 1.1rem; 
            font-weight: 700;
            box-shadow: 0 4px 15px rgba(40, 167, 69, 0.4);
            transition: all 0.3s ease;
        }
        [data-testid="stDownloadButton"] > button:hover { 
            background: linear-gradient(135deg, #218838 0%, #155724 100%) !important; 
            box-shadow: 0 6px 20px rgba(40, 167, 69, 0.6); 
            transform: translateY(-2px);
        }

        /* 9. Metric / Info / Alert Cards */
        div.stAlert, div[data-testid="stInfo"], div[data-testid="stSuccess"], div[data-testid="stWarning"] {
            background: rgba(0, 33, 66, 0.85) !important;
            backdrop-filter: blur(12px);
            border: 1px solid rgba(212, 175, 55, 0.45) !important;
            color: #FFFFFF !important;
            border-radius: 10px;
        }
        div.stAlert *, div[data-testid="stInfo"] *, div[data-testid="stSuccess"] *, div[data-testid="stWarning"] * {
            color: #FFFFFF !important;
            font-weight: 500 !important;
        }
    </style>
''', unsafe_allow_html=True)

st.title("🚛 Smart Route Rebalancer Dashboard")
st.markdown("**ระบบวิเคราะห์และตัดสายส่งน้ำอัตโนมัติ (Audited Dropdown Legibility Architecture)**")

st.sidebar.markdown("### 📁 1. นำเข้าข้อมูล (Data Source)")
sheet_url = st.sidebar.text_input("🔗 ลิงก์ Google Sheets:", placeholder="วางลิงก์ที่นี่...", on_change=reset_results)
raw_gid_input = st.sidebar.text_input("แท็บชีต (GID):", value="0", on_change=reset_results)

gid_match = re.search(r'gid=([0-9]+)', raw_gid_input)
if gid_match:
    sheet_gid = gid_match.group(1)
else:
    digits_only = "".join(filter(str.isdigit, raw_gid_input))
    sheet_gid = digits_only if digits_only else "0"

@st.cache_data(ttl=300)
def load_data_from_sheet(url, gid):
    try:
        match = re.search(r'/d/([a-zA-Z0-9-_]+)', url)
        if not match: return None, "ลิงก์ Google Sheets ไม่ถูกต้อง"
        sheet_id = match.group(1)
        export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"
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
            loader_html = f'''<div class="custom-truck-loader"><img
