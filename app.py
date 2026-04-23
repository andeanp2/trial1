import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px
from datetime import datetime

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sistem Kasir Pro v3.2", layout="wide")

# --- KONEKSI DATABASE ---
@st.cache_resource
def get_connection():
    TOKEN = st.secrets["MOTHERDUCK_TOKEN"]
    return duckdb.connect(f"md:tes_db?motherduck_token={TOKEN}")

con = get_connection()

# --- LOGIKA SINKRONISASI KUMULATIF ---
def sync_cumulative_label(opsi_string, delta_stok):
    if opsi_string and str(opsi_string) != "None" and delta_stok != 0:
        list_opsi = [item.strip() for item in opsi_string.split(",")]
        for item in list_opsi:
            if item == "": continue
            exist = con.execute("SELECT id_label FROM label_stok WHERE LOWER(nama_label) = LOWER(?)", [item]).fetchone()
            if exist:
                con.execute("UPDATE label_stok SET stok = stok + ? WHERE LOWER(nama_label) = LOWER(?)", 
                            [int(delta_stok), item.lower()])
            else:
                new_lid = con.execute("SELECT COALESCE(MAX(id_label), 0) + 1 FROM label_stok").fetchone()[0]
                con.execute("INSERT INTO label_stok (id_label, nama_label, stok, satuan) VALUES (?, ?, ?, ?)", 
                            [int(new_lid), item, int(delta_stok), 'pcs'])

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
    if "last_tx" not in st.session_state: st.session_state.last_tx = None

    df_produk = con.execute("SELECT * FROM produk").df()
    col_input, col_cart = st.columns([1, 2])

    with col_input:
        st.subheader("Input Pesanan")
        list_kat = ["Semua"] + list(df_produk['kategori'].unique())
        f_kat = st.selectbox("Filter Kategori", list_kat)
        df_display = df_produk if f_kat == "Semua" else df_produk[df_produk['kategori'] == f_kat]

        with st.form("form_cart", clear_on_submit=True):
            if not df_display.empty:
                item_p = st.selectbox("Pilih Produk", df_display['nama_produk']) 
                qty_p = st.number_input("Jumlah", min_value=1, step=1)
                row = df_produk[df_produk['nama_produk'] == item_p].iloc[0]
                
                p_opsi = ""
                if row['opsi'] and str(row['opsi']) != "None":
                    opts = [o.strip() for o in str(row['opsi']).split(",")]
                    p_user = st.multiselect("Opsi Tambahan:", opts)
                    p_opsi = ", ".join(p_user)

                if st.form_submit_button("➕ Tambah ke Keranjang"):
                    st.session_state.last_tx = None 
                    if int(row['stok']) >= qty_p:
                        st.session_state.cart.append({
                            "id": int(row['id']), 
                            "nama": item_p, 
                            "qty": int(qty_p),
                            "harga": float(row['harga']), 
                            "subtotal": float(row['harga'] * qty_p),
                            "opsi": p_opsi
                        })
                        st.rerun()
                    else:
                        st.error("Stok Produk Tidak Mencukupi!")

    with col_cart:
        # --- TAMPILAN 1: DETAIL TRANSAKSI TERAKHIR ---
        if st.session_state.last_tx and not st.session_state.cart:
            st.success(f"✅ Transaksi Berhasil! (ID: {st.session_state.last_tx['id_tx']})")
            st.subheader("📄 Struk Terakhir")
            
            df_last = pd.DataFrame(st.session_state.last_tx['items'])
            # PERBAIKAN FORMAT: Mengubah angka menjadi string berformat rupiah
            df_last['subtotal'] = df_last['subtotal'].map("Rp{:,.0f}".format)
            
            st.table(df_last[['nama', 'opsi', 'qty', 'subtotal']].rename(columns={
                'nama': 'Produk', 'opsi': 'Label/Opsi', 'qty': 'Jumlah', 'subtotal': 'Total'
            }))
            st.write(f"### TOTAL BAYAR: Rp{st.session_state.last_tx['total']:,.0f}")
            
            if st.button("🆕 Lanjut Transaksi Berikutnya", type="primary"):
                st.session_state.last_tx = None
                st.rerun()

        # --- TAMPILAN 2: KERANJANG AKTIF ---
        elif st.session_state.cart:
            st.subheader("🛒 Keranjang Belanja")
            total_bayar = sum(i['subtotal'] for i in st.session_state.cart)
            
            df_cart = pd.DataFrame(st.session_state.cart)
            # PERBAIKAN FORMAT: Agar tidak muncul 5.000.0000
            df_cart_display = df_cart.copy()
            df_cart_display['subtotal'] = df_cart_display['subtotal'].map("Rp{:,.0f}".format)
            
            st.table(df_cart_display[['nama', 'opsi', 'qty', 'subtotal']].rename(columns={
                'nama': 'Produk', 'opsi': 'Label/Opsi', 'qty': 'Jumlah', 'subtotal': 'Total'
            }))
            st.write(f"### ESTIMASI TOTAL: Rp{total_bayar:,.0f}")
            
            c_btn1, c_btn2 = st.columns(2)
            if c_btn1.button("🧹 Kosongkan", use_container_width=True):
                st.session_state.cart = []
                st.rerun()
            if c_btn2.button("✅ SELESAIKAN", type="primary", use_container_width=True):
                id_tx = datetime.now().strftime("%Y%m%d%H%M%S")
                waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                st.session_state.last_tx = {"id_tx": id_tx, "items": list(st.session_state.cart), "total": total_bayar}
                
                for b in st.session_state.cart:
                    con.execute("UPDATE produk SET stok = stok - ? WHERE id = ?", [b['qty'], b['id']])
                    if b['opsi']: sync_cumulative_label(b['opsi'], -b['qty'])
                    con.execute("INSERT INTO transaksi VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                [id_tx, b['nama'], b['qty'], b['subtotal'], st.session_state.username, waktu, b['opsi']])
                st.session_state.cart = []
                st.rerun()
        else:
            st.info("Sistem siap melayani.")

# --- HALAMAN ADMIN (Sama seperti sebelumnya) ---
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
            st.plotly_chart(px.bar(df_tx, x='waktu', y='total_harga', color='nama_produk'), use_container_width=True)

    elif menu == "Manajemen Produk":
        st.subheader("📦 Inventori Produk")
        df_p = con.execute("SELECT * FROM produk ORDER BY id ASC").df()
        st.dataframe(df_p, use_container_width=True, hide_index=True)
        ca, cb, cc = st.columns(3)
        with ca:
            with st.expander("➕ Tambah"):
                with st.form("add_p", clear_on_submit=True):
                    n = st.text_input("Nama").strip()
                    k = st.selectbox("Kategori", ["Makanan", "Minuman", "Lainnya"])
                    o = st.text_input("Opsi (Pisah koma)")
                    h = st.number_input("Harga", step=500)
                    s = st.number_input("Stok", step=1)
                    if st.form_submit_button("Simpan"):
                        check = con.execute("SELECT id FROM produk WHERE LOWER(nama_produk)=LOWER(?)", [n]).fetchone()
                        if not check:
                            nid = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM produk").fetchone()[0]
                            con.execute("INSERT INTO produk VALUES (?,?,?,?,?,?)", [nid, n, k, h, s, o])
                            sync_cumulative_label(o, s)
                            st.rerun()
                        else: st.error("Eksis!")
        with cb:
            with st.expander("🔄 Update"):
                if not df_p.empty:
                    with st.form("up_p"):
                        sel = st.selectbox("Pilih", df_p['nama_produk'])
                        r = df_p[df_p['nama_produk'] == sel].iloc[0]
                        nh = st.number_input("Harga", value=int(r['harga']))
                        ns = st.number_input("Tambah Stok", value=0)
                        no = st.text_input("Opsi", value=str(r['opsi']))
                        if st.form_submit_button("Update"):
                            con.execute("UPDATE produk SET harga=?, stok=stok+?, opsi=? WHERE id=?", [nh, ns, no, int(r['id'])])
                            sync_cumulative_label(no, ns)
                            st.rerun()
        with cc:
            with st.expander("🗑️ Hapus"):
                if not df_p.empty:
                    sel_del = st.selectbox("Hapus", df_p['nama_produk'], key="del_p")
                    if st.button("Hapus", type="primary"):
                        con.execute("DELETE FROM produk WHERE nama_produk=?", [sel_del])
                        st.rerun()

    elif menu == "Manajemen Label":
        st.subheader("🧪 Inventori Label")
        df_l = con.execute("SELECT * FROM label_stok ORDER BY id_label ASC").df()
        st.dataframe(df_l, use_container_width=True, hide_index=True)
        c1, c2, c3 = st.columns(3)
        with c1:
            with st.expander("➕ Tambah"):
                with st.form("add_l", clear_on_submit=True):
                    nl = st.text_input("Nama").strip()
                    sl = st.number_input("Stok", min_value=0)
                    sat = st.text_input("Satuan", value="pcs")
                    if st.form_submit_button("Simpan"):
                        lid = con.execute("SELECT COALESCE(MAX(id_label),0)+1 FROM label_stok").fetchone()[0]
                        con.execute("INSERT INTO label_stok VALUES (?,?,?,?)", [lid, nl, sl, sat])
                        st.rerun()
        with c2:
            with st.expander("🔄 Update"):
                if not df_l.empty:
                    with st.form("up_l"):
                        sel_l = st.selectbox("Pilih", df_l['nama_label'])
                        rl = df_l[df_l['nama_label'] == sel_l].iloc[0]
                        asl = st.number_input("Koreksi Stok", value=0)