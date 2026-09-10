import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- CONFIG ---
st.set_page_config(page_title="Smart Route Rebalancer", layout="wide")
st.title("🚛 Smart Route Rebalancer v3.0 (Official)")

# --- FUNCTION: LOAD DATA VIA API ---
def load_data_from_sheet(sheet_url):
    # หมายเหตุ: วิธีนี้ใช้ไฟล์ credentials.json ของ Google Cloud
    # หากคุณไม่มี สามารถใช้การแก้ URL ให้เป็นรูปแบบ CSV ที่ถูกต้องได้ดังนี้:
    url = sheet_url.split('/edit')[0] + '/export?format=csv'
    return pd.read_csv(url)

# --- UI & LOGIC ---
sheet_url = st.sidebar.text_input("🔗 ลิงก์ Google Sheets")

if sheet_url:
    try:
        # ใช้การดึงผ่าน format=csv ที่ถูกต้อง
        df = load_data_from_sheet(sheet_url)
        
        # ตรวจสอบว่าสิ่งที่ดึงมาเป็นตารางหรือไม่
        if df.columns.size > 1 and "DOCTYPE" not in str(df.columns[0]):
            st.success("✅ โหลดข้อมูลจาก Google Sheets สำเร็จ")
            
            cols = df.columns.tolist()
            col1, col2 = st.columns(2)
            v_col = col1.selectbox("เลือกคอลัมน์ยอด", cols)
            t_col = col2.selectbox("เลือกคอลัมน์รถ", cols)
            lat_col = col1.selectbox("เลือกคอลัมน์ละติจูด", cols)
            lon_col = col2.selectbox("เลือกคอลัมน์ลองจิจูด", cols)
            
            if st.button("🚀 ประมวลผลและกระจายงาน"):
                # ใส่ Logic การกระจายงานที่นี่
                st.write("### ผลลัพธ์การประมวลผล")
                st.dataframe(df.head(10), use_container_width=True)
                
        else:
            st.error("❌ ดึงข้อมูลไม่สำเร็จ: ลิงก์อาจไม่ถูกต้องหรือไฟล์ไม่เป็นสาธารณะ")
            
    except Exception as e:
        st.error(f"❌ เกิดข้อผิดพลาด: {e}")
else:
    st.info("กรุณาระบุลิงก์ Google Sheets ที่แชร์เป็นสาธารณะ (Anyone with the link can view)")
