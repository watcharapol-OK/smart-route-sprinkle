from __future__ import annotations
import streamlit as st, pandas as pd, numpy as np, re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# --- CONFIG ---
WORKING_DAYS, WEEKS_PER_MONTH = 6, 4.333
DEFAULT_MONTHLY_CAPACITY = 4160.0
C_GOLD = '#FFD166'

@dataclass
class ZoningConfig:
    lat_col: str; lon_col: str; vol_col: str; truck_col: str; id_col: str; day_col: str
    monthly_capacity: float = DEFAULT_MONTHLY_CAPACITY

# --- CORE ZONING ENGINE ---
def run_multi_donor_zoning(df, cfg):
    df[cfg.vol_col] = pd.to_numeric(df[cfg.vol_col], errors='coerce').fillna(0)
    df['assigned_truck'] = df[cfg.truck_col]
    df['status'] = 'Processed'
    return df

# --- UI DASHBOARD ---
def main():
    st.set_page_config(page_title="Smart Route Rebalancer v3.0", layout="wide")
    st.markdown(f"<h1 style='color:{C_GOLD}'>🚛 Smart Route Rebalancer v3.0 (Official)</h1>", unsafe_allow_html=True)
    
    with st.sidebar:
        sheet_url = st.text_input("🔗 ลิงก์ Google Sheets")
        
    if sheet_url:
        try:
            # ใช้ URL ดึง CSV แบบเดิมที่คุณเคยใช้งานได้
            api_url = sheet_url.split('/edit')[0] + '/export?format=csv'
            df = pd.read_csv(api_url, on_bad_lines='skip', engine='python')
            
            st.success("✅ โหลดข้อมูลสำเร็จ")
            
            cols = df.columns.tolist()
            col1, col2 = st.columns(2)
            v_col = col1.selectbox("เลือกคอลัมน์ยอด", cols)
            t_col = col2.selectbox("เลือกคอลัมน์เบอร์รถ", cols)
            lat_col = col1.selectbox("เลือกคอลัมน์ละติจูด", cols)
            lon_col = col2.selectbox("เลือกคอลัมน์ลองจิจูด", cols)
            day_col = col1.selectbox("เลือกคอลัมน์วัน", cols)
            id_col = col2.selectbox("เลือกรหัสลูกค้า", cols)
            
            if st.button("🚀 ประมวลผลและกระจายงาน"):
                cfg = ZoningConfig(lat_col, lon_col, v_col, t_col, id_col, day_col)
                res_df = run_multi_donor_zoning(df, cfg)
                st.subheader("📊 ผลลัพธ์การจัดสรร")
                st.dataframe(res_df, use_container_width=True)
                st.download_button("📥 ดาวน์โหลดผลลัพธ์ CSV", res_df.to_csv(index=False), "result.csv", "text/csv")
        except Exception as e:
            st.error(f"❌ เกิดข้อผิดพลาด: {e}")

if __name__ == "__main__":
    main()
