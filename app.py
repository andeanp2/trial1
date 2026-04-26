import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta, timezone

# =================================================================
# VERSI: 1.8 - FINAL STABLE BASELINE (VERIFIED)
# FITUR: Perbaikan Absolut Input Stok (Direct Variable Capture)
# =================================================================

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sistem Kasir Pro v1.8 - Stable", layout="wide")

# --- 2. KONEKSI DATABASE ---
@st.cache_resource
def get_connection():
    try:
        if "MOTHERDUCK_TOKEN" not in st.secrets:
            st.error("Missing MOTHERDUCK_TOKEN in secrets!")
            st.stop()
        TOKEN = st.secrets["MOTHERDUCK_TOKEN"]
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
        df_produk = con.execute("SELECT id, nama_produk, kategori, harga, stok FROM produk").df()
    except:
        st.warning("Tabel produk belum siap."); return

    col_input, col_cart = st.columns([1, 2])

    with col_input:
        st.subheader("Input Pesanan")
        list_kat = ["Semua"] + sorted(list(df_produk['kategori'].unique())) if not df_produk.empty else ["Semua"]
        f_kat = st.selectbox("Filter Kategori", list_kat)
        df_filtered = df_produk if f_kat == "Semua" else df_produk[df_produk['kategori'] == f_kat]

        with st.form("form_cart"):
            if not df_filtered.empty:
                item_p_name = st.selectbox("Pilih Produk", sorted(df_filtered['nama_produk'].unique()))
                selected_item_data = df_filtered[df_filtered['nama_produk'] == item_p_name].iloc[0]
                p_category = selected_item_data['kategori']
                p_id = selected_item_data['id']
                p_harga_base = float(selected_item_data['harga'])
                p_stok_prod = selected_item_data['stok']
                
                df_addons = con.execute("SELECT nama_label, harga, stok FROM master_label WHERE kategori = ?", [p_category]).df()
                addon_options = []
                addon_data_map = {}
                if not df_addons.empty:
                    for _, row in df_addons.iterrows():
                        label_display = f"{row['nama_label']} (+Rp{row['harga']:,.0f}) [Sisa: {row['stok']}]"
                        addon_options.append(label_display)
                        addon_data_map[label_display] = {"nama": row['nama_label'], "harga": float(row['harga']), "stok": int(row['stok'])}
                
                selected_addons_display = st.multiselect(f"Pilih Add On ({p_category}):", addon_options)
                qty_p_in = st.number_input("Jumlah", min_value=1, step=1)

                if st.form_submit_button("➕ Tambah"):
                    if p_stok_prod < qty_p_in:
                        st.error(f"Stok Produk '{item_p_name}' sisa {p_stok_prod}!"); return
                    
                    total_addon_price = 0
                    clean_addons_list = []
                    for ad_disp in selected_addons_display:
                        ad_info = addon_data_map[ad_disp]
                        if ad_info['stok'] < qty_p_in:
                            st.error(f"Stok Add On '{ad_info['nama']}' tidak cukup!"); return
                        total_addon_price += ad_info['harga']
                        clean_addons_list.append(ad_info['nama'])

                    st.session_state.cart.append({
                        "id": int(p_id), "nama": item_p_name, "qty": int(qty_p_in),
                        "harga_satuan": p_harga_base + total_addon_price, 
                        "subtotal": (p_harga_base + total_addon_price) * qty_p_in,
                        "opsi_list": clean_addons_list, "opsi_txt": ", ".join(clean_addons_list)
                    })
                    st.rerun()

    with col_cart:
        if st.session_state.cart:
            st.subheader("🛒 Keranjang")
            df_cart = pd.DataFrame(st.session_state.cart)
            total = sum(i['subtotal'] for i in st.session_state.cart)
            st.table(df_cart[['nama', 'opsi_txt', 'qty', 'subtotal']])
            st.write(f"### TOTAL BAYAR: Rp{total:,.0f}")
            if st.button("✅ SELESAIKAN", type="primary", use_container_width=True):
                id_tx = get_now_wib().strftime("%Y%m%d%H%M%S")
                for b in st.session_state.cart:
                    con.execute("UPDATE produk SET stok = stok - ? WHERE id = ?", [int(b['qty']), int(b['id'])])
                    for addon_name in b['opsi_list']:
                        con.execute("UPDATE master_label SET stok = stok - ? WHERE nama_label = ?", [int(b['qty']), addon_name])
                    con.execute("""
                        INSERT INTO transaksi (id_transaksi, nama_produk, qty, total_harga, kasir, waktu, opsi_detail) 
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, [id_tx, b['nama'], int(b['qty']), float(b['subtotal']), st.session_state.username, get_now_wib().replace(tzinfo=None), b['opsi_txt']])
                st.session_state.cart = []
                st.rerun()

def admin_ui():
    st.title("🏗️ Panel Admin v1.8")
    menu = st.sidebar.selectbox("Menu", ["Dashboard", "Produk", "Add On", "Transaksi"])
    list_kategori = ["Minuman", "Makanan", "Fashion"]

    # --- 1. MENU PRODUK ---
    if menu == "Produk":
        st.subheader("📦 Manajemen Produk")
        df_p = con.execute("SELECT id, nama_produk, kategori, harga, stok FROM produk ORDER BY id DESC").df()
        st.dataframe(df_p, use_container_width=True, hide_index=True)

        t1, t2, t3, t4 = st.tabs(["➕ Tambah", "✏️ Edit", "📦 Stok", "🗑️ Hapus"])
        
        with t1:
            with st.form("form_add_produk_final", clear_on_submit=False):
                # Langsung tangkap ke variabel lokal
                n_in = st.text_input("Nama Produk")
                k_in = st.selectbox("Kategori", list_kategori)
                h_in = st.number_input("Harga", min_value=0, step=500)
                s_in = st.number_input("Stok Awal", min_value=0, step=1)
                
                if st.form_submit_button("Simpan Produk"):
                    if not n_in.strip(): st.error("Nama tidak boleh kosong!"); return
                    
                    is_dup = con.execute("SELECT COUNT(*) FROM produk WHERE LOWER(TRIM(nama_produk)) = LOWER(?)", [n_in.strip()]).fetchone()[0]
                    if is_dup > 0:
                        st.error(f"Gagal! Produk '{n_in.strip()}' sudah ada."); return
                    
                    nid = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM produk").fetchone()[0]
                    
                    # Eksekusi dengan variabel lokal dan casting eksplisit
                    con.execute("""
                        INSERT INTO produk (id, nama_produk, kategori, harga, stok) 
                        VALUES (?, ?, ?, ?, ?)
                    """, [int(nid), n_in.strip(), k_in, float(h_in), int(s_in)])
                    
                    st.success(f"Berhasil simpan {n_in} dengan stok {int(s_in)}!")
                    st.rerun()
        
        with t2:
            if not df_p.empty:
                p_target_id = st.selectbox("Pilih Produk (Edit)", df_p['id'].tolist(), format_func=lambda x: df_p[df_p['id']==x]['nama_produk'].values[0])
                curr = df_p[df_p['id'] == p_target_id].iloc[0]
                with st.form("f_edit_p"):
                    en_val = st.text_input("Nama Baru", value=curr['nama_produk'])
                    ek_val = st.selectbox("Kategori", list_kategori, index=list_kategori.index(curr['kategori']))
                    eh_val = st.number_input("Harga", value=float(curr['harga']))
                    if st.form_submit_button("Update Data"):
                        con.execute("UPDATE produk SET nama_produk=?, kategori=?, harga=? WHERE id=?", [en_val.strip(), ek_val, float(eh_val), int(p_target_id)])
                        st.success("Produk diperbarui!"); st.rerun()

        with t3:
            if not df_p.empty:
                p_stok_id = st.selectbox("Pilih Produk (Stok)", df_p['id'].tolist(), format_func=lambda x: f"{df_p[df_p['id']==x]['nama_produk'].values[0]}")
                curr_s = df_p[df_p['id'] == p_stok_id]['stok'].values[0]
                with st.form("f_upd_stok_p"):
                    ns_in = st.number_input("Set Stok Baru", min_value=0, value=int(curr_s), step=1)
                    if st.form_submit_button("Update Stok"):
                        con.execute("UPDATE produk SET stok=? WHERE id=?", [int(ns_in), int(p_stok_id)])
                        st.success("Stok diperbarui!"); st.rerun()

        with t4:
            if not df_p.empty:
                p_del_id = st.selectbox("Pilih Produk (Hapus)", df_p['id'].tolist(), format_func=lambda x: df_p[df_p['id']==x]['nama_produk'].values[0])
                if st.button("🔥 Hapus Produk Permanen"):
                    con.execute("DELETE FROM produk WHERE id=?", [int(p_del_id)])
                    st.success("Produk dihapus!"); st.rerun()

    # --- 2. MENU ADD ON ---
    elif menu == "Add On":
        st.subheader("🧩 Manajemen Add On")
        df_l = con.execute("SELECT id, nama_label, kategori, harga, stok FROM master_label ORDER BY kategori, nama_label").df()
        st.dataframe(df_l, use_container_width=True, hide_index=True)

        t_l1, t_l2, t_l3, t_l4 = st.tabs(["➕ Tambah", "✏️ Edit", "📦 Stok", "🗑️ Hapus"])
        
        with t_l1:
            with st.form("f_tambah_addon_final"):
                an_in = st.text_input("Nama Add On")
                ak_in = st.selectbox("Kategori", list_kategori)
                ah_in = st.number_input("Harga Tambahan", min_value=0, step=500)
                as_in = st.number_input("Stok Awal", min_value=0, step=1)
                
                if st.form_submit_button("Simpan Add On"):
                    if not an_in.strip(): st.error("Nama Add On tidak boleh kosong!"); return
                    
                    is_dup_a = con.execute("SELECT COUNT(*) FROM master_label WHERE LOWER(TRIM(nama_label)) = LOWER(?)", [an_in.strip()]).fetchone()[0]
                    if is_dup_a > 0:
                        st.error(f"Gagal! Add On '{an_in.strip()}' sudah ada."); return
                    
                    new_id_a = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM master_label").fetchone()[0]
                    con.execute("INSERT INTO master_label (id, nama_label, kategori, harga, stok) VALUES (?,?,?,?,?)", 
                                [int(new_id_a), an_in.strip(), ak_in, float(ah_in), int(as_in)])
                    
                    st.success(f"Add On '{an_in}' dengan stok {int(as_in)} tersimpan!")
                    st.rerun()
        
        with t_l2:
            if not df_l.empty:
                a_target_id = st.selectbox("Pilih Add On (Edit)", df_l['id'].tolist(), format_func=lambda x: f"{df_l[df_l['id']==x]['nama_label'].values[0]}")
                old = df_l[df_l['id'] == a_target_id].iloc[0]
                with st.form("f_edit_a"):
                    new_nl = st.text_input("Nama Add On", value=old['nama_label'])
                    new_kl = st.selectbox("Kategori", list_kategori, index=list_kategori.index(old['kategori']))
                    new_hl = st.number_input("Harga", value=float(old['harga']))
                    if st.form_submit_button("Update Add On"):
                        con.execute("UPDATE master_label SET nama_label=?, kategori=?, harga=? WHERE id=?", [new_nl.strip(), new_kl, float(new_hl), int(a_target_id)])
                        st.success("Add On diperbarui!"); st.rerun()

        with t_l3:
            if not df_l.empty:
                a_stok_id = st.selectbox("Pilih Add On (Stok)", df_l['id'].tolist(), format_func=lambda x: f"{df_l[df_l['id']==x]['nama_label'].values[0]}")
                curr_sl = df_l[df_l['id'] == a_stok_id]['stok'].values[0]
                with st.form("f_upd_stok_a"):
                    nsl_in = st.number_input("Set Stok Baru", min_value=0, value=int(curr_sl), step=1)
                    if st.form_submit_button("Update Stok"):
                        con.execute("UPDATE master_label SET stok=? WHERE id=?", [int(nsl_in), int(a_stok_id)])
                        st.success("Stok diperbarui!"); st.rerun()

        with t_l4:
            if not df_l.empty:
                a_del_id = st.selectbox("Pilih Add On (Hapus)", df_l['id'].tolist(), format_func=lambda x: f"{df_l[df_l['id']==x]['nama_label'].values[0]}")
                if st.button("🔥 Hapus Add On Permanen"):
                    con.execute("DELETE FROM master_label WHERE id=?", [int(a_del_id)])
                    st.success("Add On dihapus!"); st.rerun()

    elif menu == "Dashboard":
        res_h = con.execute("SELECT SUM(total_harga) FROM transaksi WHERE CAST(waktu AS DATE) = ?", [get_now_wib().strftime('%Y-%m-%d')]).fetchone()
        st.metric("Omset Hari Ini", f"Rp{res_h[0] if res_h[0] else 0:,.0f}")
        df_tx = con.execute("SELECT * FROM transaksi").df()
        if not df_tx.empty: 
            df_tx['waktu'] = pd.to_datetime(df_tx['waktu'])
            st.plotly_chart(px.bar(df_tx, x='waktu', y='total_harga', title="Laporan Penjualan"))

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