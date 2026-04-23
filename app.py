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
    if "cart" not in st.session_state: st.session_state.cart = []

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
                            "nama": item_pilih, "qty": int(qty_pilih),
                            "harga": float(row_info['harga']), "subtotal": float(row_info['harga'] * qty_pilih),
                            "opsi": pilihan_opsi_str
                        })
                        st.rerun()
                    else:
                        st.error("Stok Produk Habis!")

    with col_cart:
        st.subheader("Isi Keranjang")
        if st.session_state.cart:
            total_bayar = sum(item['subtotal'] for item in st.session_state.cart)
            for i, b in enumerate(st.session_state.cart):
                c1, c2, c3 = st.columns([3, 2, 1])
                info_barang = f"**{b['nama']}**"
                if b['opsi']: info_barang += f"  \n*({b['opsi']})*"
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