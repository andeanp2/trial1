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
    TOKEN = st.secrets["MOTHERDUCK_TOKEN"]
    return duckdb.connect(f"md:my_db?motherduck_token={TOKEN}")

con = get_connection()

# --- INISIALISASI DATABASE ---
def init_db():
    con.execute("CREATE TABLE IF NOT EXISTS produk (id INTEGER PRIMARY KEY, nama_produk VARCHAR, harga DOUBLE, stok INTEGER, terakhir_diupdate TIMESTAMP)")
    con.execute("CREATE TABLE IF NOT EXISTS transaksi (id_transaksi VARCHAR, kasir VARCHAR, waktu TIMESTAMP, nama_produk VARCHAR, jumlah INTEGER, harga_satuan DOUBLE, total_harga DOUBLE)")
    con.execute("CREATE TABLE IF NOT EXISTS users (username VARCHAR PRIMARY KEY, password VARCHAR, role VARCHAR)")
    
    con.execute("INSERT OR IGNORE INTO users VALUES ('admin', 'admin123', 'admin')")
    con.execute("INSERT OR IGNORE INTO users VALUES ('kasir1', '123', 'kasir')")

init_db()

# Session State Handling
if "cart" not in st.session_state:
    st.session_state.cart = []
if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

# --- UI LOGIN ---
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

# --- UI KASIR ---
def cashier_ui():
    st.header(f"🛒 Kasir: {st.session_state.username}")
    
    df_produk = con.execute("SELECT id, nama_produk, harga, stok FROM produk WHERE stok > 0").df()
    if df_produk.empty:
        st.warning("Data produk kosong atau stok habis. Hubungi Admin.")
        return

    col_input, col_cart = st.columns([1, 2])
    
    with col_input:
        st.subheader("Pilih Barang")
        with st.form("form_add_to_cart", clear_on_submit=True):
            item_pilih = st.selectbox("Produk", df_produk['nama_produk'].tolist())
            qty_pilih = st.number_input("Jumlah", min_value=1, step=1)
            if st.form_submit_button("➕ Tambah ke Keranjang"):
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
                try:
                    for b in st.session_state.cart:
                        con.execute("INSERT INTO transaksi VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                    [id_tx, st.session_state.username, wib_now, b['nama'], b['qty'], b['harga'], b['subtotal']])
                        con.execute("UPDATE produk SET stok = stok - ?, terakhir_diupdate = ? WHERE id = ?", 
                                    [b['qty'], wib_now, b['id']])
                    st.session_state.cart = []
                    st.success("Transaksi Berhasil!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Gagal transaksi: {e}")
        else:
            st.info("Keranjang kosong.")

# --- UI ADMIN ---
def admin_ui():
    st.title("🏗️ Panel Admin")
    menu_admin = st.sidebar.selectbox("Menu Admin", ["Dashboard", "Manajemen Stok", "Data Transaksi"])
    
    if menu_admin == "Dashboard":
        res_p = con.execute("SELECT SUM(total_harga) FROM transaksi").fetchone()
        st.metric("Total Pendapatan", f"Rp{res_p[0] or 0:,.0f}")
        df_tx = con.execute("SELECT waktu, total_harga, nama_produk FROM transaksi").df()
        if not df_tx.empty:
            st.plotly_chart(px.line(df_tx.sort_values('waktu'), x='waktu', y='total_harga', title="Grafik Penjualan"), use_container_width=True)

    elif menu_admin == "Manajemen Stok":
        st.subheader("📦 Pengaturan Produk")
        df_produk = con.execute("SELECT * FROM produk ORDER BY id ASC").df()
        st.dataframe(df_produk, use_container_width=True, hide_index=True)
        
        t1, t2, t3 = st.tabs(["➕ Tambah Baru", "🔄 Update Stok/Harga", "🗑️ Hapus Produk"])
        
        # 1. TAMBAH PRODUK (DENGAN WARNING DUPLIKAT)
        with t1:
            with st.form("add_p", clear_on_submit=True):
                n = st.text_input("Nama Produk")
                h = st.number_input("Harga Satuan", min_value=0, step=500)
                s = st.number_input("Stok Awal", min_value=0)
                if st.form_submit_button("Simpan"):
                    if n:
                        # Cek apakah nama sudah ada (Case Insensitive)
                        check = con.execute("SELECT 1 FROM produk WHERE LOWER(nama_produk) = LOWER(?)", [n.strip()]).fetchone()
                        if check:
                            st.warning(f"⚠️ Produk '{n}' sudah ada di database.")
                        else:
                            max_id = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM produk").fetchone()[0]
                            con.execute("INSERT INTO produk VALUES (?, ?, ?, ?, ?)", [max_id, n.strip(), h, s, get_wib_now()])
                            st.success(f"Berhasil menambah {n}")
                            st.rerun()
                    else:
                        st.error("Nama produk tidak boleh kosong.")

        # 2. UPDATE STOK & HARGA
        with t2:
            if not df_produk.empty:
                with st.form("update_s"):
                    p_upd = st.selectbox("Pilih Produk yang akan diupdate", df_produk['nama_produk'].tolist())
                    new_h = st.number_input("Update Harga Baru (Biarkan jika tetap)", min_value=0)
                    new_s = st.number_input("Tambah Stok (Gunakan angka negatif untuk mengurangi)", step=1)
                    if st.form_submit_button("Update Data"):
                        # Jika harga baru 0, pakai harga lama
                        current_h = con.execute("SELECT harga FROM produk WHERE nama_produk = ?", [p_upd]).fetchone()[0]
                        final_h = new_h if new_h > 0 else current_h
                        
                        con.execute("UPDATE produk SET stok = stok + ?, harga = ?, terakhir_diupdate = ? WHERE nama_produk = ?", 
                                    [new_s, final_h, get_wib_now(), p_upd])
                        st.success(f"Produk {p_upd} berhasil diperbarui!")
                        st.rerun()
            else:
                st.info("Belum ada produk.")

        # 3. HAPUS PRODUK (BARU)
        with t3:
            if not df_produk.empty:
                st.warning("Hati-hati: Produk yang dihapus tidak bisa dikembalikan!")
                with st.form("del_p"):
                    p_del = st.selectbox("Pilih Produk yang akan DIHAPUS", df_produk['nama_produk'].tolist())
                    konfirmasi = st.checkbox("Saya yakin ingin menghapus produk ini secara permanen")
                    if st.form_submit_button("🚨 HAPUS SEKARANG", type="primary"):
                        if konfirmasi:
                            con.execute("DELETE FROM produk WHERE nama_produk = ?", [p_del])
                            st.success(f"Produk '{p_del}' telah dihapus.")
                            st.rerun()
                        else:
                            st.error("Centang kotak konfirmasi dulu!")
            else:
                st.info("Tidak ada produk untuk dihapus.")

    elif menu_admin == "Data Transaksi":
        st.subheader("📜 Riwayat Penjualan")
        df_all = con.execute("SELECT * FROM transaksi ORDER BY waktu DESC").df()
        st.dataframe(df_all, use_container_width=True)

# --- LOGOUT & RUN ---
if not st.session_state.logged_in:
    login_ui()
else:
    st.sidebar.title(f"👋 {st.session_state.username}")
    if st.sidebar.button("Logout", use_container_width=True):
        st.session_state.logged_in = False
        st.session_state.cart = []
        st.rerun()
    
    if st.session_state.role == "admin":
        admin_ui()
    else:
        cashier_ui()