import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px
from datetime import datetime

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sistem Kasir Pro v2", layout="wide")

# --- KONEKSI DATABASE ---
@st.cache_resource
def get_connection():
    # Menghubungkan langsung tanpa menjalankan script CREATE TABLE tiap kali
    TOKEN = st.secrets["MOTHERDUCK_TOKEN"]
    return duckdb.connect(f"md:tes_db?motherduck_token={TOKEN}")

con = get_connection()

# --- FUNGSI LOGIN ---
def login_ui():
    st.title("🔐 Login Sistem Kasir")
    with st.form("login_form"):
        user = st.text_input("Username")
        pw = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")
        if submit:
            try:
                res = con.execute("SELECT role FROM users WHERE username = ? AND password = ?", [user, pw]).fetchone()
                if res:
                    st.session_state.logged_in = True
                    st.session_state.username = user
                    st.session_state.role = res[0]
                    st.rerun()
                else:
                    st.error("Username atau Password salah!")
            except Exception as e:
                st.error(f"Error: Pastikan tabel 'users' sudah ada di MotherDuck. ({e})")

# --- HALAMAN KASIR ---
def cashier_ui():
    st.header(f"🛒 Kasir: {st.session_state.username}")
    if "cart" not in st.session_state: st.session_state.cart = []

    try:
        df_produk = con.execute("SELECT * FROM produk").df()
    except:
        st.error("Gagal mengambil data produk. Periksa tabel di MotherDuck.")
        return

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
                
                pilihan_opsi = ""
                if row_info['opsi'] and str(row_info['opsi']) != "None" and row_info['opsi'] != "":
                    list_opsi = [o.strip() for o in str(row_info['opsi']).split(",")]
                    pilihan_user = st.multiselect("Tambahan:", list_opsi)
                    pilihan_opsi = ", ".join(pilihan_user)

                if st.form_submit_button("➕ Tambah"):
                    if int(row_info['stok']) >= qty_pilih:
                        st.session_state.cart.append({
                            "id_produk": int(row_info['id']),
                            "nama": item_pilih, "qty": int(qty_pilih),
                            "harga": float(row_info['harga']), "subtotal": float(row_info['harga'] * qty_pilih),
                            "opsi": pilihan_opsi
                        })
                        st.rerun()
                    else:
                        st.error("Stok Produk Habis!")
            else:
                st.warning("Tidak ada produk di kategori ini.")

    with col_cart:
        st.subheader("Isi Keranjang")
        if st.session_state.cart:
            total_bayar = sum(item['subtotal'] for item in st.session_state.cart)
            for i, b in enumerate(st.session_state.cart):
                c1, c2, c3 = st.columns([3, 2, 1])
                c1.write(f"**{b['nama']}** ({b['opsi']})\n{b['qty']} x Rp{b['harga']:,.0f}")
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
                    # 1. Kurangi Stok Produk
                    con.execute("UPDATE produk SET stok = stok - ? WHERE id = ?", [b['qty'], b['id_produk']])
                    
                    # 2. Kurangi Stok Label/Bahan Baku
                    con.execute("""
                        UPDATE label_stok 
                        SET stok = stok - (SELECT jumlah_pemakaian * ? FROM produk_label WHERE id_produk = ? AND id_label = label_stok.id_label)
                        WHERE id_label IN (SELECT id_label FROM produk_label WHERE id_produk = ?)
                    """, [b['qty'], b['id_produk'], b['id_produk']])
                    
                    # 3. Simpan Transaksi
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
    menu = st.sidebar.selectbox("Menu Admin", ["Dashboard", "Stok Produk", "Bahan Baku (Label)", "Data Transaksi"])
    
    if menu == "Dashboard":
        st.subheader("📊 Performa Penjualan")
        c1, c2 = st.columns(2)
        hari_ini = con.execute("SELECT SUM(total_harga) FROM transaksi WHERE CAST(waktu AS DATE) = CURRENT_DATE").fetchone()[0] or 0
        bulan_ini = con.execute("SELECT SUM(total_harga) FROM transaksi WHERE date_trunc('month', CAST(waktu AS TIMESTAMP)) = date_trunc('month', CURRENT_DATE)").fetchone()[0] or 0
        c1.metric("Omset Hari Ini", f"Rp{hari_ini:,.0f}")
        c2.metric("Omset Bulan Ini", f"Rp{bulan_ini:,.0f}")
        df_tx = con.execute("SELECT * FROM transaksi").df()
        if not df_tx.empty:
            st.plotly_chart(px.bar(df_tx, x='waktu', y='total_harga', color='nama_produk', title="Tren Penjualan"), use_container_width=True)

    elif menu == "Stok Produk":
        st.subheader("📦 Manajemen Produk")
        df_p = con.execute("SELECT * FROM produk ORDER BY id ASC").df()
        st.dataframe(df_p, use_container_width=True, hide_index=True)
        
        ca, cb, cc = st.columns(3)
        with ca:
            with st.expander("➕ Tambah Produk"):
                with st.form("add_p"):
                    n = st.text_input("Nama")
                    k = st.selectbox("Kategori", ["Makanan", "Minuman", "Lainnya"])
                    o = st.text_input("Opsi (pisahkan koma)", help="Dingin, Panas")
                    h = st.number_input("Harga", step=500)
                    s = st.number_input("Stok", step=1)
                    if st.form_submit_button("Simpan"):
                        new_id = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM produk").fetchone()[0]
                        con.execute("INSERT INTO produk VALUES (?,?,?,?,?,?)", [new_id, n, k, float(h), int(s), o])
                        st.rerun()
        with cb:
            with st.expander("📝 Edit Harga & Stok"):
                if not df_p.empty:
                    with st.form("edit_p"):
                        pk = st.selectbox("Pilih Produk", df_p['nama_produk'])
                        row = df_p[df_p['nama_produk'] == pk].iloc[0]
                        new_h = st.number_input("Harga Baru", value=int(row['harga']))
                        add_s = st.number_input("Tambah/Kurang Stok", value=0)
                        if st.form_submit_button("Update"):
                            con.execute("UPDATE produk SET harga=?, stok=stok+? WHERE id=?", [new_h, add_s, int(row['id'])])
                            st.rerun()
        with cc:
            with st.expander("🗑️ Hapus"):
                if not df_p.empty:
                    pk_del = st.selectbox("Hapus Produk", df_p['nama_produk'], key="del_p")
                    if st.button("Hapus Permanen", type="primary"):
                        con.execute("DELETE FROM produk WHERE nama_produk=?", [pk_del])
                        st.rerun()

    elif menu == "Bahan Baku (Label)":
        st.subheader("🧪 Manajemen Bahan Baku & Label")
        tab1, tab2 = st.tabs(["Stok Bahan Baku", "Ikatan Produk (BOM)"])
        
        with tab1:
            df_l = con.execute("SELECT * FROM label_stok").df()
            st.dataframe(df_l, use_container_width=True, hide_index=True)
            with st.form("add_label"):
                c1, c2, c3 = st.columns(3)
                nl = c1.text_input("Nama Bahan (Cup/Sedotan)")
                sl = c2.number_input("Stok Awal", min_value=0)
                sat = c3.text_input("Satuan", value="pcs")
                if st.form_submit_button("Tambah Bahan Baku"):
                    lid = con.execute("SELECT COALESCE(MAX(id_label),0)+1 FROM label_stok").fetchone()[0]
                    con.execute("INSERT INTO label_stok VALUES (?,?,?,?)", [lid, nl, int(sl), sat])
                    st.rerun()
        
        with tab2:
            st.caption("Hubungkan Produk dengan Bahan Baku agar stok berkurang otomatis.")
            df_link = con.execute("""
                SELECT p.nama_produk, l.nama_label, pl.jumlah_pemakaian 
                FROM produk_label pl 
                JOIN produk p ON pl.id_produk = p.id 
                JOIN label_stok l ON pl.id_label = l.id_label
            """).df()
            st.table(df_link)
            
            with st.form("link_label"):
                df_p = con.execute("SELECT id, nama_produk FROM produk").df()
                df_l = con.execute("SELECT id_label, nama_label FROM label_stok").df()
                sel_p = st.selectbox("Pilih Produk", df_p['nama_produk'])
                sel_l = st.selectbox("Pilih Bahan Baku", df_l['nama_label'])
                jml = st.number_input("Jumlah per pemakaian", min_value=1, value=1)
                if st.form_submit_button("Ikat Bahan ke Produk"):
                    id_p = int(df_p[df_p['nama_produk'] == sel_p]['id'].iloc[0])
                    id_l = int(df_l[df_l['nama_label'] == sel_l]['id_label'].iloc[0])
                    con.execute("INSERT OR REPLACE INTO produk_label VALUES (?,?,?)", [id_p, id_l, jml])
                    st.rerun()

    elif menu == "Data Transaksi":
        st.subheader("📝 Histori Transaksi")
        st.dataframe(con.execute("SELECT * FROM transaksi ORDER BY waktu DESC").df(), use_container_width=True)

# --- LOGIKA UTAMA ---
if "logged_in" not in st.session_state:
    login_ui()
else:
    st.sidebar.write(f"**{st.session_state.username}** ({st.session_state.role})")
    if st.sidebar.button("Logout"):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()
    if st.session_state.role == "admin": admin_ui()
    else: cashier_ui()