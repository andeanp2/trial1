import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px
from datetime import datetime

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sistem Kasir Pro v1", layout="wide")

# --- KONEKSI DATABASE ---
@st.cache_resource
def get_connection():
    TOKEN = st.secrets["MOTHERDUCK_TOKEN"]
    return duckdb.connect(f"md:my_db?motherduck_token={TOKEN}")

con = get_connection()

# --- FUNGSI LOGIN ---
def login_ui():
    st.title("🔐 Login Sistem Kasir")
    with st.form("login_form"):
        user = st.text_input("Username")
        pw = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")
        
        if submit:
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
            item_pilih = st.selectbox("Produk", df_display['nama_produk']) 
            qty_pilih = st.number_input("Jumlah", min_value=1, step=1)
            btn_add = st.form_submit_button("➕ Tambah ke Keranjang")

            if btn_add:
                row = df_produk[df_produk['nama_produk'] == item_pilih].iloc[0]
                if int(row['stok']) >= qty_pilih:
                    st.session_state.cart.append({
                        "nama": item_pilih, 
                        "qty": int(qty_pilih),
                        "harga": float(row['harga']), 
                        "subtotal": float(row['harga'] * qty_pilih)
                    })
                    st.toast(f"{item_pilih} ditambah!")
                    st.rerun()
                else:
                    st.error("Stok habis!")

    with col_cart:
        st.subheader("Isi Keranjang")
        if st.session_state.cart:
            total_bayar = 0
            for i, barang in enumerate(st.session_state.cart):
                c1, c2, c3 = st.columns([3, 2, 1])
                c1.write(f"**{barang['nama']}** \n{barang['qty']} x Rp{barang['harga']:,.0f}")
                c2.write(f" \nRp{barang['subtotal']:,.0f}")
                if c3.button("🗑️", key=f"del_{i}"):
                    st.session_state.cart.pop(i)
                    st.rerun()
                total_bayar += barang['subtotal']
            
            st.divider()
            st.write(f"### TOTAL: Rp{total_bayar:,.0f}")
            
            c1, c2 = st.columns(2)
            if c1.button("🧹 Kosongkan"):
                st.session_state.cart = []
                st.rerun()

            if c2.button("✅ PROSES TRANSAKSI"):
                id_tx = datetime.now().strftime("%Y%m%d%H%M%S")
                waktu_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for b in st.session_state.cart:
                    con.execute("UPDATE produk SET stok = stok - ? WHERE nama_produk = ?", [b['qty'], b['nama']])
                    con.execute("""
                        INSERT INTO transaksi (id_transaksi, nama_produk, jumlah, total_harga, kasir, waktu) 
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, [id_tx, b['nama'], b['qty'], b['subtotal'], str(st.session_state.username), waktu_str])
                
                st.success("Transaksi Berhasil!")
                st.session_state.cart = []
                st.rerun()
        else:
            st.info("Keranjang kosong.")

# --- HALAMAN ADMIN ---
def admin_ui():
    st.title("🏗️ Panel Admin")
    menu_admin = st.sidebar.selectbox("Menu Admin", ["Dashboard Utama", "Manajemen Stok", "Data Transaksi"])
    
    if menu_admin == "Dashboard Utama":
        st.subheader("📊 Performa Penjualan")
        col1, col2 = st.columns(2)
        
        # 1. Omset Hari Ini
        omset_hari_ini = con.execute("""
            SELECT SUM(total_harga) 
            FROM transaksi 
            WHERE CAST(waktu AS DATE) = CURRENT_DATE
        """).fetchone()[0] or 0

        # 2. Omset Bulan Ini (Filter berdasarkan bulan dan tahun sekarang)
        omset_bulan_ini = con.execute("""
            SELECT SUM(total_harga) 
            FROM transaksi 
            WHERE date_trunc('month', CAST(waktu AS TIMESTAMP)) = date_trunc('month', CURRENT_DATE)
        """).fetchone()[0] or 0
        
        col1.metric("Omset Hari Ini", f"Rp{omset_hari_ini:,.0f}")
        col2.metric("Omset Bulan Ini", f"Rp{omset_bulan_ini:,.0f}")
        
        # Grafik Penjualan
        df_tx = con.execute("SELECT * FROM transaksi").df()
        if not df_tx.empty:
            fig = px.bar(df_tx, x='waktu', y='total_harga', title="Tren Penjualan Barang", color='nama_produk')
            st.plotly_chart(fig, use_container_width=True)

    elif menu_admin == "Manajemen Stok":
        st.subheader("📦 Manajemen Gudang & Stok")
        df_produk = con.execute("SELECT id, nama_produk, kategori, harga, stok FROM produk ORDER BY id ASC").df()
        st.dataframe(df_produk, use_container_width=True, hide_index=True)
        
        col_tambah, col_edit, col_hapus = st.columns(3)
        
        with col_tambah:
            with st.expander("➕ Tambah Barang Baru"):
                with st.form("form_tambah_barang", clear_on_submit=True):
                    nama_baru = st.text_input("Nama Produk Baru").strip()
                    kat_pilihan = st.selectbox("Kategori", ["Makanan", "Minuman", "Fashion"])
                    harga_baru = st.number_input("Harga Jual (Rp)", min_value=0, step=500)
                    stok_awal = st.number_input("Stok Awal", min_value=0, step=1)
                    btn_tambah = st.form_submit_button("Simpan Barang")
                
                    if btn_tambah and nama_baru:
                        produk_eksis = con.execute("SELECT nama_produk FROM produk WHERE LOWER(nama_produk) = LOWER(?)", [nama_baru]).fetchone()
                        if produk_eksis:
                            st.error(f"❌ Produk '{nama_baru}' sudah ada!")
                        else:
                            max_id = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM produk").fetchone()[0]
                            con.execute("INSERT INTO produk (id, nama_produk, kategori, harga, stok) VALUES (?, ?, ?, ?, ?)", 
                                        [int(max_id), str(nama_baru), kat_pilihan, float(harga_baru), int(stok_awal)])
                            st.success(f"Berhasil menambah {nama_baru}!")
                            st.rerun()

        with col_edit:
            with st.expander("📝 Edit Harga & Stok"):
                if not df_produk.empty:
                    with st.form("form_edit_produk"):
                        opsi_edit = {f"{r['nama_produk']} (ID: {r['id']})": r['id'] for _, r in df_produk.iterrows()}
                        pilihan_label = st.selectbox("Pilih Produk", options=list(opsi_edit.keys()))
                        id_target = opsi_edit[pilihan_label]
                        data_skrg = df_produk[df_produk['id'] == id_target].iloc[0]
                        
                        st.write(f"Harga saat ini: **Rp{data_skrg['harga']:,.0f}**")
                        harga_update = st.number_input("Set Harga Baru (Rp)", min_value=0, value=int(data_skrg['harga']), step=500)
                        stok_tambahan = st.number_input("Tambah/Kurang Stok (+/-)", step=1, value=0)
                        
                        btn_update = st.form_submit_button("Simpan Perubahan")
                        if btn_update:
                            con.execute("UPDATE produk SET harga = ?, stok = stok + ? WHERE id = ?", 
                                        [float(harga_update), int(stok_tambahan), id_target])
                            st.success("Update Berhasil!")
                            st.rerun()

        with col_hapus:
            with st.expander("🗑️ Hapus Produk"):
                if not df_produk.empty:
                    with st.form("form_hapus_produk"):
                        opsi_hapus = {f"{r['nama_produk']} (ID: {r['id']})": r['id'] for _, r in df_produk.iterrows()}
                        label_hapus = st.selectbox("Pilih Produk", options=list(opsi_hapus.keys()))
                        id_hapus = opsi_hapus[label_hapus]
                        st.warning(f"Menghapus ID: {id_hapus}")
                        konfirmasi = st.checkbox("Saya yakin ingin menghapus")
                        btn_hapus = st.form_submit_button("Hapus Permanen", type="primary")
                        
                        if btn_hapus and konfirmasi:
                            con.execute("DELETE FROM produk WHERE id = ?", [id_hapus])
                            st.success("Produk terhapus!")
                            st.rerun()

    elif menu_admin == "Data Transaksi":
        st.subheader("📝 Histori Transaksi Lengkap")
        df_tx = con.execute("SELECT * FROM transaksi ORDER BY waktu DESC").df()
        st.dataframe(df_tx, use_container_width=True, hide_index=True)

# --- LOGIKA UTAMA ---
if "logged_in" not in st.session_state:
    login_ui()
else:
    st.sidebar.write(f"User: **{st.session_state.username}** ({st.session_state.role})")
    if st.sidebar.button("Logout"):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()
    
    if st.session_state.role == "admin":
        admin_ui()
    else:
        cashier_ui()