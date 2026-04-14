import streamlit as st
import duckdb
import pandas as pd
import pytz 
import plotly.express as px # Tambahkan ini
from datetime import datetime

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sistem Kasir Pro v1", layout="wide")

# --- FUNGSI HELPER ---
def get_wib_now():
    tz_wib = pytz.timezone('Asia/Jakarta')
    return datetime.now(tz_wib)

@st.cache_resource
def get_connection():
    TOKEN = st.secrets["MOTHERDUCK_TOKEN"]
    return duckdb.connect(f"md:my_db?motherduck_token={TOKEN}")

con = get_connection()

# Inisialisasi Session State
if "cart" not in st.session_state:
    st.session_state.cart = []
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

# --- UI LOGIN ---
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

# --- UI KASIR ---
def cashier_ui():
    st.header(f"🛒 Kasir: {st.session_state.username}")
    
    # 1. Ambil Data Produk
    try:
        df_produk = con.execute("SELECT id, nama_produk, harga, stok FROM produk").df()
    except:
        st.error("Tabel produk belum siap atau kolom hilang.")
        return

    if df_produk.empty:
        st.warning("Data produk masih kosong. Silakan hubungi Admin.")
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
                        "id": produk_data['id'],
                        "nama": item_pilih,
                        "harga": produk_data['harga'],
                        "qty": qty_pilih,
                        "subtotal": qty_pilih * produk_data['harga']
                    })
                    st.rerun()
                else:
                    st.error("Stok tidak cukup!")

    with col_cart:
        st.subheader("Isi Keranjang")
        if st.session_state.cart:
            total_bayar = 0
            for i, barang in enumerate(st.session_state.cart):
                total_bayar += barang['subtotal'] # Perbaikan: Hitung Total
                c1, c2, c3 = st.columns([3, 2, 1])
                c1.write(f"**{barang['nama']}** \n{barang['qty']} x Rp{barang['harga']:,.0f}")
                c2.write(f"\nRp{barang['subtotal']:,.0f}") 
                if c3.button("🗑️", key=f"del_{i}"):
                    st.session_state.cart.pop(i)
                    st.rerun()
            
            st.divider()
            st.write(f"### TOTAL: Rp{total_bayar:,.0f}")
            
            c1, c2 = st.columns(2)
            if c1.button("🧹 Kosongkan"):
                st.session_state.cart = []
                st.rerun()

            if c2.button("✅ PROSES TRANSAKSI"):
                wib_now = get_wib_now()
                id_tx = wib_now.strftime("%Y%m%d%H%M%S")
                
                for b in st.session_state.cart:
                    # Simpan ke tabel transaksi
                    con.execute("""
                        INSERT INTO transaksi (id_transaksi, kasir, waktu, nama_produk, jumlah, harga_satuan, total_harga)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, [id_tx, st.session_state.username, wib_now, b['nama'], b['qty'], b['harga'], b['subtotal']])
                    
                    # Update Stok & Waktu Update
                    con.execute("UPDATE produk SET stok = stok - ?, terakhir_diupdate = ? WHERE nama_produk = ?", 
                                [b['qty'], wib_now, b['nama']])
                    
                    # Simpan ke Log Stok
                    max_id_log = con.execute("SELECT COALESCE(MAX(id_log), 0) + 1 FROM log_stok").fetchone()[0]
                    con.execute("INSERT INTO log_stok VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                [int(max_id_log), int(b['id']), b['nama'], 0, 0, "Transaksi Kasir", wib_now])

                st.session_state.cart = []
                st.success("Transaksi Berhasil!")
                st.rerun()
        else:
            st.info("Keranjang kosong.")

    # --- RIWAYAT HARIAN ---
    st.divider()
    st.subheader("📜 Riwayat Struk Hari Ini")
    
    pilihan_limit = st.selectbox("Tampilkan:", [5, 10, 20, "Semua"], index=0)
    limit_sql = "" if pilihan_limit == "Semua" else f"LIMIT {pilihan_limit}"
    tgl_wib_ini = get_wib_now().strftime("%Y-%m-%d")

    query_tabel = f"""
        SELECT id_transaksi AS "ID Struk", MAX(waktu) AS "Jam", SUM(total_harga) AS "Total Belanja"
        FROM transaksi WHERE CAST(waktu AS DATE) = ? GROUP BY id_transaksi ORDER BY "Jam" DESC {limit_sql}
    """
    df_struk = con.execute(query_tabel, [tgl_wib_ini]).df()
    st.dataframe(df_struk, use_container_width=True, hide_index=True)

# --- UI ADMIN ---
def admin_ui():
    st.title("🏗️ Panel Admin")
    menu_admin = st.sidebar.selectbox("Menu Admin", ["Dashboard Utama", "Manajemen Stok", "Data Transaksi"])
    
    if menu_admin == "Dashboard Utama":
        res_p = con.execute("SELECT SUM(total_harga) FROM transaksi").fetchone()
        total_penjualan = res_p[0] if res_p and res_p[0] is not None else 0
        st.metric("Total Pendapatan", f"Rp{total_penjualan:,.0f}")
        
        df_tx = con.execute("SELECT waktu, total_harga, nama_produk FROM transaksi").df()
        if not df_tx.empty:
            fig = px.bar(df_tx, x='waktu', y='total_harga', color='nama_produk', title="Grafik Penjualan")
            st.plotly_chart(fig, use_container_width=True)

    elif menu_admin == "Manajemen Stok":
        df_produk = con.execute("SELECT * FROM produk ORDER BY id ASC").df()
        st.dataframe(df_produk, use_container_width=True)
        
        t1, t2, t3, t4 = st.tabs(["➕ Tambah", "✏️ Edit", "🔄 Stok", "🗑️ Hapus"])
        
        with t1:
            with st.form("add_p"):
                n = st.text_input("Nama")
                h = st.number_input("Harga", min_value=0)
                s = st.number_input("Stok", min_value=0)
                if st.form_submit_button("Simpan"):
                    # Perbaikan: Tambahkan 5 kolom (ID, Nama, Harga, Stok, Timestamp)
                    max_id = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM produk").fetchone()[0]
                    con.execute("INSERT INTO produk VALUES (?, ?, ?, ?, ?)", [max_id, n, h, s, get_wib_now()])
                    st.rerun()

    elif menu_admin == "Data Transaksi":
        df_all = con.execute("SELECT * FROM transaksi ORDER BY waktu DESC").df()
        st.dataframe(df_all, use_container_width=True)

# --- JALANKAN APLIKASI ---
if not st.session_state.logged_in:
    login_ui()
else:
    st.sidebar.write(f"User: {st.session_state.username}")
    if st.sidebar.button("Logout"):
        st.session_state.logged_in = False
        st.rerun()
    
    if st.session_state.role == "admin":
        admin_ui()
    else:
        cashier_ui()