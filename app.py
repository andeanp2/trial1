import streamlit as st
import duckdb
import pandas as pd
import pytz 
import plotly.express as px
from datetime import datetime

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sistem Kasir Pro v1", layout="wide", page_icon="🛒")

# --- 2. FUNGSI HELPER ---
def get_wib_now():
    tz_wib = pytz.timezone('Asia/Jakarta')
    return datetime.now(tz_wib)

@st.cache_resource
def get_connection():
    # Pastikan TOKEN sudah ada di .streamlit/secrets.toml
    TOKEN = st.secrets["MOTHERDUCK_TOKEN"]
    return duckdb.connect(f"md:my_db?motherduck_token={TOKEN}")

con = get_connection()

# --- 3. INISIALISASI DATABASE ---
def init_db():
    # Buat tabel satu per satu agar stabil
    con.execute("CREATE TABLE IF NOT EXISTS produk (id INTEGER PRIMARY KEY, nama_produk VARCHAR, harga DOUBLE, stok INTEGER, terakhir_diupdate TIMESTAMP)")
    con.execute("CREATE TABLE IF NOT EXISTS transaksi (id_transaksi VARCHAR, kasir VARCHAR, waktu TIMESTAMP, nama_produk VARCHAR, jumlah INTEGER, harga_satuan DOUBLE, total_harga DOUBLE)")
    con.execute("CREATE TABLE IF NOT EXISTS users (username VARCHAR PRIMARY KEY, password VARCHAR, role VARCHAR)")
    
    # User default (Gunakan OR IGNORE agar tidak error saat refresh)
    con.execute("INSERT OR IGNORE INTO users VALUES ('admin', 'admin123', 'admin')")
    con.execute("INSERT OR IGNORE INTO users VALUES ('kasir1', '123', 'kasir')")

init_db()

# Inisialisasi Session State
if "cart" not in st.session_state:
    st.session_state.cart = []
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

# --- 4. UI LOGIN ---
def login_ui():
    st.title("🔐 Login Sistem Kasir")
    with st.container(border=True):
        col1, _ = st.columns([1, 1])
        with col1:
            user = st.text_input("Username")
            pw = st.text_input("Password", type="password")
            if st.button("Login", use_container_width=True):
                res = con.execute("SELECT role FROM users WHERE username = ? AND password = ?", [user, pw]).fetchone()
                if res:
                    st.session_state.logged_in = True
                    st.session_state.username = user
                    st.session_state.role = res[0]
                    st.rerun()
                else:
                    st.error("Username atau Password salah!")

# --- 5. UI KASIR ---
def cashier_ui():
    st.header(f"🛒 Kasir: {st.session_state.username}")
    
    # Ambil produk yang stoknya ada
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
            if st.form_submit_button("➕ Tambah"):
                # Cari data produk yang dipilih
                p_data = df_produk[df_produk['nama_produk'] == item_pilih].iloc[0]
                
                if p_data['stok'] >= qty_pilih:
                    st.session_state.cart.append({
                        "id": int(p_data['id']),
                        "nama": item_pilih,
                        "harga": float(p_data['harga']),
                        "qty": int(qty_pilih),
                        "subtotal": float(qty_pilih * p_data['harga'])
                    })
                    st.rerun()
                else:
                    st.error("Stok tidak cukup!")

    with col_cart:
        st.subheader("Isi Keranjang")
        if st.session_state.cart:
            total_bayar = sum(item.get('subtotal', 0) for item in st.session_state.cart)
            
            for i, barang in enumerate(st.session_state.cart):
                with st.container(border=True):
                    c1, c2, c3 = st.columns([3, 2, 1])
                    c1.write(f"**{barang['nama']}**")
                    c1.caption(f"{barang['qty']} x Rp{barang['harga']:,.0f}")
                    c2.write(f"Rp{barang.get('subtotal', 0):,.0f}") 
                    if c3.button("🗑️", key=f"del_{i}"):
                        st.session_state.cart.pop(i)
                        st.rerun()
            
            st.divider()
            st.write(f"### TOTAL: Rp{total_bayar:,.0f}")
            
            if st.button("✅ PROSES TRANSAKSI", type="primary", use_container_width=True):
                wib_now = get_wib_now()
                id_tx = wib_now.strftime("%Y%m%d%H%M%S%f")[:-3]
                
                for b in st.session_state.cart:
                    # Simpan Transaksi
                    con.execute("INSERT INTO transaksi VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                [id_tx, st.session_state.username, wib_now, b['nama'], b['qty'], b['harga'], b['subtotal']])
                    # Update Stok
                    con.execute("UPDATE produk SET stok = stok - ? WHERE id = ?", [b['qty'], b['id']])
                
                st.session_state.cart = []
                st.success("Transaksi Berhasil!")
                st.rerun()
        else:
            st.info("Keranjang kosong.")

# --- 6. UI ADMIN ---
def admin_ui():
    st.title("🏗️ Panel Admin")
    menu_admin = st.sidebar.selectbox("Menu Admin", ["Dashboard", "Manajemen Stok", "Data Transaksi"])
    
    if menu_admin == "Dashboard":
        res_p = con.execute("SELECT SUM(total_harga) FROM transaksi").fetchone()
        total_val = res_p[0] if res_p and res_p[0] is not None else 0
        st.metric("Total Pendapatan", f"Rp{total_val:,.0f}")
        
        # Ambil data untuk grafik
        df_tx = con.execute("SELECT waktu, total_harga, nama_produk FROM transaksi").df()
        if not df_tx.empty:
            fig = px.bar(df_tx, x='waktu', y='total_harga', color='nama_produk', title="Tren Penjualan")
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Belum ada data transaksi untuk grafik.")

    elif menu_admin == "Manajemen Stok":
        st.subheader("📦 Pengaturan Produk")
        df_p = con.execute("SELECT * FROM produk ORDER BY id ASC").df()
        st.dataframe(df_p, use_container_width=True, hide_index=True)
        
        t1, t2, t3 = st.tabs(["➕ Tambah Baru", "🔄 Update Stok/Harga", "🗑️ Hapus Produk"])
        
        with t1:
            with st.form("add_form", clear_on_submit=True):
                n = st.text_input("Nama Produk")
                h = st.number_input("Harga Satuan", min_value=0, step=500)
                s = st.number_input("Stok Awal", min_value=0)
                if st.form_submit_button("Simpan"):
                    if n:
                        # Cek duplikat nama
                        check = con.execute("SELECT 1 FROM produk WHERE LOWER(nama_produk) = LOWER(?)", [n.strip()]).fetchone()
                        if check:
                            st.warning(f"Produk '{n}' sudah ada.")
                        else:
                            mid = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM produk").fetchone()[0]
                            con.execute("INSERT INTO produk VALUES (?, ?, ?, ?, ?)", [mid, n.strip(), h, s, get_wib_now()])
                            st.rerun()
        
        with t2:
            if not df_p.empty:
                with st.form("upd_form"):
                    p_sel = st.selectbox("Pilih Produk", df_p['nama_produk'].tolist())
                    u_h = st.number_input("Update Harga (0 jika tetap)", min_value=0)
                    u_s = st.number_input("Tambah Stok (bisa negatif)", step=1)
                    if st.form_submit_button("Update"):
                        old_h = con.execute("SELECT harga FROM produk WHERE nama_produk = ?", [p_sel]).fetchone()[0]
                        fix_h = u_h if u_h > 0 else old_h
                        con.execute("UPDATE produk SET stok = stok + ?, harga = ?, terakhir_diupdate = ? WHERE nama_produk = ?", 
                                    [u_s, fix_h, get_wib_now(), p_sel])
                        st.rerun()
        
        with t3:
            if not df_p.empty:
                with st.form("del_form"):
                    p_del = st.selectbox("Produk yang akan DIHAPUS", df_p['nama_produk'].tolist())
                    confirm = st.checkbox("Saya yakin ingin menghapus produk ini")
                    if st.form_submit_button("🚨 HAPUS", type="primary"):
                        if confirm:
                            con.execute("DELETE FROM produk WHERE nama_produk = ?", [p_del])
                            st.rerun()
                        else:
                            st.error("Centang konfirmasi dulu!")

    elif menu_admin == "Data Transaksi":
        df_all = con.execute("SELECT * FROM transaksi ORDER BY waktu DESC").df()
        st.dataframe(df_all, use_container_width=True)

# --- 7. MAIN RUNNER ---
if not st.session_state.logged_in:
    login_ui()
else:
    st.sidebar.title(f"👋 {st.session_state.username}")
    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.session_state.cart = []
        st.rerun()
    
    if st.session_state.role == "admin":
        admin_ui()
    else:
        cashier_ui()