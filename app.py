import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta, timezone

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sistem Kasir Pro v1.0", layout="wide")

# --- 2. KONEKSI DATABASE ---
@st.cache_resource
def get_connection():
    try:
        if "MOTHERDUCK_TOKEN" not in st.secrets:
            st.error("Missing MOTHERDUCK_TOKEN in secrets!")
            st.stop()
        TOKEN = st.secrets["MOTHERDUCK_TOKEN"]
        # Menghubungkan ke MotherDuck
        return duckdb.connect(f"md:tes_db?motherduck_token={TOKEN}")
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
    """Menghitung ulang total stok berdasarkan label/opsi unik"""
    try:
        df_all = con.execute("SELECT opsi, stok FROM produk WHERE opsi IS NOT NULL AND opsi != ''").df()
        con.execute("DELETE FROM label_stok") # Reset tabel label
        
        if df_all.empty:
            return
            
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
    st.info(f"🕒 Waktu Sekarang (WIB): **{now_wib.strftime('%H:%M:%S')}**")
    
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
                nama_produk_unik = sorted(df_filtered['nama_produk'].unique())
                item_p_name = st.selectbox("Pilih Produk", nama_produk_unik)
                
                all_variations = df_produk[df_produk['nama_produk'] == item_p_name]
                available_labels = []
                for opt_str in all_variations['opsi'].fillna("").tolist():
                    if opt_str:
                        available_labels.extend([x.strip() for x in opt_str.split(",")])
                available_labels = sorted(list(set(available_labels)))
                
                p_user_selection = st.multiselect("Opsi Tambahan:", available_labels)
                qty_p = st.number_input("Jumlah", min_value=1, step=1)

                if st.form_submit_button("➕ Tambah"):
                    selected_lower = [s.lower() for s in p_user_selection]
                    # Validasi Logika Bisnis Sederhana
                    if "dingin" in selected_lower and "hangat" in selected_lower:
                        st.error("⚠️ Tidak bisa pilih Dingin & Hangat bersamaan!")
                    elif "cup besar" in selected_lower and "cup kecil" in selected_lower:
                        st.error("⚠️ Pilih salah satu ukuran Cup!")
                    else:
                        selected_std_opt = standardize_options(", ".join(p_user_selection))
                        target_product = None
                        for _, row in all_variations.iterrows():
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
                        else: st.error("Varian ini tidak terdaftar.")

    with col_cart:
        if st.session_state.last_tx and not st.session_state.cart:
            st.success(f"✅ Transaksi Berhasil! (ID: {st.session_state.last_tx['id_tx']})")
            df_last = pd.DataFrame(st.session_state.last_tx['items'])
            df_last_disp = df_last.copy()
            df_last_disp['subtotal'] = df_last_disp['subtotal'].map("Rp{:,.0f}".format)
            st.table(df_last_disp[['nama', 'opsi', 'qty', 'subtotal']])
            if st.button("🆕 Lanjut"):
                st.session_state.last_tx = None
                st.rerun()

        elif st.session_state.cart:
            st.subheader("🛒 Keranjang")
            df_cart = pd.DataFrame(st.session_state.cart)
            total = sum(i['subtotal'] for i in st.session_state.cart)
            df_disp = df_cart.copy()
            df_disp['subtotal'] = df_disp['subtotal'].map("Rp{:,.0f}".format)
            st.table(df_disp[['nama', 'opsi', 'qty', 'subtotal']])
            st.write(f"### TOTAL: Rp{total:,.0f}")
            if st.button("✅ SELESAIKAN", type="primary", use_container_width=True):
                current_wib = get_now_wib()
                id_tx = current_wib.strftime("%Y%m%d%H%M%S")
                st.session_state.last_tx = {"id_tx": id_tx, "items": list(st.session_state.cart)}
                
                for b in st.session_state.cart:
                    con.execute("UPDATE produk SET stok = stok - ? WHERE id = ?", [b['qty'], b['id']])
                    con.execute("INSERT INTO transaksi VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                [id_tx, b['nama'], int(b['qty']), float(b['subtotal']), st.session_state.username, current_wib.replace(tzinfo=None), b['opsi']])
                
                refresh_label_stocks()
                st.session_state.cart = []
                st.rerun()

def admin_ui():
    now_wib = get_now_wib()
    st.title("🏗️ Panel Admin")
    st.caption(f"WIB: {now_wib.strftime('%d/%m/%Y %H:%M:%S')}")
    menu = st.sidebar.selectbox("Menu", ["Dashboard", "Produk", "Label", "Transaksi"])
    
    if menu == "Dashboard":
        today_str = now_wib.strftime('%Y-%m-%d')
        res_h = con.execute("SELECT SUM(total_harga) FROM transaksi WHERE CAST(waktu AS DATE) = ?", [today_str]).fetchone()
        h = res_h[0] if res_h and res_h[0] is not None else 0
        st.metric("Omset Hari Ini (WIB)", f"Rp{h:,.0f}")
        df_tx = con.execute("SELECT * FROM transaksi").df()
        if not df_tx.empty:
            st.plotly_chart(px.bar(df_tx, x='waktu', y='total_harga', color='nama_produk', title="Trend Penjualan"), use_container_width=True)

    elif menu == "Produk":
        st.subheader("📦 Daftar Produk")
        df_p = con.execute("SELECT id, nama_produk, kategori, harga, stok, opsi FROM produk ORDER BY id DESC").df()
        df_p_disp = df_p.copy()
        df_p_disp['harga'] = df_p_disp['harga'].map("Rp{:,.0f}".format)
        st.dataframe(df_p_disp, use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("🛠️ Kelola Produk")
        t1, t2, t3, t4 = st.tabs(["➕ Tambah", "✏️ Edit", "📦 Update Stok", "🗑️ Hapus"])
        
        # TAB 1: TAMBAH PRODUK
        with t1:
            with st.form("f_add", clear_on_submit=True):
                n = st.text_input("Nama Produk")
                k = st.selectbox("Kategori", ["Minuman", "Makanan", "Snack"])
                h = st.number_input("Harga", min_value=0, step=500)
                s = st.number_input("Stok Awal", min_value=0, step=1)
                o = st.text_input("Opsi (Pisahkan dengan koma, contoh: Dingin, Hangat)")
                if st.form_submit_button("Simpan Produk"):
                    nid = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM produk").fetchone()[0]
                    con.execute("INSERT INTO produk VALUES (?,?,?,?,?,?)", [nid, n, k, h, s, o])
                    refresh_label_stocks()
                    st.success(f"Produk {n} Berhasil Ditambahkan!")
                    st.rerun()

        # TAB 2: EDIT PRODUK
        with t2:
            if not df_p.empty:
                edit_id = st.selectbox("Pilih ID Produk untuk di-Edit", df_p['id'].tolist())
                item_data = df_p[df_p['id'] == edit_id].iloc[0]
                
                with st.form("f_edit"):
                    new_n = st.text_input("Nama Produk", value=item_data['nama_produk'])
                    new_k = st.selectbox("Kategori", ["Minuman", "Makanan", "Snack"], 
                                         index=["Minuman", "Makanan", "Snack"].index(item_data['kategori']))
                    new_h = st.number_input("Harga", value=float(item_data['harga']), step=500.0)
                    new_o = st.text_input("Opsi", value=item_data['opsi'])
                    
                    if st.form_submit_button("Update Data"):
                        con.execute("""UPDATE produk SET nama_produk=?, kategori=?, harga=?, opsi=? 
                                    WHERE id=?""", [new_n, new_k, new_h, new_o, edit_id])
                        refresh_label_stocks()
                        st.success("Update Berhasil!")
                        st.rerun()
            else: st.info("Tidak ada data.")

        # TAB 3: UPDATE STOK (QUICK)
        with t3:
            if not df_p.empty:
                stok_id = st.selectbox("Pilih Produk (Update Stok)", df_p['id'].tolist(), key="stok_sel")
                curr_stok = df_p[df_p['id'] == stok_id]['stok'].values[0]
                st.write(f"Stok Sekarang: **{curr_stok}**")
                
                new_stok_val = st.number_input("Set Stok Baru", min_value=0, step=1, value=int(curr_stok))
                if st.button("Update Stok"):
                    con.execute("UPDATE produk SET stok=? WHERE id=?", [new_stok_val, stok_id])
                    refresh_label_stocks()
                    st.success("Stok Berhasil diperbarui!")
                    st.rerun()

        # TAB 4: HAPUS PRODUK
        with t4:
            if not df_p.empty:
                del_id = st.selectbox("Pilih ID Produk untuk di-HAPUS", df_p['id'].tolist(), key="del_sel")
                target_name = df_p[df_p['id'] == del_id]['nama_produk'].values[0]
                st.warning(f"Apakah Anda yakin ingin menghapus **{target_name}** (ID: {del_id})?")
                if st.button("🔥 HAPUS PERMANEN", type="secondary"):
                    con.execute("DELETE FROM produk WHERE id=?", [del_id])
                    refresh_label_stocks()
                    st.success("Produk Dihapus!")
                    st.rerun()

    elif menu == "Label":
        st.subheader("🏷️ Akumulasi Stok per Label")
        refresh_label_stocks() # Pastikan data terbaru
        df_l = con.execute("SELECT * FROM label_stok ORDER BY stok DESC").df()
        if not df_l.empty:
            st.dataframe(df_l, use_container_width=True, hide_index=True)
        else:
            st.info("Belum ada label/opsi yang terdaftar pada produk.")

    elif menu == "Transaksi":
        st.subheader("📜 Riwayat Transaksi")
        df_tx = con.execute("SELECT * FROM transaksi ORDER BY waktu DESC").df()
        if not df_tx.empty:
            df_tx_disp = df_tx.copy()
            df_tx_disp['waktu'] = pd.to_datetime(df_tx_disp['waktu']).dt.strftime('%d/%m/%Y %H:%M:%S')
            df_tx_disp['total_harga'] = df_tx_disp['total_harga'].map("Rp{:,.0f}".format)
            st.dataframe(df_tx_disp, use_container_width=True, hide_index=True)
        else: st.info("Belum ada transaksi.")

# --- 5. LOGIKA UTAMA ---
if "logged_in" not in st.session_state:
    login_ui()
else:
    st.sidebar.write(f"User: **{st.session_state.username}** ({st.session_state.role})")
    if st.sidebar.button("Logout"):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()
    
    if st.session_state.role == "admin": 
        admin_ui()
    else: 
        cashier_ui()