import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta, timezone

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sistem Kasir Pro v1.6", layout="wide")

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
                p_harga_base = float(selected_item_data['harga'])
                p_stok_prod = selected_item_data['stok']
                
                # Ambil Add On (Nama, Harga, Stok)
                df_addons = con.execute("SELECT nama_label, harga, stok FROM master_label WHERE kategori = ?", [p_category]).df()
                
                addon_options = []
                addon_data_map = {}
                if not df_addons.empty:
                    for _, row in df_addons.iterrows():
                        # Tampilan menu: Nama (+Harga) [Sisa Stok]
                        label_display = f"{row['nama_label']} (+Rp{row['harga']:,.0f}) [Stok: {row['stok']}]"
                        addon_options.append(label_display)
                        addon_data_map[label_display] = {
                            "nama": row['nama_label'],
                            "harga": float(row['harga']),
                            "stok": int(row['stok'])
                        }
                
                selected_addons_display = st.multiselect(f"Pilih Add On ({p_category}):", addon_options)
                qty_p = st.number_input("Jumlah", min_value=1, step=1)

                if st.form_submit_button("➕ Tambah"):
                    # 1. Cek Stok Produk Utama
                    if p_stok_prod < qty_p:
                        st.error(f"Stok Produk '{item_p_name}' tidak cukup! (Sisa: {p_stok_prod})")
                        return

                    # 2. Cek Stok Semua Add On yang dipilih
                    insufficient_addons = []
                    total_addon_price = 0
                    clean_addons_list = []
                    
                    for ad_disp in selected_addons_display:
                        ad_info = addon_data_map[ad_disp]
                        if ad_info['stok'] < qty_p:
                            insufficient_addons.append(f"{ad_info['nama']} (Sisa: {ad_info['stok']})")
                        total_addon_price += ad_info['harga']
                        clean_addons_list.append(ad_info['nama'])

                    if insufficient_addons:
                        st.error(f"Stok Add On tidak cukup: {', '.join(insufficient_addons)}")
                    else:
                        final_unit_price = p_harga_base + total_addon_price
                        st.session_state.cart.append({
                            "id": int(p_id), 
                            "nama": item_p_name, 
                            "qty": int(qty_p),
                            "harga_satuan": final_unit_price, 
                            "subtotal": float(final_unit_price * qty_p),
                            "opsi_list": clean_addons_list, # List untuk potong stok nanti
                            "opsi_txt": ", ".join(clean_addons_list) # Teks untuk display
                        })
                        st.rerun()

    with col_cart:
        if st.session_state.cart:
            st.subheader("🛒 Keranjang")
            df_cart = pd.DataFrame(st.session_state.cart)
            total = sum(i['subtotal'] for i in st.session_state.cart)
            
            df_display = df_cart.copy()
            df_display['harga_satuan'] = df_display['harga_satuan'].map("Rp{:,.0f}".format)
            df_display['subtotal'] = df_display['subtotal'].map("Rp{:,.0f}".format)
            
            st.table(df_display[['nama', 'opsi_txt', 'qty', 'harga_satuan', 'subtotal']])
            st.write(f"### TOTAL BAYAR: Rp{total:,.0f}")
            
            if st.button("✅ SELESAIKAN", type="primary", use_container_width=True):
                id_tx = get_now_wib().strftime("%Y%m%d%H%M%S")
                for b in st.session_state.cart:
                    # Potong Stok Produk Utama
                    con.execute("UPDATE produk SET stok = stok - ? WHERE id = ?", [b['qty'], b['id']])
                    
                    # Potong Stok Tiap Add On
                    for addon_name in b['opsi_list']:
                        con.execute("UPDATE master_label SET stok = stok - ? WHERE nama_label = ?", [b['qty'], addon_name])
                    
                    # Simpan Transaksi
                    con.execute("INSERT INTO transaksi VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                [id_tx, b['nama'], b['qty'], b['subtotal'], st.session_state.username, get_now_wib().replace(tzinfo=None), b['opsi_txt']])
                
                st.session_state.cart = []
                st.success("Transaksi Berhasil & Stok Diperbarui!")
                st.rerun()

def admin_ui():
    st.title("🏗️ Panel Admin v1.6")
    menu = st.sidebar.selectbox("Menu", ["Dashboard", "Produk", "Add On", "Transaksi"])
    
    list_kategori = ["Minuman", "Makanan", "Fashion"]

    # --- MENU ADD ON ---
    if menu == "Add On":
        st.subheader("🧩 Manajemen Add On & Stok")
        df_l = con.execute("SELECT id, nama_label, kategori, harga, stok FROM master_label ORDER BY kategori, nama_label").df()
        
        df_l_disp = df_l.copy()
        if not df_l_disp.empty:
            df_l_disp['harga'] = df_l_disp['harga'].map("Rp{:,.0f}".format)
        st.dataframe(df_l_disp, use_container_width=True, hide_index=True)

        t_l1, t_l2, t_l3, t_l4 = st.tabs(["➕ Tambah", "✏️ Edit", "📦 Stok", "🗑️ Hapus"])
        
        with t_l1:
            with st.form("add_addon"):
                nl = st.text_input("Nama Add On")
                kl = st.selectbox("Kategori", list_kategori)
                hl = st.number_input("Harga Tambahan", min_value=0, step=500)
                sl = st.number_input("Stok Awal", min_value=0)
                if st.form_submit_button("Simpan"):
                    new_id = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM master_label").fetchone()[0]
                    con.execute("INSERT INTO master_label VALUES (?,?,?,?)", [new_id, nl, kl, hl, sl]) # Update query sesuai kolom stok
                    st.rerun()
        
        with t_l2:
            if not df_l.empty:
                edit_l_id = st.selectbox("Pilih Add On (Edit)", df_l['id'].tolist(), 
                                         format_func=lambda x: f"{df_l[df_l['id']==x]['nama_label'].values[0]}")
                old_data = df_l[df_l['id'] == edit_l_id].iloc[0]
                with st.form("edit_addon_form"):
                    new_nl = st.text_input("Nama Baru", value=old_data['nama_label'])
                    new_kl = st.selectbox("Kategori Baru", list_kategori, index=list_kategori.index(old_data['kategori']))
                    new_hl = st.number_input("Harga", value=float(old_data['harga']), step=500.0)
                    if st.form_submit_button("Update"):
                        con.execute("UPDATE master_label SET nama_label=?, kategori=?, harga=? WHERE id=?", [new_nl, new_kl, new_hl, edit_l_id])
                        st.rerun()

        with t_l3:
            if not df_l.empty:
                stok_l_id = st.selectbox("Pilih Add On (Update Stok)", df_l['id'].tolist(), 
                                         format_func=lambda x: f"{df_l[df_l['id']==x]['nama_label'].values[0]}")
                curr_stok_l = df_l[df_l['id'] == stok_l_id]['stok'].values[0]
                new_sl = st.number_input("Set Stok Baru", min_value=0, value=int(curr_stok_l))
                if st.button("Update Stok Add On"):
                    con.execute("UPDATE master_label SET stok=? WHERE id=?", [new_sl, stok_l_id])
                    st.rerun()

        with t_l4:
            if not df_l.empty:
                del_l_id = st.selectbox("Pilih Add On (Hapus)", df_l['id'].tolist())
                if st.button("🔥 Hapus Permanen"):
                    con.execute("DELETE FROM master_label WHERE id=?", [del_l_id])
                    st.rerun()

    # --- MENU PRODUK (LOGIKA TETAP SAMA) ---
    elif menu == "Produk":
        st.subheader("📦 Daftar Produk Dasar")
        df_p = con.execute("SELECT id, nama_produk, kategori, harga, stok FROM produk ORDER BY id DESC").df()
        st.dataframe(df_p, use_container_width=True, hide_index=True)

        t1, t2, t3, t4 = st.tabs(["➕ Tambah", "✏️ Edit", "📦 Stok", "🗑️ Hapus"])
        # (Isi tab produk tetap konsisten dengan v1.5 dengan penyesuaian Update Stok by Name)
        with t1:
            with st.form("f_add"):
                n = st.text_input("Nama")
                k = st.selectbox("Kat", list_kategori)
                h = st.number_input("Harga", min_value=0)
                s = st.number_input("Stok", min_value=0)
                if st.form_submit_button("Simpan"):
                    con.execute("INSERT INTO produk VALUES ((SELECT COALESCE(MAX(id),0)+1 FROM produk),?,?,?,?,?)", [n, k, h, s, ""])
                    st.rerun()
        
        with t3:
            if not df_p.empty:
                nama_stok = st.selectbox("Nama Produk", sorted(df_p['nama_produk'].tolist()))
                curr_s = df_p[df_p['nama_produk'] == nama_stok]['stok'].values[0]
                ns = st.number_input("Stok Baru", min_value=0, value=int(curr_s))
                if st.button("Update"):
                    con.execute("UPDATE produk SET stok=? WHERE nama_produk=?", [ns, nama_stok])
                    st.rerun()
        # ... (edit & hapus produk menyesuaikan)

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