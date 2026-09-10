# ---------------------------------------------------------------- TAB 5: DETAIL
with tab_detail:
    section("📋 รายละเอียดการโยกย้ายสมาชิก", "พร้อมดาวน์โหลดไปใช้งานจริง")

    detail = rdf.copy()
    detail['เบอร์รถเดิม'] = detail[truck_col]
    detail['วันจัดส่ง(เดิม)'] = detail[day_col]

    want = [id_col]
    if name_col:
        want.append(name_col)
    want += ['วันจัดส่ง(เดิม)', 'วันจัดส่ง(ใหม่)', 'สถานะการย้ายวัน', vol_col,
             'เบอร์รถเดิม', 'เบอร์รถใหม่', 'สถานะ']
    want = list(dict.fromkeys([c for c in want if c in detail.columns]))
    detail = detail[want]

    f1, f2, f3 = st.columns([1, 1, 2])
    only_moved = f1.checkbox("เฉพาะรายที่ย้ายสาย", False)
    only_daymoved = f2.checkbox("เฉพาะรายที่ย้ายวัน", False)
    tl2 = [t for t in sorted(rdf['เบอร์รถใหม่'].dropna().unique()) if t != OVERFLOW_LABEL]
    tf = f3.multiselect("กรองตามเบอร์รถใหม่", tl2, [])

    vd = detail
    if only_moved:
        vd = vd[vd['สถานะ'].astype(str).str.startswith('ย้าย')]
    if only_daymoved and 'สถานะการย้ายวัน' in vd.columns:
        vd = vd[vd['สถานะการย้ายวัน'].astype(str) != '-']
    if tf:
        vd = vd[vd['เบอร์รถใหม่'].isin(tf)]

    st.caption(f"แสดง {len(vd):,} จาก {len(detail):,} รายการ")
    st.dataframe(vd, use_container_width=True, hide_index=True, height=520)

    st.markdown("---")

    @st.cache_data
    def to_csv(d: pd.DataFrame) -> bytes:
        return d.to_csv(index=False).encode('utf-8-sig')

    b1, b2, b3 = st.columns([1, 2, 1])
    with b2:
        st.download_button(
            "📥 ดาวน์โหลดผลลัพธ์ทั้งหมด (CSV เปิดใน Excel ได้ทันที)",
            to_csv(detail),
            'route_rebalance_result.csv',
            'text/csv',
            use_container_width=True,
        )
