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
    st.header(f"🛒 Kasir: {st.session_state.username}")
    
    # 1. Inisialisasi Keranjang Belanja di Session State jika belum ada
    if "cart" not in st.session_state:
        st.session_state.cart = []

    # Ambil data produk terbaru
    df_produk = con.execute("SELECT * FROM produk").df()

    # LAYOUT: Kiri untuk Input, Kanan untuk Daftar Keranjang
    col_input, col_cart = st.columns([1, 2])

    with col_input:
        st.subheader("Pilih Barang")
        with st.form("form_add_to_cart", clear_on_submit=True):
            item_pilih = st.selectbox("Produk", df_produk['nama_produk'])
            qty_pilih = st.number_input("Jumlah", min_value=1, step=1)
            btn_add = st.form_submit_button("➕ Tambah ke Keranjang")

            if btn_add:
                # Ambil info harga dan stok
                row = df_produk[df_produk['nama_produk'] == item_pilih].iloc[0]
                harga_satuan = float(row['harga'])
                stok_tersedia = int(row['stok'])

                if stok_tersedia >= qty_pilih:
                    # Masukkan ke list sementara
                    st.session_state.cart.append({
                        "nama": item_pilih,
                        "qty": int(qty_pilih),
                        "harga": harga_satuan,
                        "subtotal": float(harga_satuan * qty_pilih)
                    })
                    st.toast(f"{item_pilih} ditambah!")
                else:
                    st.error("Stok tidak cukup!")

    with col_cart:
        st.subheader("Isi Keranjang")
        if st.session_state.cart:
            df_cart = pd.DataFrame(st.session_state.cart)
            st.table(df_cart)
            
            total_bayar = df_cart['subtotal'].sum()
            st.write(f"### TOTAL: Rp{total_bayar:,.0f}")

            c1, c2 = st.columns(2)
            if c1.button("🗑️ Kosongkan Keranjang"):
                st.session_state.cart = []
                st.rerun()

            if c2.button("✅ PROSES TRANSAKSI"):
                # PROSES SEMUA BARANG DI KERANJANG KE DATABASE
                id_tx = str(datetime.now().strftime("%Y%m%d%H%M%S"))
                waktu_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                
                try:
                    for barang in st.session_state.cart:
                        # Update Stok
                        con.execute("UPDATE produk SET stok = stok - ? WHERE nama_produk = ?", 
                                    [barang['qty'], barang['nama']])
                        
                        # Catat Transaksi
                        con.execute("""
                            INSERT INTO transaksi (id_transaksi, nama_produk, jumlah, total_harga, kasir, waktu) 
                            VALUES (?, ?, ?, ?, ?, ?)
                        """, [id_tx, barang['nama'], barang['qty'], barang['subtotal'], str(st.session_state.username), waktu_str])
                    
                    st.success("Transaksi Berhasil Disimpan!")
                    st.balloons()
                    st.session_state.cart = [] # Kosongkan keranjang setelah sukses
                    st.rerun()
                except Exception as e:
                    st.error(f"Gagal memproses transaksi: {e}")
        else:
            st.info("Keranjang masih kosong.")

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
        st.subheader("📦 Manajemen Gudang & Stok")
        
        # Ambil data produk terbaru
        df_produk = con.execute("SELECT * FROM produk ORDER BY id ASC").df()
        st.dataframe(df_produk, use_container_width=True)
        
        # Kita bagi menjadi dua kolom untuk aksi
        col_tambah, col_update = st.columns(2)
        
        with col_tambah:
            with st.expander("➕ Tambah Barang Baru"):
                with st.form("form_tambah_barang"):
                    nama_baru = st.text_input("Nama Produk Baru")
                    harga_baru = st.number_input("Harga Jual (Rp)", min_value=0, step=500)
                    stok_awal = st.number_input("Stok Awal", min_value=0, step=1)
                    btn_tambah = st.form_submit_button("Simpan Barang")
                    
                    if btn_tambah and nama_baru:
                        # 1. Cari ID terakhir untuk menentukan ID baru
                        max_id = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM produk").fetchone()[0]
                        
                        # 2. Masukkan ke database
                        con.execute("""
                            INSERT INTO produk (id, nama_produk, harga, stok) 
                            VALUES (?, ?, ?, ?)
                        """, [int(max_id), str(nama_baru), float(harga_baru), int(stok_awal)])
                        
                        st.success(f"Berhasil menambahkan {nama_baru}!")
                        st.rerun()

        with col_update:
            with st.expander("🔄 Update Stok (Barang Eksis)"):
                if not df_produk.empty:
                    with st.form("form_update_stok"):
                        prod_edit = st.selectbox("Pilih Produk", df_produk['nama_produk'])
                        stok_tambahan = st.number_input("Jumlah Perubahan Stok (+/-)", step=1)
                        btn_update = st.form_submit_button("Update Stok")
                        
                        if btn_update:
                            con.execute("UPDATE produk SET stok = stok + ? WHERE nama_produk = ?", 
                                        [int(stok_tambahan), str(prod_edit)])
                            st.success(f"Stok {prod_edit} berhasil diperbarui!")
                            st.rerun()
                else:
                    st.info("Belum ada barang di database.")

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