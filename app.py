st.markdown("---")
        st.markdown("<div style='text-align:center; margin-bottom: 10px;'><b>📌 เมื่อจัดสายส่งเป็นที่น่าพอใจแล้ว สามารถดาวน์โหลดข้อมูลเพื่อนำไปใช้อัปเดตได้เลย</b></div>", unsafe_allow_html=True)
        
        # 📌 บังคับเข้ารหัสเป็น Bytes แบบ utf-8-sig ทันที เพื่อป้องกัน Streamlit ตัดข้อมูลภาษาไทยทิ้ง
        @st.cache_data
        def convert_df(df):
            return df.to_csv(index=False).encode('utf-8-sig')

        csv_bytes = convert_df(detail_df)
        
        # จัดตำแหน่งปุ่มดาวน์โหลดให้อยู่ตรงกลาง
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
