import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta, timezone

# =================================================================
# VERSI: 1.8 - FINAL STABLE BASELINE (ENTER-KEY REPAIRED)
# FIX: Sinkronisasi nilai widget saat ditekan ENTER di dalam Form
# =================================================================

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sistem Kasir Pro v1.8 - Stable", layout="wide")

# --- 2. KONEKSI DATABASE ---
@st.cache_resource
def get_connection():
    try:
        if "MOTHERDUCK_TOKEN" not in st.secrets:
            st.error("Missing MOTHERDUCK_TOKEN in secrets!")
            st.stop()
        TOKEN = st.secrets["MOTHERDUCK_TOKEN"]
        return duckdb.connect(f"md:tes_db?motherduck_token={TOKEN}")
    except Exception as e:
        st.error(f"Gagal koneksi ke MotherDuck: {e}")
        st.stop()

con = get_connection()

# --- 3. LOGIKA HELPER ---
WIB = timezone(timedelta(hours=7))

def get_now_wib():
    return datetime.now(timezone.utc).astimezone(WIB)

# --- 4. UI COMPONENTS ---

def login_ui():
    st.title("🔐 Login Sistem Kasir")
    with st.form("login_form"):
        user = st.text_input("Username")
        pw = st.text_input("Password", type="password")
        if st.form_submit_button("Login"):
            res = con.execute("SELECT role FROM users WHERE username = ? AND password = ?", [user, pw]).fetchone()
            if res:
                st.session_state.logged_in = True
                st.session_state.username = user
                st.session_state.role = res[0]
                st.rerun()
            else: 
                st.error("Username atau Password salah!")

def cashier_ui():
    st.header(f"🛒 Kasir: {st.session_state.username}")
    if "cart" not in st.session_state: st.session_state.cart = []

    try:
        df_produk = con.execute("SELECT id, nama_produk, kategori, harga, stok FROM produk").df()
    except:
        st.warning("Tabel produk belum siap."); return

    col_input, col_cart = st.columns([1, 2])

    with col_input:
        st.subheader("Input Pesanan")
        list_kat = ["Semua"] + sorted(list(df_produk['kategori'].unique())) if not df_produk.empty else ["Semua"]
        f_kat = st.selectbox("Filter Kategori", list_kat)
        df_filtered = df_produk if f_kat == "Semua" else df_produk[df_produk['kategori'] == f_kat]

        with st.form("form_cart"):
            if not df_filtered.empty:
                item_p_name = st.selectbox("Pilih Produk", sorted(df_filtered['nama_produk'].unique()))
                selected_item_data = df_filtered[df_filtered['nama_produk'] == item_p_name].iloc[0]
                p_category = selected_item_data['kategori']
                p_id = selected_item_data['id']
                p_harga_base = float(selected_item_data['harga'])
                p_stok_prod = selected_item_data['stok']
                
                df_addons = con.execute("SELECT nama_label, harga, stok FROM master_label WHERE kategori = ?", [p_category]).df()
                addon_options = []
                addon_data_map = {}
                if not df_addons.empty:
                    for _, row in df_addons.iterrows():
                        label_display = f"{row['nama_label']} (+Rp{row['harga']:,.0f}) [Sisa: {row['stok']}]"
                        addon_options.append(label_display)
                        addon_data_map[label_display] = {"nama": row['nama_label'], "harga": float(row['harga']), "stok": int(row['stok'])}
                
                selected_addons_display = st.multiselect(f"Pilih Add On ({p_category}):", addon_options)
                qty_p_in = st.number_input("Jumlah", min_value=1, step=1, key="cashier_qty_input")

                if st.form_submit_button("➕ Tambah"):
                    # Ambil nilai dari session state agar Enter Key aman
                    qty_val = st.session_state.cashier_qty_input
                    if p_stok_prod < qty_val:
                        st.error(f"Stok Produk '{item_p_name}' sisa {p_stok_prod}!"); return
                    
                    total_addon_price = 0
                    clean_addons_list = []
                    for ad_disp in selected_addons_display:
                        ad_info = addon_data_map[ad_disp]
                        if ad_info['stok'] < qty_val:
                            st.error(f"Stok Add On '{ad_info['nama']}' tidak cukup!"); return
                        total_addon_price += ad_info['harga']
                        clean_addons_list.append(ad_info['nama'])

                    st.session_state.cart.append({
                        "id": int(p_id), "nama": item_p_name, "qty": int(qty_val),
                        "harga_satuan": p_harga_base + total_addon_price, 
                        "subtotal": (p_harga_base + total_addon_price) * qty_val,
                        "opsi_list": clean_addons_list, "opsi_txt": ", ".join(clean_addons_list)
                    })
                    st.rerun()

    with col_cart:
        if st.session_state.cart:
            st.subheader("🛒 Keranjang")
            total = sum(i['subtotal'] for i in st.session_state.cart)
            st.table(pd.DataFrame(st.session_state.cart)[['nama', 'opsi_txt', 'qty', 'subtotal']])
            st.write(f"### TOTAL BAYAR: Rp{total:,.0f}")
            if st.button("✅ SELESAIKAN", type="primary", use_container_width=True):
                id_tx = get_now_wib().strftime("%Y%m%d%H%M%S")
                for b in st.session_state.cart:
                    con.execute("UPDATE produk SET stok = stok - ? WHERE id = ?", [int(b['qty']), int(b['id'])])
                    for addon_name in b['opsi_list']:
                        con.execute("UPDATE master_label SET stok = stok - ? WHERE nama_label = ?", [int(b['qty']), addon_name])
                    con.execute("""
                        INSERT INTO transaksi (id_transaksi, nama_produk, qty, total_harga, kasir, waktu, opsi_detail) 
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, [id_tx, b['nama'], int(b['qty']), float(b['subtotal']), st.session_state.username, get_now_wib().replace(tzinfo=None), b['opsi_txt']])
                st.session_state.cart = []
                st.rerun()

def admin_ui():
    st.title("🏗️ Panel Admin v1.8")
    menu = st.sidebar.selectbox("Menu", ["Dashboard", "Produk", "Add On", "Transaksi"])
    list_kategori = ["Minuman", "Makanan", "Fashion"]

    # --- 1. MENU PRODUK ---
    if menu == "Produk":
        st.subheader("📦 Manajemen Produk")
        df_p = con.execute("SELECT id, nama_produk, kategori, harga, stok FROM produk ORDER BY id DESC").df()
        st.dataframe(df_p, use_container_width=True, hide_index=True)

        t1, t2, t3, t4 = st.tabs(["➕ Tambah", "✏️ Edit", "📦 Stok", "🗑️ Hapus"])
        
        # --- TAB 1: TAMBAH ---
        with t1:
            with st.form("f_add_p"):
                st.text_input("Nama Produk", key="p_name_k")
                st.selectbox("Kategori", list_kategori, key="p_kat_k")
                st.number_input("Harga", min_value=0, step=500, key="p_harga_k")
                st.number_input("Stok Awal", min_value=0, step=1, key="p_stok_k")
                
                if st.form_submit_button("Simpan Produk"):
                    v_n, v_k, v_h, v_s = st.session_state.p_name_k, st.session_state.p_kat_k, st.session_state.p_harga_k, st.session_state.p_stok_k
                    if not v_n.strip(): st.error("Nama tidak boleh kosong!"); return
                    is_dup = con.execute("SELECT COUNT(*) FROM produk WHERE LOWER(TRIM(nama_produk)) = LOWER(?)", [v_n.strip()]).fetchone()[0]
                    if is_dup > 0: st.error(f"Gagal! Produk '{v_n.strip()}' sudah ada."); return
                    
                    nid = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM produk").fetchone()[0]
                    con.execute("INSERT INTO produk (id, nama_produk, kategori, harga, stok) VALUES (?,?,?,?,?)", [int(nid), v_n.strip(), v_k, float(v_h), int(v_s)])
                    st.success(f"Berhasil simpan {v_n}!"); st.rerun()

        # --- TAB 2: EDIT (IMPLEMENTASI BARU) ---
        with t2:
            if not df_p.empty:
                p_edit_id = st.selectbox("Pilih Produk yang akan di-Edit", df_p['id'].tolist(), 
                                        format_func=lambda x: f"{df_p[df_p['id']==x]['nama_produk'].values[0]}",
                                        key="p_edit_sel_id")
                
                # Ambil data lama untuk default value
                old_data = df_p[df_p['id'] == p_edit_id].iloc[0]
                
                with st.form("f_edit_p_form"):
                    e_nama = st.text_input("Nama Produk", value=old_data['nama_produk'])
                    e_kat = st.selectbox("Kategori", list_kategori, index=list_kategori.index(old_data['kategori']))
                    e_harga = st.number_input("Harga", min_value=0, value=float(old_data['harga']), step=500)
                    
                    if st.form_submit_button("Update Data Produk"):
                        con.execute("""
                            UPDATE produk SET nama_produk = ?, kategori = ?, harga = ? WHERE id = ?
                        """, [e_nama.strip(), e_kat, float(e_harga), int(p_edit_id)])
                        st.success("Produk berhasil diperbarui!"); st.rerun()
            else:
                st.info("Belum ada produk untuk diedit.")

        # --- TAB 3: STOK ---
        with t3:
            if not df_p.empty:
                p_stok_id = st.selectbox("Pilih Produk (Update Stok)", df_p['id'].tolist(), 
                                        format_func=lambda x: f"{df_p[df_p['id']==x]['nama_produk'].values[0]}", 
                                        key="p_stok_sel_id")
                curr_s = df_p[df_p['id'] == p_stok_id]['stok'].values[0]
                with st.form("f_upd_stok_p"):
                    st.number_input("Set Stok Baru", min_value=0, value=int(curr_s), step=1, key="p_stok_upd_k")
                    if st.form_submit_button("Update Stok"):
                        con.execute("UPDATE produk SET stok=? WHERE id=?", [int(st.session_state.p_stok_upd_k), int(p_stok_id)])
                        st.success("Stok diperbarui!"); st.rerun()

        # --- TAB 4: HAPUS ---
        with t4:
            if not df_p.empty:
                p_del_id = st.selectbox("Pilih Produk yang akan Dihapus", df_p['id'].tolist(), 
                                        format_func=lambda x: f"{df_p[df_p['id']==x]['nama_produk'].values[0]}",
                                        key="p_del_sel_id")
                if st.button("🔥 Hapus Produk Permanen", key="btn_del_p"):
                    con.execute("DELETE FROM produk WHERE id=?", [int(p_del_id)])
                    st.success("Produk berhasil dihapus!"); st.rerun()
            else:
                st.info("Belum ada produk untuk dihapus.")

    # --- 2. MENU ADD ON ---
    elif menu == "Add On":
        st.subheader("🧩 Manajemen Add On")
        df_l = con.execute("SELECT id, nama_label, kategori, harga, stok FROM master_label ORDER BY kategori, nama_label").df()
        st.dataframe(df_l, use_container_width=True, hide_index=True)

        t_l1, t_l2, t_l3, t_l4 = st.tabs(["➕ Tambah", "✏️ Edit", "📦 Stok", "🗑️ Hapus"])
        
        with t_l1:
            with st.form("form_add_addon_final"):
                st.text_input("Nama Add On", key="a_name_k")
                st.selectbox("Kategori", list_kategori, key="a_kat_k")
                st.number_input("Harga Tambahan", min_value=0, step=500, key="a_harga_k")
                st.number_input("Stok Awal", min_value=0, step=1, key="a_stok_k")
                
                if st.form_submit_button("Simpan Add On"):
                    val_an = st.session_state.a_name_k
                    val_ak = st.session_state.a_kat_k
                    val_ah = st.session_state.a_harga_k
                    val_as = st.session_state.a_stok_k

                    if not val_an.strip(): st.error("Nama tidak boleh kosong!"); return
                    is_dup_a = con.execute("SELECT COUNT(*) FROM master_label WHERE LOWER(TRIM(nama_label)) = LOWER(?)", [val_an.strip()]).fetchone()[0]
                    if is_dup_a > 0:
                        st.error(f"Gagal! Add On '{val_an.strip()}' sudah ada."); return
                    
                    new_id_a = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM master_label").fetchone()[0]
                    con.execute("INSERT INTO master_label (id, nama_label, kategori, harga, stok) VALUES (?,?,?,?,?)", 
                                [int(new_id_a), val_an.strip(), val_ak, float(val_ah), int(val_as)])
                    st.success(f"Berhasil! Add On {val_an} dengan stok {int(val_as)} tersimpan."); st.rerun()

        with t_l3:
            if not df_l.empty:
                a_stok_id = st.selectbox("Pilih Add On (Stok)", df_l['id'].tolist(), format_func=lambda x: f"{df_l[df_l['id']==x]['nama_label'].values[0]}")
                curr_sl = df_l[df_l['id'] == a_stok_id]['stok'].values[0]
                with st.form("f_upd_stok_a"):
                    st.number_input("Set Stok Baru", min_value=0, value=int(curr_sl), step=1, key="a_stok_new_k")
                    if st.form_submit_button("Update Stok"):
                        val_new_as = st.session_state.a_stok_new_k
                        con.execute("UPDATE master_label SET stok=? WHERE id=?", [int(val_new_as), int(a_stok_id)])
                        st.success("Stok diperbarui!"); st.rerun()

    elif menu == "Dashboard":
        # 1. Hitung Omset Hari Ini
        now = get_now_wib()
        tgl_hari_ini = now.strftime('%Y-%m-%d')
        res_h = con.execute("SELECT SUM(total_harga) FROM transaksi WHERE CAST(waktu AS DATE) = ?", [tgl_hari_ini]).fetchone()
        omset_hari = res_h[0] if res_h[0] else 0

        # 2. Hitung Omset Bulan Ini
        bln_ini = now.strftime('%Y-%m')
        res_m = con.execute("SELECT SUM(total_harga) FROM transaksi WHERE STRFTIME('%Y-%m', waktu) = ?", [bln_ini]).fetchone()
        omset_bulan = res_m[0] if res_m[0] else 0

        # Tampilkan Metrik
        col_m1, col_m2 = st.columns(2)
        col_m1.metric("Omset Hari Ini", f"Rp{omset_hari:,.0f}")
        col_m2.metric("Omset Bulan Ini", f"Rp{omset_bulan:,.0f}")

        # 3. Grafik Penjualan dengan Legenda
        df_tx = con.execute("SELECT * FROM transaksi").df()
        if not df_tx.empty:
            df_tx['waktu'] = pd.to_datetime(df_tx['waktu'])
            
            # Cek kolom yang tersedia di dataframe vs yang diminta Plotly
            cols_needed = ['waktu', 'total_harga', 'nama_produk', 'opsi_detail', 'qty']
            cols_available = df_tx.columns.tolist()
            
            # Filter hanya kolom yang benar-benar ada agar tidak Error
            hover_cols = [c for c in ['opsi_detail', 'qty'] if c in cols_available]
            
            fig = px.bar(
                df_tx,
                x='waktu' if 'waktu' in cols_available else df_tx.columns[0],
                y='total_harga' if 'total_harga' in cols_available else df_tx.columns[1],
                color='nama_produk' if 'nama_produk' in cols_available else None,
                hover_data=hover_cols,
                title="Laporan Penjualan",
                labels={'total_harga': 'Total (Rp)', 'waktu': 'Tanggal'},
                template="plotly_white"
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Belum ada data transaksi.")

    elif menu == "Transaksi":
        df_tx = con.execute("SELECT * FROM transaksi ORDER BY waktu DESC").df()
        st.dataframe(df_tx, use_container_width=True)

# --- 5. LOGIKA UTAMA ---
if "logged_in" not in st.session_state:
    login_ui()
else:
    st.sidebar.write(f"User: **{st.session_state.username}**")
    if st.sidebar.button("Logout"):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()
    if st.session_state.role == "admin": admin_ui()
    else: cashier_ui()