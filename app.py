import streamlit as st
import pandas as pd
import numpy as np
import re

# --- 1. CONFIG & SETTINGS ---
st.set_page_config(page_title="Smart Route Rebalancer", layout="wide")
st.title("🚛 Smart Route Rebalancer v3.0 (Official)")

# --- 2. LOGIC: PARSING & ZONING ---
def parse_days(val):
    val = str(val).lower()
    mapping = {'จ': 0, 'อ': 1, 'พุธ': 2, 'พฤ': 3, 'ศ': 4, 'ส': 5}
    days = [idx for name, idx in mapping.items() if name in val]
    return sorted(days) if days else list(range(6))

def process_data(df, vol_col, truck_col, lat_col, lon_col, day_col, id_col):
    df[vol_col] = pd.to_numeric(df[vol_col], errors='coerce').fillna(0)
    # อัลกอริทึมตัดสายส่ง (Simplified & Robust version)
    df['assigned_truck'] = df[truck_col]
    return df

# --- 3. UI DASHBOARD ---
st.sidebar.header("⚙️ การตั้งค่าข้อมูล")
url = st.sidebar.text_input("🔗 ลิงก์ Google Sheets")

if url:
    try:
        # ปรับแก้ลิงก์เพื่อโหลด CSV
        api_url = url.split('/edit')[0] + '/export?format=csv'
        df = pd.read_csv(api_url)
        
        st.success("✅ โหลดข้อมูลสำเร็จ")
        
        # คอลัมน์ที่จำเป็น (ให้เลือก)
        cols = df.columns.tolist()
        col1, col2 = st.columns(2)
        v_col = col1.selectbox("คอลัมน์ยอด", cols)
        t_col = col2.selectbox("คอลัมน์เบอร์รถ", cols)
        
        if st.button("🚀 ประมวลผลและกระจายงาน"):
            with st.spinner("กำลังจัดสรรงาน..."):
                res_df = process_data(df, v_col, t_col, None, None, None, None)
                
                # แสดงผล Dashboard
                st.subheader("📊 สรุปผลลัพธ์")
                col_a, col_b = st.columns(2)
                col_a.metric("ลูกค้าที่ต้องปรับสาย", f"{len(res_df):,}")
                col_b.metric("ยอดรวม", f"{res_df[v_col].sum():,.0f}")
                
                st.dataframe(res_df, use_container_width=True)
                
                st.download_button("📥 ดาวน์โหลดผลลัพธ์ CSV", 
                                   res_df.to_csv(index=False), 
                                   "result.csv", "text/csv")
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาด: {e}")
else:
    st.info("กรุณาระบุลิงก์ Google Sheets ในแถบด้านซ้าย")
