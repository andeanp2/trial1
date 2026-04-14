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

# --- HALAMAN KASIR (INPUT TRANSAKSI) ---
def cashier_ui():
    st.header(f"🛒 Menu Kasir (User: {st.session_state.username})")
    
    # Ambil data produk
    df_produk = con.execute("SELECT * FROM produk").df()
    
    with st.form("transaksi_form"):
        item = st.selectbox("Pilih Produk", df_produk['nama_produk'])
        jumlah = st.number_input("Jumlah Beli", min_value=1, step=1)
        btn_beli = st.form_submit_button("Proses Transaksi")
        
        if btn_beli:
            # 1. Ambil data stok dan harga dari dataframe yang sudah di-load
            stok_skrg = df_produk[df_produk['nama_produk'] == item]['stok'].values[0]
            harga_satuan = df_produk[df_produk['nama_produk'] == item]['harga'].values[0]
            
            if stok_skrg >= jumlah:
                total = harga_satuan * jumlah
                
                # --- BARIS YANG TADI HILANG ---
                id_tx = datetime.now().strftime("%Y%m%d%H%M%S") # Membuat ID unik berdasarkan waktu
                waktu_sekarang = datetime.now()
                # ------------------------------

                # 2. Update Stok di database
                con.execute("UPDATE produk SET stok = stok - ? WHERE nama_produk = ?", [jumlah, item])
                
                # 3. Catat Transaksi dengan kolom yang jelas (Explicit)
                con.execute("""
                    INSERT INTO transaksi (id_transaksi, nama_produk, jumlah, total_harga, kasir, waktu) 
                    VALUES (?, ?, ?, ?, ?, ?)
                """, [id_tx, item, jumlah, total, st.session_state.username, waktu_sekarang])
                
                st.success(f"Transaksi Berhasil! Total: Rp{total:,.0f}")
                st.balloons() # Biar lebih seru!
                st.rerun()    # Segarkan halaman untuk update tabel stok
            else:
                st.error("Maaf, Stok tidak mencukupi!")

# --- HALAMAN ADMIN (UPDATE STOK & DASHBOARD) ---
def admin_ui():
    st.title("🏗️ Panel Admin")
    menu_admin = st.sidebar.selectbox("Menu Admin", ["Dashboard Utama", "Manajemen Stok", "Data Transaksi"])
    
    if menu_admin == "Dashboard Utama":
        st.subheader("📊 Ringkasan Bisnis")
        col1, col2 = st.columns(2)
        
        # Metric Sederhana
        total_penjualan = con.execute("SELECT SUM(total_harga) FROM transaksi").fetchone()[0] or 0
        total_stok = con.execute("SELECT SUM(stok) FROM produk").fetchone()[0] or 0
        
        col1.metric("Total Pendapatan", f"Rp{total_penjualan:,.0f}")
        col2.metric("Total Stok Barang", f"{total_stok} unit")
        
        # Grafik Penjualan (Plotly)
        df_tx = con.execute("SELECT * FROM transaksi").df()
        if not df_tx.empty:
            fig = px.bar(df_tx, x='waktu', y='total_harga', title="Tren Penjualan", color='nama_produk')
            st.plotly_chart(fig, use_container_width=True)

    elif menu_admin == "Manajemen Stok":
        st.subheader("📦 Update Stok Produk")
        df_produk = con.execute("SELECT * FROM produk").df()
        st.table(df_produk)
        
        with st.expander("Edit Stok"):
            prod_edit = st.selectbox("Pilih Produk untuk Update", df_produk['nama_produk'])
            stok_baru = st.number_input("Tambah/Kurangi Stok", step=1)
            if st.button("Update Stok"):
                con.execute("UPDATE produk SET stok = stok + ? WHERE nama_produk = ?", [stok_baru, prod_edit])
                st.success("Stok berhasil diperbarui!")
                st.rerun()

    elif menu_admin == "Data Transaksi":
        st.subheader("📝 Histori Transaksi Lengkap")
        df_tx = con.execute("SELECT * FROM transaksi ORDER BY waktu DESC").df()
        st.dataframe(df_tx, use_container_width=True)

# --- LOGIKA UTAMA ---
if "logged_in" not in st.session_state:
    login_ui()
else:
    # Sidebar untuk logout
    st.sidebar.write(f"Logged in as: **{st.session_state.username}** ({st.session_state.role})")
    if st.sidebar.button("Logout"):
        del st.session_state.logged_in
        st.rerun()
    
    # Render UI berdasarkan role
    if st.session_state.role == "admin":
        admin_ui()
    else:
        cashier_ui()