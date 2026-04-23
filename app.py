import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px
from datetime import datetime

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sistem Kasir Pro v2.8", layout="wide")

# --- KONEKSI DATABASE ---
@st.cache_resource
def get_connection():
    TOKEN = st.secrets["MOTHERDUCK_TOKEN"]
    return duckdb.connect(f"md:tes_db?motherduck_token={TOKEN}")

con = get_connection()

# --- LOGIKA SINKRONISASI KUMULATIF ---
def sync_cumulative_label(opsi_string, delta_stok):
    """
    Mengupdate stok label secara akumulatif. 
    Jika delta_stok positif (restock) atau negatif (penjualan/koreksi), 
    semua label yang disebutkan dalam opsi_string akan ikut terupdate.
    """
    if opsi_string and str(opsi_string) != "None" and delta_stok != 0:
        # Pecah opsi menjadi list dan bersihkan spasi
        list_opsi = [item.strip() for item in opsi_string.split(",")]
        
        for item in list_opsi:
            if item == "": continue
            
            # Cek keberadaan label (Case-Insensitive)
            exist = con.execute("SELECT id_label FROM label_stok WHERE LOWER(nama_label) = LOWER(?)", [item]).fetchone()
            
            if exist:
                # Update stok label yang sudah ada (Akumulasi)
                con.execute("UPDATE label_stok SET stok = stok + ? WHERE LOWER(nama_label) = LOWER(?)", 
                            [int(delta_stok), item.lower()])
            else:
                # Jika label baru pertama kali muncul, buat baris baru
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

    df_produk = con.execute("SELECT * FROM produk").df()
    col_input, col_cart = st.columns([1, 2])

    with col_input:
        st.subheader("Input Pesanan")
        list_kat = ["Semua"] + list(df_produk['kategori'].unique())
        f_kat = st.selectbox("Filter", list_kat)
        df_display = df_produk if f_kat == "Semua" else df_produk[df_produk['kategori'] == f_kat]

        with st.form("form_cart", clear_on_submit=True):
            if not df_display.empty:
                item_p = st.selectbox("Produk", df_display['nama_produk']) 
                qty_p = st.number_input("Qty", min_value=1, step=1)
                row = df_produk[df_produk['nama_produk'] == item_p].iloc[0]
                
                p_opsi = ""
                if row['opsi'] and str(row['opsi']) != "None":
                    opts = [o.strip() for o in str(row['opsi']).split(",")]
                    p_user = st.multiselect("Opsi:", opts)
                    p_opsi = ", ".join(p_user)

                if st.form_submit_button("➕ Tambah"):
                    if int(row['stok']) >= qty_p:
                        st.session_state.cart.append({
                            "id": int(row['id']), "nama": item_p, "qty": int(qty_p),
                            "harga": float(row['harga']), "subtotal": float(row['harga'] * qty_p),
                            "opsi": p_opsi
                        })
                        st.rerun()
                    else: st.error("Stok Habis!")

    with col_cart:
        st.subheader("Keranjang")
        if st.session_state.cart:
            total = sum(i['subtotal'] for i in st.session_state.cart)
            for i, b in enumerate(st.session_state.cart):
                c1, c2, c3 = st.columns([3, 2, 1])
                c1.write(f"**{b['nama']}** \n*({b['opsi']})*")
                c2.write(f"Rp{b['subtotal']:,.0f}")
                if c3.button("🗑️", key=f"del_{i}"):
                    st.session_state.cart.pop(i)
                    st.rerun()
            
            st.divider()
            if st.button("✅ PROSES TRANSAKSI", use_container_width=True):
                id_tx = datetime.now().strftime("%Y%m%d%H%M%S")
                waktu = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for b in st.session_state.cart:
                    # Potong stok produk & stok label (Negatif delta)
                    con.execute("UPDATE produk SET stok = stok - ? WHERE id = ?", [b['qty'], b['id']])
                    if b['opsi']:
                        sync_cumulative_label(b['opsi'], -b['qty'])
                    
                    con.execute("INSERT INTO transaksi VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                [id_tx, b['nama'], b['qty'], b['subtotal'], st.session_state.username, waktu, b['opsi']])
                st.success("Berhasil!")
                st.session_state.cart = []
                st.rerun()

# --- HALAMAN ADMIN ---
def admin_ui():
    st.title("🏗️ Panel Admin")
    menu = st.sidebar.selectbox("Menu", ["Dashboard", "Produk", "Label/Bahan Baku", "Transaksi"])
    
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

    elif menu == "Produk":
        st.subheader("📦 Manajemen Stok Produk")
        df_p = con.execute("SELECT * FROM produk ORDER BY id ASC").df()
        st.dataframe(df_p, use_container_width=True, hide_index=True)
        
        ca, cb = st.columns(2)
        with ca:
            with st.expander("➕ Tambah Produk"):
                with st.form("add_p", clear_on_submit=True):
                    n = st.text_input("Nama").strip()
                    o = st.text_input("Opsi (Pisah koma)")
                    h = st.number_input("Harga", step=500)
                    s = st.number_input("Stok Awal", min_value=0)
                    if st.form_submit_button("Simpan"):
                        check = con.execute("SELECT id FROM produk WHERE LOWER(nama_produk)=LOWER(?)", [n]).fetchone()
                        if not check:
                            nid = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM produk").fetchone()[0]
                            con.execute("INSERT INTO produk VALUES (?,?,?,?,?,?)", [nid, n, "Minuman", h, s, o])
                            # SINKRONISASI POSITIF (Restock Label)
                            sync_cumulative_label(o, s)
                            st.rerun()
                        else: st.error("Produk sudah ada!")
        with cb:
            with st.expander("🔄 Update Stok"):
                if not df_p.empty:
                    with st.form("up_p"):
                        sel = st.selectbox("Produk", df_p['nama_produk'])
                        r = df_p[df_p['nama_produk'] == sel].iloc[0]
                        ns = st.number_input("Tambah Stok (+/-)", value=0)
                        if st.form_submit_button("Update"):
                            con.execute("UPDATE produk SET stok=stok+? WHERE id=?", [ns, int(r['id'])])
                            # SINKRONISASI POSITIF/NEGATIF
                            sync_cumulative_label(r['opsi'], ns)
                            st.rerun()

    elif menu == "Label/Bahan Baku":
        st.subheader("🧪 Stok Label (Akumulasi Otomatis)")
        df_l = con.execute("SELECT * FROM label_stok ORDER BY id_label ASC").df()
        st.dataframe(df_l, use_container_width=True, hide_index=True)
        
        with st.expander("🔄 Koreksi Anomali (Manual)"):
            with st.form("kor_l"):
                sel_l = st.selectbox("Pilih Label", df_l['nama_label'] if not df_l.empty else ["Kosong"])
                delta = st.number_input("Koreksi (+/-)", value=0)
                if st.form_submit_button("Simpan"):
                    con.execute("UPDATE label_stok SET stok=stok+? WHERE nama_label=?", [delta, sel_l])
                    st.rerun()

    elif menu == "Transaksi":
        st.subheader("📝 Histori")
        st.dataframe(con.execute("SELECT * FROM transaksi ORDER BY waktu DESC").df(), use_container_width=True)

# --- LOGIKA UTAMA ---
if "logged_in" not in st.session_state:
    login_ui()
else:
    st.sidebar.write(f"Logged in: **{st.session_state.username}**")
    if st.sidebar.button("Logout"):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()
    if st.session_state.role == "admin": admin_ui()
    else: cashier_ui()