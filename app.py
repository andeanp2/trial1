import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta, timezone

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sistem Kasir Pro v1.1 - Full", layout="wide")

# --- 2. KONEKSI & INISIALISASI DATABASE ---
@st.cache_resource
def get_connection():
    try:
        TOKEN = st.secrets["MOTHERDUCK_TOKEN"]
        con = duckdb.connect(f"md:tes_db?motherduck_token={TOKEN}")
        
        # Inisialisasi tabel labels jika belum ada
        con.execute("""
            CREATE TABLE IF NOT EXISTS labels (
                id INTEGER PRIMARY KEY,
                nama_label VARCHAR,
                kategori_terkait VARCHAR,
                harga_tambahan DOUBLE
            )
        """)
        return con
    except Exception as e:
        st.error(f"Gagal koneksi: {e}")
        st.stop()

con = get_connection()
WIB = timezone(timedelta(hours=7))

def get_now_wib():
    return datetime.now(timezone.utc).astimezone(WIB)

# --- 3. UI KASIR (Logika Produk & Label Terpisah) ---
def cashier_ui():
    st.header(f"🛒 Kasir: {st.session_state.username}")
    now_wib = get_now_wib()
    
    if "cart" not in st.session_state: st.session_state.cart = []

    df_p = con.execute("SELECT * FROM produk").df()
    df_l = con.execute("SELECT * FROM labels").df()

    col_in, col_cart = st.columns([1, 2])

    with col_in:
        st.subheader("Input Pesanan")
        if not df_p.empty:
            p_name = st.selectbox("Pilih Produk", df_p['nama_produk'].unique())
            p_info = df_p[df_p['nama_produk'] == p_name].iloc[0]
            
            # Filter label berdasarkan kategori produk
            available_labels = df_l[df_l['kategori_terkait'] == p_info['kategori']]
            
            selected_opsi = st.multiselect(f"Opsi {p_info['kategori']}", available_labels['nama_label'].tolist())
            qty = st.number_input("Jumlah", min_value=1, step=1)

            # Hitung harga
            tambahan = available_labels[available_labels['nama_label'].isin(selected_opsi)]['harga_tambahan'].sum()
            harga_total_satuan = p_info['harga'] + tambahan

            if st.button("➕ Tambah Ke Keranjang", use_container_width=True):
                if p_info['stok'] >= qty:
                    st.session_state.cart.append({
                        "id_p": int(p_info['id']),
                        "nama": p_name,
                        "opsi": ", ".join(selected_opsi),
                        "qty": int(qty),
                        "harga": float(harga_total_satuan),
                        "subtotal": float(harga_total_satuan * qty)
                    })
                    st.rerun()
                else:
                    st.error("Stok tidak cukup!")
        else:
            st.warning("Produk belum ada.")

    with col_cart:
        st.subheader("🛒 Keranjang")
        if st.session_state.cart:
            df_cart = pd.DataFrame(st.session_state.cart)
            st.table(df_cart[['nama', 'opsi', 'qty', 'subtotal']])
            total_akhir = df_cart['subtotal'].sum()
            st.write(f"### TOTAL: Rp{total_akhir:,.0f}")
            
            if st.button("✅ SELESAIKAN", type="primary", use_container_width=True):
                id_tx = now_wib.strftime("%Y%m%d%H%M%S")
                for i in st.session_state.cart:
                    # Simpan Transaksi
                    con.execute("INSERT INTO transaksi VALUES (?, ?, ?, ?, ?, ?, ?)",
                                [id_tx, i['nama'], i['qty'], i['subtotal'], st.session_state.username, now_wib.replace(tzinfo=None), i['opsi']])
                    # Potong Stok Produk Dasar
                    con.execute("UPDATE produk SET stok = stok - ? WHERE id = ?", [i['qty'], i['id_p']])
                
                st.session_state.cart = []
                st.success("Berhasil!")
                st.rerun()

# --- 4. UI ADMIN (Dashboard & Kelola) ---
def admin_ui():
    now_wib = get_now_wib()
    st.title("🏗️ Panel Admin v1.1")
    
    menu = st.sidebar.selectbox("Menu Admin", ["Dashboard", "Produk", "Label/Opsi", "Riwayat Transaksi"])

    # --- TAB: DASHBOARD ---
    if menu == "Dashboard":
        st.subheader("📈 Ringkasan Penjualan")
        today = now_wib.strftime('%Y-%m-%d')
        
        # Omset Hari Ini
        res = con.execute("SELECT SUM(total_harga) FROM transaksi WHERE CAST(waktu AS DATE) = ?", [today]).fetchone()
        omset = res[0] if res[0] else 0
        st.metric("Omset Hari Ini", f"Rp{omset:,.0f}")

        # Grafik Transaksi
        df_tx = con.execute("SELECT * FROM transaksi").df()
        if not df_tx.empty:
            df_tx['waktu'] = pd.to_datetime(df_tx['waktu'])
            fig = px.line(df_tx.groupby('waktu')['total_harga'].sum().reset_index(), 
                         x='waktu', y='total_harga', title="Tren Omset")
            st.plotly_chart(fig, use_container_width=True)

    # --- TAB: PRODUK ---
    elif menu == "Produk":
        st.subheader("📦 Manajemen Produk")
        df_p = con.execute("SELECT * FROM produk").df()
        st.dataframe(df_p, use_container_width=True, hide_index=True)
        
        t1, t2 = st.tabs(["➕ Tambah", "🗑️ Hapus"])
        with t1:
            with st.form("add_p"):
                n = st.text_input("Nama Produk")
                k = st.selectbox("Kategori", ["Minuman", "Makanan", "Snack"])
                h = st.number_input("Harga Dasar", min_value=0)
                s = st.number_input("Stok", min_value=0)
                if st.form_submit_button("Simpan"):
                    new_id = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM produk").fetchone()[0]
                    con.execute("INSERT INTO produk VALUES (?,?,?,?,?, '')", [new_id, n, k, h, s])
                    st.rerun()
        with t2:
            del_id = st.number_input("ID Produk untuk dihapus", min_value=1)
            if st.button("Hapus Produk"):
                con.execute("DELETE FROM produk WHERE id=?", [del_id])
                st.rerun()

    # --- TAB: LABEL/OPSI ---
    elif menu == "Label/Opsi":
        st.subheader("🏷️ Pengaturan Label Otomatis")
        st.info("Label di sini akan muncul otomatis di kasir sesuai kategori produk.")
        
        df_l = con.execute("SELECT * FROM labels").df()
        st.dataframe(df_l, use_container_width=True, hide_index=True)

        with st.form("add_l"):
            nl = st.text_input("Nama Label (Contoh: Dingin, Pedas, Besar)")
            kl = st.selectbox("Kategori Terkait", ["Minuman", "Makanan", "Snack"])
            hl = st.number_input("Harga Tambahan (Rp)", min_value=0, step=500)
            if st.form_submit_button("Tambah Label"):
                nid = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM labels").fetchone()[0]
                con.execute("INSERT INTO labels VALUES (?,?,?,?)", [nid, nl, kl, hl])
                st.rerun()

    # --- TAB: TRANSAKSI ---
    elif menu == "Riwayat Transaksi":
        st.subheader("📜 Semua Transaksi")
        df_tx = con.execute("SELECT * FROM transaksi ORDER BY waktu DESC").df()
        st.dataframe(df_tx, use_container_width=True)

# --- 5. LOGIKA AUTH & MAIN ---
if "logged_in" not in st.session_state:
    st.title("🔐 Login")
    u = st.text_input("Username")
    p = st.text_input("Password", type="password")
    if st.button("Login"):
        res = con.execute("SELECT role FROM users WHERE username=? AND password=?", [u, p]).fetchone()
        if res:
            st.session_state.logged_in = True
            st.session_state.username = u
            st.session_state.role = res[0]
            st.rerun()
        else:
            st.error("Salah!")
else:
    if st.sidebar.button("🚪 Logout"):
        st.session_state.clear()
        st.rerun()
    
    if st.session_state.role == "admin":
        admin_ui()
    else:
        cashier_ui()