import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta, timezone

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sistem Kasir Pro v1.1 - Stable", layout="wide")

# --- 2. KONEKSI & INISIALISASI DATABASE ---
@st.cache_resource
def get_connection():
    try:
        if "MOTHERDUCK_TOKEN" not in st.secrets:
            st.error("Missing MOTHERDUCK_TOKEN in secrets!")
            st.stop()
        TOKEN = st.secrets["MOTHERDUCK_TOKEN"]
        con = duckdb.connect(f"md:tes_db?motherduck_token={TOKEN}")
        
        # Inisialisasi tabel master_label jika belum ada
        con.execute("""
            CREATE TABLE IF NOT EXISTS master_label (
                id INTEGER PRIMARY KEY,
                nama_label VARCHAR,
                kategori VARCHAR
            )
        """)
        return con
    except Exception as e:
        st.error(f"Gagal koneksi ke MotherDuck: {e}")
        st.stop()

con = get_connection()

# --- 3. LOGIKA HELPER & WAKTU (WIB) ---
WIB = timezone(timedelta(hours=7))

def get_now_wib():
    return datetime.now(timezone.utc).astimezone(WIB)

def standardize_options(opsi_string):
    if not opsi_string or str(opsi_string).strip().lower() == "none" or opsi_string == "":
        return ""
    parts = [p.strip().lower() for p in opsi_string.split(",") if p.strip()]
    parts.sort()
    return ", ".join(parts)

def refresh_label_stocks():
    """Menghitung ulang total stok berdasarkan label yang terjual/tersedia"""
    try:
        df_all = con.execute("SELECT opsi, stok FROM produk WHERE opsi IS NOT NULL AND opsi != ''").df()
        con.execute("DELETE FROM label_stok")
        
        if df_all.empty: return
            
        label_map = {}
        for _, row in df_all.iterrows():
            opsi_list = [o.strip().lower() for o in str(row['opsi']).split(",") if o.strip()]
            for label in opsi_list:
                label_map[label] = label_map.get(label, 0) + int(row['stok'])
        
        for i, (nama_label, total_stok) in enumerate(label_map.items()):
            con.execute("INSERT INTO label_stok VALUES (?, ?, ?, ?)", [i + 1, nama_label, total_stok, 'pcs'])
    except Exception as e:
        st.error(f"Gagal sinkronisasi label: {e}")

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
    now_wib = get_now_wib()
    st.header(f"🛒 Kasir: {st.session_state.username}")
    
    if "cart" not in st.session_state: st.session_state.cart = []
    if "last_tx" not in st.session_state: st.session_state.last_tx = None

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
                
                # Mendapatkan kategori produk yang dipilih untuk memfilter label
                p_category = df_filtered[df_filtered['nama_produk'] == item_p_name]['kategori'].values[0]
                
                # FILTER LABEL: Hanya ambil label yang sesuai dengan kategori produk
                df_labels = con.execute("SELECT nama_label FROM master_label WHERE kategori = ?", [p_category]).df()
                available_labels = sorted(df_labels['nama_label'].tolist()) if not df_labels.empty else []
                
                p_user_selection = st.multiselect(f"Opsi ({p_category}):", available_labels)
                qty_p = st.number_input("Jumlah", min_value=1, step=1)

                if st.form_submit_button("➕ Tambah"):
                    selected_std_opt = standardize_options(", ".join(p_user_selection))
                    
                    # Cari varian produk yang cocok dengan opsi
                    all_variants = df_produk[df_produk['nama_produk'] == item_p_name]
                    target_product = None
                    for _, row in all_variants.iterrows():
                        if standardize_options(row['opsi']) == selected_std_opt:
                            target_product = row
                            break
                    
                    if target_product is not None:
                        if int(target_product['stok']) >= qty_p:
                            st.session_state.cart.append({
                                "id": int(target_product['id']), "nama": item_p_name, "qty": int(qty_p),
                                "harga": float(target_product['harga']), 
                                "subtotal": float(target_product['harga'] * qty_p),
                                "opsi": ", ".join(p_user_selection)
                            })
                            st.rerun()
                        else: st.error(f"Stok Habis! Sisa: {target_product['stok']}")
                    else:
                        st.error("🚨 Varian/Kombinasi Opsi ini tidak tersedia di stok produk.")

    with col_cart:
        if st.session_state.cart:
            st.subheader("🛒 Keranjang")
            df_cart = pd.DataFrame(st.session_state.cart)
            total = sum(i['subtotal'] for i in st.session_state.cart)
            st.table(df_cart[['nama', 'opsi', 'qty', 'subtotal']])
            st.write(f"### TOTAL: Rp{total:,.0f}")
            if st.button("✅ SELESAIKAN", type="primary"):
                id_tx = get_now_wib().strftime("%Y%m%d%H%M%S")
                for b in st.session_state.cart:
                    con.execute("UPDATE produk SET stok = stok - ? WHERE id = ?", [b['qty'], b['id']])
                    con.execute("INSERT INTO transaksi VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                [id_tx, b['nama'], b['qty'], b['subtotal'], st.session_state.username, get_now_wib().replace(tzinfo=None), b['opsi']])
                refresh_label_stocks()
                st.session_state.cart = []
                st.success("Transaksi Berhasil!")
                st.rerun()

def admin_ui():
    st.title("🏗️ Panel Admin v1.1")
    menu = st.sidebar.selectbox("Menu", ["Dashboard", "Produk", "Kelola Label", "Transaksi"])
    
    # --- TABEL MASTER LABEL ---
    if menu == "Kelola Label":
        st.subheader("🏷️ Master Label & Kategori")
        df_l = con.execute("SELECT * FROM master_label ORDER BY kategori, nama_label").df()
        st.dataframe(df_l, use_container_width=True, hide_index=True)

        t_l1, t_l2, t_l3 = st.tabs(["➕ Tambah Label", "✏️ Edit Label", "🗑️ Hapus"])
        
        with t_l1:
            with st.form("add_label"):
                nl = st.text_input("Nama Label (Contoh: Dingin, Pedas, Large)")
                kl = st.selectbox("Untuk Kategori", ["Minuman", "Makanan", "Snack"])
                if st.form_submit_button("Simpan Label"):
                    new_id = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM master_label").fetchone()[0]
                    con.execute("INSERT INTO master_label VALUES (?,?,?)", [new_id, nl, kl])
                    st.success(f"Label '{nl}' ditambahkan untuk {kl}")
                    st.rerun()
        
        with t_l2:
            if not df_l.empty:
                edit_l_id = st.selectbox("Pilih Label yang akan diubah", df_l['id'].tolist(), format_func=lambda x: f"ID {x} - {df_l[df_l['id']==x]['nama_label'].values[0]}")
                old_data = df_l[df_l['id'] == edit_l_id].iloc[0]
                with st.form("edit_label_form"):
                    new_nl = st.text_input("Nama Label Baru", value=old_data['nama_label'])
                    new_kl = st.selectbox("Kategori Baru", ["Minuman", "Makanan", "Snack"], index=["Minuman", "Makanan", "Snack"].index(old_data['kategori']))
                    if st.form_submit_button("Update Label"):
                        con.execute("UPDATE master_label SET nama_label=?, kategori=? WHERE id=?", [new_nl, new_kl, edit_l_id])
                        st.success("Label Berhasil diupdate!")
                        st.rerun()

        with t_l3:
            if not df_l.empty:
                del_l_id = st.selectbox("Pilih Label yang akan dihapus", df_l['id'].tolist(), key="del_l")
                if st.button("🔥 Hapus Label"):
                    con.execute("DELETE FROM master_label WHERE id=?", [del_l_id])
                    st.rerun()

    # --- TABEL PRODUK (MODIFIED) ---
    elif menu == "Produk":
        st.subheader("📦 Daftar Produk")
        df_p = con.execute("SELECT * FROM produk ORDER BY id DESC").df()
        st.dataframe(df_p, use_container_width=True)

        t1, t2, t3, t4 = st.tabs(["➕ Tambah Produk", "✏️ Edit Produk", "📦 Stok", "🗑️ Hapus"])
        
        with t1:
            with st.form("f_add"):
                n = st.text_input("Nama Produk")
                k = st.selectbox("Kategori", ["Minuman", "Makanan", "Snack"], key="add_kat")
                h = st.number_input("Harga", min_value=0, step=500)
                s = st.number_input("Stok", min_value=0)
                
                # Ambil label yang tersedia untuk kategori yang dipilih
                avail_labels = con.execute("SELECT nama_label FROM master_label WHERE kategori = ?", [k]).df()
                opt_list = sorted(avail_labels['nama_label'].tolist()) if not avail_labels.empty else []
                o = st.multiselect("Pilih Opsi/Label", opt_list)
                
                if st.form_submit_button("Simpan"):
                    nid = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM produk").fetchone()[0]
                    con.execute("INSERT INTO produk VALUES (?,?,?,?,?,?)", [nid, n, k, h, s, ", ".join(o)])
                    refresh_label_stocks()
                    st.rerun()
        
        with t2:
            if not df_p.empty:
                eid = st.selectbox("Pilih ID Produk", df_p['id'].tolist())
                curr = df_p[df_p['id'] == eid].iloc[0]
                with st.form("f_edit"):
                    en = st.text_input("Nama", value=curr['nama_produk'])
                    ek = st.selectbox("Kategori", ["Minuman", "Makanan", "Snack"], index=["Minuman", "Makanan", "Snack"].index(curr['kategori']))
                    eh = st.number_input("Harga", value=float(curr['harga']))
                    
                    # Filter label berdasarkan kategori saat edit
                    avail_labels_edit = con.execute("SELECT nama_label FROM master_label WHERE kategori = ?", [ek]).df()
                    opt_list_edit = sorted(avail_labels_edit['nama_label'].tolist()) if not avail_labels_edit.empty else []
                    
                    # Pre-select label yang sudah ada
                    curr_opsi = [x.strip() for x in str(curr['opsi']).split(",") if x.strip()]
                    eo = st.multiselect("Pilih Opsi/Label", opt_list_edit, default=[x for x in curr_opsi if x in opt_list_edit])
                    
                    if st.form_submit_button("Update"):
                        con.execute("UPDATE produk SET nama_produk=?, kategori=?, harga=?, opsi=? WHERE id=?", [en, ek, eh, ", ".join(eo), eid])
                        refresh_label_stocks()
                        st.rerun()

        # ... (Logika t3 & t4 tetap sama seperti sebelumnya) ...
        with t3:
            if not df_p.empty:
                stok_id = st.selectbox("Pilih Produk (Stok)", df_p['id'].tolist())
                ns = st.number_input("Set Stok Baru", min_value=0)
                if st.button("Update Stok"):
                    con.execute("UPDATE produk SET stok=? WHERE id=?", [ns, stok_id])
                    refresh_label_stocks()
                    st.rerun()
        
        with t4:
            if not df_p.empty:
                did = st.selectbox("Pilih ID untuk Hapus", df_p['id'].tolist())
                if st.button("🔥 Hapus"):
                    con.execute("DELETE FROM produk WHERE id=?", [did])
                    refresh_label_stocks()
                    st.rerun()

    elif menu == "Dashboard":
        # Dashboard logic...
        res_h = con.execute("SELECT SUM(total_harga) FROM transaksi WHERE CAST(waktu AS DATE) = ?", [get_now_wib().strftime('%Y-%m-%d')]).fetchone()
        st.metric("Omset Hari Ini", f"Rp{res_h[0] if res_h[0] else 0:,.0f}")
        df_tx = con.execute("SELECT * FROM transaksi").df()
        if not df_tx.empty:
            st.plotly_chart(px.line(df_tx, x='waktu', y='total_harga', title="Tren Penjualan"))

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