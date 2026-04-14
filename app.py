import streamlit as st
import duckdb
import pandas as pd
import pytz 
import plotly.express as px
from datetime import datetime

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sistem Kasir Pro v1", layout="wide", page_icon="🛒")

# --- FUNGSI HELPER ---
def get_wib_now():
    tz_wib = pytz.timezone('Asia/Jakarta')
    return datetime.now(tz_wib)

@st.cache_resource
def get_connection():
    # Mengambil token dari st.secrets
    TOKEN = st.secrets["MOTHERDUCK_TOKEN"]
    return duckdb.connect(f"md:my_db?motherduck_token={TOKEN}")

con = get_connection()

# --- INISIALISASI DATABASE (OTOMATIS) ---
def init_db():
    # Membuat tabel jika belum ada
    con.execute("""
        CREATE TABLE IF NOT EXISTS produk (
            id INTEGER PRIMARY KEY,
            nama_produk VARCHAR,
            harga DOUBLE,
            stok INTEGER,
            terakhir_diupdate TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS transaksi (
            id_transaksi VARCHAR,
            kasir VARCHAR,
            waktu TIMESTAMP,
            nama_produk VARCHAR,
            jumlah INTEGER,
            harga_satuan DOUBLE,
            total_harga DOUBLE
        );
        CREATE TABLE IF NOT EXISTS log_stok (
            id_log INTEGER PRIMARY KEY,
            id_produk INTEGER,
            nama_produk VARCHAR,
            stok_awal INTEGER,
            perubahan INTEGER,
            keterangan VARCHAR,
            waktu TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS users (
            username VARCHAR PRIMARY KEY,
            password VARCHAR,
            role VARCHAR
        );
    """)
    
    # Cek jika user admin belum ada, buat default (user: admin, pass: admin123)
    user_exists = con.execute("SELECT * FROM users WHERE username = 'admin'").fetchone()
    if not user_exists:
        con.execute("INSERT INTO users VALUES ('admin', 'admin123', 'admin'), ('kasir1', '123', 'kasir')")

init_db()

# Inisialisasi Session State
if "cart" not in st.session_state:
    st.session_state.cart = []
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

# --- UI LOGIN ---
def login_ui():
    st.title("🔐 Login Sistem Kasir")
    with st.container(border=True):
        col1, col2 = st.columns([1, 1])
        with col1:
            user = st.text_input("Username")
            pw = st.text_input("Password", type="password")
            submit = st.button("Login", use_container_width=True)
            
            if submit:
                res = con.execute("SELECT role FROM users WHERE username = ? AND password = ?", [user, pw]).fetchone()
                if res:
                    st.session_state.logged_in = True
                    st.session_state.username = user
                    st.session_state.role = res[0]
                    st.rerun()
                else:
                    st.error("Username atau Password salah!")

# --- UI KASIR ---
def cashier_ui():
    st.header(f"🛒 Kasir: {st.session_state.username}")
    
    # Ambil Data Produk yang stoknya > 0
    df_produk = con.execute("SELECT id, nama_produk, harga, stok FROM produk WHERE stok > 0").df()

    if df_produk.empty:
        st.warning("Data produk kosong atau stok habis. Silakan hubungi Admin.")
        return

    col_input, col_cart = st.columns([1, 2])
    
    with col_input:
        st.subheader("Pilih Barang")
        with st.form("form_add_to_cart", clear_on_submit=True):
            item_pilih = st.selectbox("Produk", df_produk['nama_produk'].tolist())
            qty_pilih = st.number_input("Jumlah", min_value=1, step=1)
            btn_add = st.form_submit_button("➕ Tambah ke Keranjang")

            if btn_add:
                produk_data = df_produk[df_produk['nama_produk'] == item_pilih].iloc[0]
                if produk_data['stok'] >= qty_pilih:
                    st.session_state.cart.append({
                        "id": int(produk_data['id']),
                        "nama": item_pilih,
                        "harga": float(produk_data['harga']),
                        "qty": int(qty_pilih),
                        "subtotal": float(qty_pilih * produk_data['harga'])
                    })
                    st.rerun()
                else:
                    st.error(f"Stok tidak cukup! (Sisa: {produk_data['stok']})")

    with col_cart:
        st.subheader("Isi Keranjang")
        if st.session_state.cart:
            total_bayar = sum(item['subtotal'] for item in st.session_state.cart)
            
            for i, barang in enumerate(st.session_state.cart):
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 2, 1])
                    c1.write(f"**{barang['nama']}**")
                    c1.caption(f"{barang['qty']} x Rp{barang['harga']:,.0f}")
                    c2.write(f"Rp{barang['subtotal']:,.0f}") 
                    if c3.button("🗑️", key=f"del_{i}"):
                        st.session_state.cart.pop(i)
                        st.rerun()
            
            st.divider()
            st.write(f"### TOTAL: Rp{total_bayar:,.0f}")
            
            c1, c2 = st.columns(2)
            if c1.button("🧹 Kosongkan", use_container_width=True):
                st.session_state.cart = []
                st.rerun()

            if c2.button("✅ PROSES TRANSAKSI", type="primary", use_container_width=True):
                wib_now = get_wib_now()
                # ID Transaksi unik dengan timestamp + milidetik
                id_tx = wib_now.strftime("%Y%m%d%H%M%S%f")[:-3]
                
                try:
                    for b in st.session_state.cart:
                        # 1. Simpan ke tabel transaksi
                        con.execute("""
                            INSERT INTO transaksi (id_transaksi, kasir, waktu, nama_produk, jumlah, harga_satuan, total_harga)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, [id_tx, st.session_state.username, wib_now, b['nama'], b['qty'], b['harga'], b['subtotal']])
                        
                        # 2. Update Stok
                        con.execute("UPDATE produk SET stok = stok - ?, terakhir_diupdate = ? WHERE id = ?", 
                                    [b['qty'], wib_now, b['id']])
                        
                        # 3. Simpan ke Log Stok
                        max_id_log = con.execute("SELECT COALESCE(MAX(id_log), 0) + 1 FROM log_stok").fetchone()[0]
                        con.execute("INSERT INTO log_stok VALUES (?, ?, ?, 0, ?, ?, ?)", 
                                    [int(max_id_log), b['id'], b['nama'], -b['qty'], "Penjualan Kasir", wib_now])

                    st.session_state.cart = []
                    st.success(f"Transaksi {id_tx} Berhasil!")
                    st.balloons()
                    st.rerun()
                except Exception as e:
                    st.error(f"Terjadi kesalahan: {e}")
        else:
            st.info("Keranjang masih kosong.")

# --- UI ADMIN ---
def admin_ui():
    st.title("🏗️ Panel Admin")
    menu_admin = st.sidebar.selectbox("Menu Admin", ["Dashboard Utama", "Manajemen Stok", "Data Transaksi"])
    
    if menu_admin == "Dashboard Utama":
        res_p = con.execute("SELECT SUM(total_harga) FROM transaksi").fetchone()
        total_penjualan = res_p[0] if res_p and res_p[0] is not None else 0
        
        c1, c2 = st.columns(2)
        c1.metric("Total Pendapatan", f"Rp{total_penjualan:,.0f}")
        
        df_tx = con.execute("SELECT waktu, total_harga, nama_produk FROM transaksi").df()
        if not df_tx.empty:
            fig = px.line(df_tx.sort_values('waktu'), x='waktu', y='total_harga', title="Tren Penjualan")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Belum ada data transaksi untuk grafik.")

    elif menu_admin == "Manajemen Stok":
        st.subheader("Daftar Produk")
        df_produk = con.execute("SELECT * FROM produk ORDER BY id ASC").df()
        st.dataframe(df_produk, use_container_width=True, hide_index=True)
        
        t1, t2 = st.tabs(["➕ Tambah Produk Baru", "🔄 Update Stok"])
        
        with t1:
            with st.form("add_p", clear_on_submit=True):
                n = st.text_input("Nama Produk")
                h = st.number_input("Harga", min_value=0)
                s = st.number_input("Stok Awal", min_value=0)
                if st.form_submit_button("Simpan Produk"):
                    max_id = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM produk").fetchone()[0]
                    con.execute("INSERT INTO produk VALUES (?, ?, ?, ?, ?)", [max_id, n, h, s, get_wib_now()])
                    st.success("Produk berhasil ditambahkan!")
                    st.rerun()
        
        with t2:
            if not df_produk.empty:
                with st.form("update_s"):
                    prod_update = st.selectbox("Pilih Produk", df_produk['nama_produk'].tolist())
                    stok_tambah = st.number_input("Tambah/Kurang Stok", step=1)
                    if st.form_submit_button("Update"):
                        con.execute("UPDATE produk SET stok = stok + ?, terakhir_diupdate = ? WHERE nama_produk = ?", 
                                    [stok_tambah, get_wib_now(), prod_update])
                        st.success("Stok berhasil diperbarui!")
                        st.rerun()

    elif menu_admin == "Data Transaksi":
        st.subheader("Seluruh Riwayat Transaksi")
        df_all = con.execute("SELECT * FROM transaksi ORDER BY waktu DESC").df()
        st.dataframe(df_all, use_container_width=True)

# --- JALANKAN APLIKASI ---
if not st.session_state.logged_in:
    login_ui()
else:
    st.sidebar.title(f"👋 {st.session_state.username}")
    st.sidebar.write(f"Role: **{st.session_state.role.upper()}**")
    
    if st.sidebar.button("Logout", type="secondary"):
        st.session_state.logged_in = False
        st.session_state.cart = []
        st.rerun()
    
    st.sidebar.divider()
    
    if st.session_state.role == "admin":
        admin_ui()
    else:
        cashier_ui()