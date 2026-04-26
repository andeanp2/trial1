import streamlit as st
import duckdb
import pandas as pd
from datetime import datetime, timedelta, timezone

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sistem Kasir Pro v1.1", layout="wide")

# --- 2. KONEKSI DATABASE ---
@st.cache_resource
def get_connection():
    TOKEN = st.secrets["MOTHERDUCK_TOKEN"]
    con = duckdb.connect(f"md:tes_db?motherduck_token={TOKEN}")
    # Inisialisasi Tabel Baru jika belum ada
    con.execute("""
        CREATE TABLE IF NOT EXISTS labels (
            id INTEGER PRIMARY KEY,
            nama_label VARCHAR,
            kategori_terkait VARCHAR,
            harga_tambahan DOUBLE
        )
    """)
    return con

con = get_connection()
WIB = timezone(timedelta(hours=7))

def get_now_wib():
    return datetime.now(timezone.utc).astimezone(WIB)

# --- 3. UI KASIR ---
def cashier_ui():
    st.header(f"🛒 Terminal Kasir")
    
    if "cart" not in st.session_state: st.session_state.cart = []
    
    # Ambil Data
    df_produk = con.execute("SELECT * FROM produk").df()
    df_labels = con.execute("SELECT * FROM labels").df()

    col_in, col_cart = st.columns([1, 2])

    with col_in:
        st.subheader("Pilih Pesanan")
        p_name = st.selectbox("Produk", df_produk['nama_produk'].tolist())
        
        # Ambil info produk terpilih
        selected_p_info = df_produk[df_produk['nama_produk'] == p_name].iloc[0]
        kat_produk = selected_p_info['kategori']
        harga_dasar = selected_p_info['harga']
        
        # FILTER LABEL: Hanya munculkan label yang kategorinya sama dengan produk
        available_labels = df_labels[df_labels['kategori_terkait'] == kat_produk]
        
        selected_opsi = st.multiselect(
            f"Opsi (Khusus {kat_produk})", 
            options=available_labels['nama_label'].tolist()
        )
        
        qty = st.number_input("Jumlah", min_value=1, step=1)
        
        # Hitung tambahan harga dari label
        tambahan_harga = available_labels[available_labels['nama_label'].isin(selected_opsi)]['harga_tambahan'].sum()
        harga_satuan = harga_dasar + tambahan_harga

        if st.button("➕ Tambah ke Keranjang", use_container_width=True):
            st.session_state.cart.append({
                "id": int(selected_p_info['id']),
                "nama": p_name,
                "opsi": ", ".join(selected_opsi),
                "qty": int(qty),
                "harga_satuan": harga_satuan,
                "subtotal": harga_satuan * qty
            })
            st.rerun()

    with col_cart:
        st.subheader("🛒 Keranjang")
        if st.session_state.cart:
            df_cart = pd.DataFrame(st.session_state.cart)
            st.table(df_cart[['nama', 'opsi', 'qty', 'subtotal']])
            total_bayar = df_cart['subtotal'].sum()
            st.write(f"## TOTAL: Rp{total_bayar:,.0f}")
            
            if st.button("✅ Selesaikan Transaksi", type="primary"):
                now = get_now_wib()
                id_tx = now.strftime("%Y%m%d%H%M%S")
                for item in st.session_state.cart:
                    con.execute("INSERT INTO transaksi VALUES (?, ?, ?, ?, ?, ?, ?)",
                                [id_tx, item['nama'], item['qty'], item['subtotal'], 
                                 st.session_state.username, now.replace(tzinfo=None), item['opsi']])
                    con.execute("UPDATE produk SET stok = stok - ? WHERE id = ?", [item['qty'], item['id']])
                
                st.session_state.cart = []
                st.success("Transaksi Berhasil Disimpan!")
                st.rerun()

# --- 4. UI ADMIN (MANAJEMEN LABEL) ---
def admin_ui():
    st.title("🏗️ Panel Admin v1.1")
    menu = st.sidebar.selectbox("Menu", ["Dashboard", "Produk", "Kelola Label", "Transaksi"])

    if menu == "Kelola Label":
        st.subheader("🏷️ Pengaturan Label/Opsi")
        
        # Form Tambah Label
        with st.expander("➕ Tambah Label Baru"):
            with st.form("add_label"):
                nl = st.text_input("Nama Label (Contoh: Dingin, Cup Besar)")
                kl = st.selectbox("Berlaku Untuk Kategori", ["Minuman", "Makanan", "Fashion"])
                hl = st.number_input("Harga Tambahan (Isi 0 jika gratis)", min_value=0, step=500)
                if st.form_submit_button("Simpan Label"):
                    new_id = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM labels").fetchone()[0]
                    con.execute("INSERT INTO labels VALUES (?,?,?,?)", [new_id, nl, kl, hl])
                    st.success("Label Berhasil Dibuat")
                    st.rerun()

        # Daftar Label
        df_l = con.execute("SELECT * FROM labels").df()
        st.dataframe(df_l, use_container_width=True, hide_index=True)
        
        if not df_l.empty:
            del_id = st.number_input("ID Label untuk dihapus", min_value=1, step=1)
            if st.button("🗑️ Hapus Label"):
                con.execute("DELETE FROM labels WHERE id=?", [del_id])
                st.rerun()

    elif menu == "Produk":
        st.subheader("📦 Kelola Produk Dasar")
        # Logika Tambah/Edit Produk (Hanya input Nama, Kat, Harga Dasar, Stok)
        # (Sama seperti v1.0 tapi tanpa kolom 'opsi' di form input)
        df_p = con.execute("SELECT id, nama_produk, kategori, harga as harga_dasar, stok FROM produk").df()
        st.dataframe(df_p, use_container_width=True)
        
        with st.form("tambah_p"):
            n = st.text_input("Nama Produk"); k = st.selectbox("Kat", ["Minuman", "Makanan"])
            h = st.number_input("Harga Dasar"); s = st.number_input("Stok")
            if st.form_submit_button("Simpan"):
                nid = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM produk").fetchone()[0]
                con.execute("INSERT INTO produk (id, nama_produk, kategori, harga, stok) VALUES (?,?,?,?,?)", [nid, n, k, h, s])
                st.rerun()

# --- 5. LOGIKA AUTH ---
if "logged_in" not in st.session_state:
    # Form Login Sederhana (Username & Password)
    st.title("🔐 Login")
    user = st.text_input("User")
    pw = st.text_input("Pass", type="password")
    if st.button("Login"):
        res = con.execute("SELECT role FROM users WHERE username=? AND password=?", [user, pw]).fetchone()
        if res:
            st.session_state.logged_in = True
            st.session_state.username = user
            st.session_state.role = res[0]
            st.rerun()
else:
    if st.sidebar.button("Logout"):
        st.session_state.clear()
        st.rerun()
    
    if st.session_state.role == "admin": admin_ui()
    else: cashier_ui()