import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta, timezone

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sistem Kasir Pro v1.3", layout="wide")

# --- 2. KONEKSI DATABASE ---
@st.cache_resource
def get_connection():
    try:
        if "MOTHERDUCK_TOKEN" not in st.secrets:
            st.error("Missing MOTHERDUCK_TOKEN in secrets!")
            st.stop()
        TOKEN = st.secrets["MOTHERDUCK_TOKEN"]
        # Langsung konek ke MotherDuck (Tabel diasumsikan sudah ada)
        return duckdb.connect(f"md:tes_db?motherduck_token={TOKEN}")
    except Exception as e:
        st.error(f"Gagal koneksi ke MotherDuck: {e}")
        st.stop()

con = get_connection()

# --- 3. LOGIKA HELPER ---
WIB = timezone(timedelta(hours=7))

def get_now_wib():
    return datetime.now(timezone.utc).astimezone(WIB)

# --- 4. UI COMPONENTS ---

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

def cashier_ui():
    st.header(f"🛒 Kasir: {st.session_state.username}")
    
    if "cart" not in st.session_state: st.session_state.cart = []

    try:
        df_produk = con.execute("SELECT * FROM produk").df()
    except:
        st.warning("Tabel produk belum siap.")
        return

    col_input, col_cart = st.columns([1, 2])

    with col_input:
        st.subheader("Input Pesanan")
        list_kat = ["Semua"] + sorted(list(df_produk['kategori'].unique())) if not df_produk.empty else ["Semua"]
        f_kat = st.selectbox("Filter Kategori", list_kat)
        df_filtered = df_produk if f_kat == "Semua" else df_produk[df_produk['kategori'] == f_kat]

        with st.form("form_cart", clear_on_submit=True):
            if not df_filtered.empty:
                item_p_name = st.selectbox("Pilih Produk", sorted(df_filtered['nama_produk'].unique()))
                
                selected_item_data = df_filtered[df_filtered['nama_produk'] == item_p_name].iloc[0]
                p_category = selected_item_data['kategori']
                p_id = selected_item_data['id']
                p_harga = selected_item_data['harga']
                p_stok = selected_item_data['stok']
                
                df_labels = con.execute("SELECT nama_label FROM master_label WHERE kategori = ?", [p_category]).df()
                available_labels = sorted(df_labels['nama_label'].tolist()) if not df_labels.empty else []
                
                p_user_selection = st.multiselect(f"Opsi Tambahan ({p_category}):", available_labels)
                qty_p = st.number_input("Jumlah", min_value=1, step=1)

                if st.form_submit_button("➕ Tambah"):
                    if p_stok >= qty_p:
                        st.session_state.cart.append({
                            "id": int(p_id), "nama": item_p_name, "qty": int(qty_p),
                            "harga": float(p_harga), "subtotal": float(p_harga * qty_p),
                            "opsi": ", ".join(p_user_selection)
                        })
                        st.rerun()
                    else:
                        st.error(f"Stok tidak mencukupi! Sisa: {p_stok}")

    with col_cart:
        if st.session_state.cart:
            st.subheader("🛒 Keranjang")
            df_cart = pd.DataFrame(st.session_state.cart)
            total = sum(i['subtotal'] for i in st.session_state.cart)
            st.table(df_cart[['nama', 'opsi', 'qty', 'subtotal']])
            st.write(f"### TOTAL: Rp{total:,.0f}")
            if st.button("✅ SELESAIKAN", type="primary", use_container_width=True):
                id_tx = get_now_wib().strftime("%Y%m%d%H%M%S")
                for b in st.session_state.cart:
                    con.execute("UPDATE produk SET stok = stok - ? WHERE id = ?", [b['qty'], b['id']])
                    con.execute("INSERT INTO transaksi VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                [id_tx, b['nama'], b['qty'], b['subtotal'], st.session_state.username, get_now_wib().replace(tzinfo=None), b['opsi']])
                st.session_state.cart = []
                st.success("Transaksi Berhasil!")
                st.rerun()

def admin_ui():
    st.title("🏗️ Panel Admin v1.3")
    menu = st.sidebar.selectbox("Menu", ["Dashboard", "Produk", "Kelola Label", "Transaksi"])
    
    if menu == "Kelola Label":
        st.subheader("🏷️ Master Label")
        df_l = con.execute("SELECT * FROM master_label ORDER BY kategori, nama_label").df()
        st.dataframe(df_l, use_container_width=True, hide_index=True)

        t_l1, t_l2, t_l3 = st.tabs(["➕ Tambah", "✏️ Edit", "🗑️ Hapus"])
        with t_l1:
            with st.form("add_label"):
                nl = st.text_input("Nama Label")
                kl = st.selectbox("Kategori", ["Minuman", "Makanan", "Snack"])
                if st.form_submit_button("Simpan"):
                    new_id = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM master_label").fetchone()[0]
                    con.execute("INSERT INTO master_label VALUES (?,?,?)", [new_id, nl, kl])
                    st.rerun()
        
        with t_l2:
            if not df_l.empty:
                edit_l_id = st.selectbox("Pilih Label", df_l['id'].tolist(), format_func=lambda x: f"{df_l[df_l['id']==x]['nama_label'].values[0]} ({df_l[df_l['id']==x]['kategori'].values[0]})")
                old_data = df_l[df_l['id'] == edit_l_id].iloc[0]
                with st.form("edit_label_form"):
                    new_nl = st.text_input("Nama Label", value=old_data['nama_label'])
                    new_kl = st.selectbox("Kategori", ["Minuman", "Makanan", "Snack"], index=["Minuman", "Makanan", "Snack"].index(old_data['kategori']))
                    if st.form_submit_button("Update"):
                        con.execute("UPDATE master_label SET nama_label=?, kategori=? WHERE id=?", [new_nl, new_kl, edit_l_id])
                        st.rerun()

        with t_l3:
            if not df_l.empty:
                del_l_id = st.selectbox("Pilih ID Label Hapus", df_l['id'].tolist())
                if st.button("🔥 Hapus"):
                    con.execute("DELETE FROM master_label WHERE id=?", [del_l_id])
                    st.rerun()

    elif menu == "Produk":
        st.subheader("📦 Daftar Produk")
        df_p = con.execute("SELECT id, nama_produk, kategori, harga, stok FROM produk ORDER BY id DESC").df()
        st.dataframe(df_p, use_container_width=True, hide_index=True)

        t1, t2, t3, t4 = st.tabs(["➕ Tambah Produk", "✏️ Edit Produk", "📦 Update Stok", "🗑️ Hapus"])
        
        with t1:
            with st.form("f_add", clear_on_submit=True):
                n = st.text_input("Nama Produk")
                k = st.selectbox("Kategori", ["Minuman", "Makanan", "Snack"])
                h = st.number_input("Harga", min_value=0, step=500)
                s = st.number_input("Stok Awal", min_value=0)
                if st.form_submit_button("Simpan Produk"):
                    nid = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM produk").fetchone()[0]
                    con.execute("INSERT INTO produk VALUES (?,?,?,?,?,?)", [nid, n, k, h, s, ""])
                    st.rerun()
        
        with t2:
            if not df_p.empty:
                target_p_name = st.selectbox("Pilih Nama Produk (Edit)", df_p['nama_produk'].tolist())
                curr = df_p[df_p['nama_produk'] == target_p_name].iloc[0]
                with st.form("f_edit"):
                    en = st.text_input("Nama Baru", value=curr['nama_produk'])
                    ek = st.selectbox("Kategori", ["Minuman", "Makanan", "Snack"], index=["Minuman", "Makanan", "Snack"].index(curr['kategori']))
                    eh = st.number_input("Harga", value=float(curr['harga']))
                    if st.form_submit_button("Update Data"):
                        con.execute("UPDATE produk SET nama_produk=?, kategori=?, harga=? WHERE id=?", [en, ek, eh, int(curr['id'])])
                        st.rerun()

        # --- UPDATE STOK BERDASARKAN NAMA ---
        with t3:
            if not df_p.empty:
                nama_stok = st.selectbox("Pilih Nama Produk untuk Update Stok", sorted(df_p['nama_produk'].tolist()))
                curr_s = df_p[df_p['nama_produk'] == nama_stok]['stok'].values[0]
                st.info(f"Stok saat ini untuk **{nama_stok}**: {curr_s}")
                
                ns = st.number_input("Set Stok Baru", min_value=0, value=int(curr_s))
                if st.button("Simpan Perubahan Stok"):
                    con.execute("UPDATE produk SET stok=? WHERE nama_produk=?", [ns, nama_stok])
                    st.success(f"Stok {nama_stok} diperbarui menjadi {ns}")
                    st.rerun()
        
        with t4:
            if not df_p.empty:
                del_name = st.selectbox("Nama Produk untuk Hapus", df_p['nama_produk'].tolist())
                if st.button("🔥 Hapus Permanen"):
                    con.execute("DELETE FROM produk WHERE nama_produk=?", [del_name])
                    st.rerun()

    elif menu == "Dashboard":
        res_h = con.execute("SELECT SUM(total_harga) FROM transaksi WHERE CAST(waktu AS DATE) = ?", [get_now_wib().strftime('%Y-%m-%d')]).fetchone()
        st.metric("Omset Hari Ini", f"Rp{res_h[0] if res_h[0] else 0:,.0f}")
        df_tx = con.execute("SELECT * FROM transaksi").df()
        if not df_tx.empty:
            st.plotly_chart(px.bar(df_tx, x='waktu', y='total_harga', title="Penjualan"))

    elif menu == "Transaksi":
        df_tx = con.execute("SELECT * FROM transaksi ORDER BY waktu DESC").df()
        st.dataframe(df_tx, use_container_width=True)

# --- 5. LOGIKA UTAMA ---
if "logged_in" not in st.session_state:
    login_ui()
else:
    st.sidebar.write(f"User: **{st.session_state.username}**")
    if st.sidebar.button("Logout"):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()
    
    if st.session_state.role == "admin": admin_ui()
    else: cashier_ui()