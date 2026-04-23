import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px
from datetime import datetime

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sistem Kasir Pro v2.3", layout="wide")

# --- KONEKSI DATABASE ---
@st.cache_resource
def get_connection():
    TOKEN = st.secrets["MOTHERDUCK_TOKEN"]
    return duckdb.connect(f"md:tes_db?motherduck_token={TOKEN}")

con = get_connection()

# --- FUNGSI LOGIN ---
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

# --- HALAMAN KASIR ---
def cashier_ui():
    st.header(f"🛒 Kasir: {st.session_state.username}")
    if "cart" not in st.session_state: 
        st.session_state.cart = []

    df_produk = con.execute("SELECT * FROM produk").df()
    col_input, col_cart = st.columns([1, 2])

    with col_input:
        st.subheader("Pilih Barang")
        list_kategori = ["Semua"] + list(df_produk['kategori'].unique())
        filter_kat = st.selectbox("Filter Kategori", list_kategori)
        df_display = df_produk if filter_kat == "Semua" else df_produk[df_produk['kategori'] == filter_kat]

        with st.form("form_add_to_cart", clear_on_submit=True):
            if not df_display.empty:
                item_pilih = st.selectbox("Produk", df_display['nama_produk']) 
                qty_pilih = st.number_input("Jumlah", min_value=1, step=1)
                row_info = df_produk[df_produk['nama_produk'] == item_pilih].iloc[0]
                
                pilihan_opsi_str = ""
                if row_info['opsi'] and str(row_info['opsi']) != "None":
                    list_label = [o.strip() for o in str(row_info['opsi']).split(",")]
                    pilihan_user = st.multiselect("Opsi Tambahan:", list_label)
                    pilihan_opsi_str = ", ".join(pilihan_user)

                if st.form_submit_button("➕ Tambah"):
                    if int(row_info['stok']) >= qty_pilih:
                        st.session_state.cart.append({
                            "id_produk": int(row_info['id']),
                            "nama": item_pilih, 
                            "qty": int(qty_pilih),
                            "harga": float(row_info['harga']), 
                            "subtotal": float(row_info['harga'] * qty_pilih),
                            "opsi": pilihan_opsi_str
                        })
                        st.rerun()
                    else:
                        st.error("Stok Produk Habis!")
            else:
                st.warning("Produk tidak tersedia.")

    with col_cart:
        st.subheader("Isi Keranjang")
        if st.session_state.cart:
            total_bayar = sum(item['subtotal'] for item in st.session_state.cart)
            for i, b in enumerate(st.session_state.cart):
                c1, c2, c3 = st.columns([3, 2, 1])
                info_barang = f"**{b['nama']}**"
                if b['opsi']: 
                    info_barang += f"  \n*({b['opsi']})*"
                c1.write(f"{info_barang}  \n{b['qty']} x Rp{b['harga']:,.0f}")
                c2.write(f"Rp{b['subtotal']:,.0f}")
                if c3.button("🗑️", key=f"del_{i}"):
                    st.session_state.cart.pop(i)
                    st.rerun()
            
            st.divider()
            st.write(f"### TOTAL: Rp{total_bayar:,.0f}")
            if st.button("✅ PROSES TRANSAKSI", use_container_width=True):
                id_tx = datetime.now().strftime("%Y%m%d%H%M%S")
                waktu_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for b in st.session_state.cart:
                    con.execute("UPDATE produk SET stok = stok - ? WHERE id = ?", [b['qty'], b['id_produk']])
                    if b['opsi']:
                        list_pilihan = [p.strip() for p in b['opsi'].split(",")]
                        for p in list_pilihan:
                            con.execute("UPDATE label_stok SET stok = stok - ? WHERE nama_label = ?", [b['qty'], p])
                    con.execute("INSERT INTO transaksi VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                [id_tx, b['nama'], b['qty'], b['subtotal'], st.session_state.username, waktu_str, b['opsi']])
                st.success("Transaksi Berhasil!")
                st.session_state.cart = []
                st.rerun()
        else:
            st.info("Keranjang kosong.")

# --- HALAMAN ADMIN ---
def admin_ui():
    st.title("🏗️ Panel Admin")
    menu = st.sidebar.selectbox("Menu Admin", ["Dashboard", "Manajemen Produk", "Manajemen Label", "Data Transaksi"])
    
    if menu == "Dashboard":
        st.subheader("📊 Performa Penjualan")
        c1, c2 = st.columns(2)
        h = con.execute("SELECT SUM(total_harga) FROM transaksi WHERE CAST(waktu AS DATE) = CURRENT_DATE").fetchone()[0] or 0
        b = con.execute("SELECT SUM(total_harga) FROM transaksi WHERE date_trunc('month', CAST(waktu AS TIMESTAMP)) = date_trunc('month', CURRENT_DATE)").fetchone()[0] or 0
        c1.metric("Omset Hari Ini", f"Rp{h:,.0f}")
        c2.metric("Omset Bulan Ini", f"Rp{b:,.0f}")
        df_tx = con.execute("SELECT * FROM transaksi").df()
        if not df_tx.empty:
            st.plotly_chart(px.bar(df_tx, x='waktu', y='total_harga', color='nama_produk', title="Tren Penjualan"), use_container_width=True)

    elif menu == "Manajemen Produk":
        st.subheader("📦 Pengaturan Produk")
        df_p = con.execute("SELECT * FROM produk ORDER BY id ASC").df()
        st.dataframe(df_p, use_container_width=True, hide_index=True)
        col1, col2, col3 = st.columns(3)
        
        with col1:
            with st.expander("➕ Tambah"):
                with st.form("add_p", clear_on_submit=True):
                    n = st.text_input("Nama Produk").strip()
                    k = st.selectbox("Kategori", ["Makanan", "Minuman"])
                    o = st.text_input("Opsi (Pisah koma)")
                    h = st.number_input("Harga", step=500)
                    s = st.number_input("Stok", step=1)
                    if st.form_submit_button("Simpan"):
                        check = con.execute("SELECT nama_produk FROM produk WHERE LOWER(nama_produk) = LOWER(?)", [n]).fetchone()
                        if check:
                            st.error(f"❌ Produk '{n}' sudah terdaftar!")
                        elif n == "":
                            st.warning("Nama tidak boleh kosong")
                        else:
                            nid = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM produk").fetchone()[0]
                            con.execute("INSERT INTO produk VALUES (?,?,?,?,?,?)", [nid, n, k, h, s, o])
                            st.rerun()
                            
        with col2:
            with st.expander("📝 Update"):
                if not df_p.empty:
                    with st.form("edit_p"):
                        sel = st.selectbox("Pilih Produk", df_p['nama_produk'])
                        r = df_p[df_p['nama_produk'] == sel].iloc[0]
                        nh = st.number_input("Harga Baru", value=int(r['harga']))
                        ns = st.number_input("Tambah Stok", value=0)
                        no = st.text_input("Update Opsi", value=str(r['opsi']))
                        if st.form_submit_button("Update"):
                            con.execute("UPDATE produk SET harga=?, stok=stok+?, opsi=? WHERE id=?", [nh, ns, no, int(r['id'])])
                            st.rerun()
                            
        with col3:
            with st.expander("🗑️ Hapus"):
                if not df_p.empty:
                    sel_del = st.selectbox("Pilih Produk", df_p['nama_produk'], key="del_p")
                    if st.button("Hapus Permanen", type="primary"):
                        con.execute("DELETE FROM produk WHERE nama_produk=?", [sel_del])
                        st.rerun()

    elif menu == "Manajemen Label":
        st.subheader("🧪 Pengaturan Label (Bahan Baku)")
        df_l = con.execute("SELECT * FROM label_stok").df()
        st.dataframe(df_l, use_container_width=True, hide_index=True)
        c1, c2, c3 = st.columns(3)
        
        with c1:
            with st.expander("➕ Tambah Label Baru"):
                with st.form("add_l", clear_on_submit=True):
                    nl = st.text_input("Nama Label").strip()
                    sl = st.number_input("Stok Awal", min_value=0)
                    sat = st.text_input("Satuan", value="pcs")
                    if st.form_submit_button("Simpan Label"):
                        check_l = con.execute("SELECT nama_label FROM label_stok WHERE LOWER(nama_label) = LOWER(?)", [nl]).fetchone()
                        if check_l:
                            st.error(f"❌ Label '{nl}' sudah ada!")
                        elif nl == "":
                            st.warning("Nama tidak boleh kosong")
                        else:
                            lid = con.execute("SELECT COALESCE(MAX(id_label),0)+1 FROM label_stok").fetchone()[0]
                            con.execute("INSERT INTO label_stok VALUES (?,?,?,?)", [lid, nl, sl, sat])
                            st.rerun()
                            
        with c2:
            with st.expander("🔄 Update Label"):
                if not df_l.empty:
                    with st.form("update_l"):
                        sel_l = st.selectbox("Pilih Label", df_l['nama_label'])
                        rl = df_l[df_l['nama_label'] == sel_l].iloc[0]
                        nnl = st.text_input("Ubah Nama", value=rl['nama_label'])
                        asl = st.number_input("Tambah Stok", value=0)
                        nsat = st.text_input("Ubah Satuan", value=rl['satuan'])
                        if st.form_submit_button("Simpan Perubahan"):
                            con.execute("UPDATE label_stok SET nama_label=?, stok=stok+?, satuan=? WHERE id_label=?", 
                                        [nnl, asl, nsat, int(rl['id_label'])])
                            st.rerun()
                            
        with c3:
            with st.expander("🗑️ Hapus Label"):
                if not df_l.empty:
                    sel_ldel = st.selectbox("Pilih Label", df_l['nama_label'], key="del_l")
                    if st.button("Hapus Permanen", type="primary", key="btn_del_l"):
                        con.execute("DELETE FROM label_stok WHERE nama_label=?", [sel_ldel])
                        st.rerun()

    elif menu == "Data Transaksi":
        st.subheader("📝 Histori")
        st.dataframe(con.execute("SELECT * FROM transaksi ORDER BY waktu DESC").df(), use_container_width=True)

# --- LOGIKA UTAMA ---
if "logged_in" not in st.session_state:
    login_ui()
else:
    st.sidebar.write(f"Logged in as: **{st.session_state.username}**")
    if st.sidebar.button("Logout"):
        for k in list(st.session_state.keys()): 
            del st.session_state[k]
        st.rerun()
    if st.session_state.role == "admin": 
        admin_ui()
    else: 
        cashier_ui()