from __future__ import annotations
import streamlit as st, pandas as pd

# --- UI & LOGIC ---
def main():
    st.set_page_config(page_title="Smart Route Rebalancer", layout="wide")
    st.title("🚛 Smart Route Rebalancer v3.0 (Official)")
    
    sheet_url = st.sidebar.text_input("🔗 ใส่ลิงก์ CSV (จาก Publish to web เท่านั้น)")
    
    if sheet_url:
        try:
            # ตรวจสอบเบื้องต้นว่าเป็นลิงก์ที่ถูกต้องหรือไม่
            df = pd.read_csv(sheet_url)
            st.success("✅ โหลดข้อมูลสำเร็จ")
            
            cols = df.columns.tolist()
            # ถ้าโหลด HTML มา ตัวแปร cols จะยาวผิดปกติ ให้เช็คที่นี่
            if len(cols) < 2 or "<!DOCTYPE" in str(cols[0]):
                st.error("❌ ลิงก์ที่ใส่ไม่ใช่ไฟล์ CSV กรุณาใช้ลิงก์จาก 'Publish to web' เท่านั้น")
                return

            col1, col2 = st.columns(2)
            v_col = col1.selectbox("เลือกคอลัมน์ยอด", cols)
            t_col = col2.selectbox("เลือกคอลัมน์รถ", cols)
            lat_col = col1.selectbox("เลือกคอลัมน์ละติจูด", cols)
            lon_col = col2.selectbox("เลือกคอลัมน์ลองจิจูด", cols)
            
            if st.button("🚀 ประมวลผล"):
                st.write("ประมวลผลเสร็จสิ้น (ตัวอย่างข้อมูล):")
                st.dataframe(df[[v_col, t_col]].head())
                
        except Exception as e:
            st.error(f"เกิดข้อผิดพลาด: {e}")

if __name__ == "__main__":
    main()
