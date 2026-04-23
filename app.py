import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px
from datetime import datetime

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sistem Kasir Pro v3.7", layout="wide")

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

# --- 3. LOGIKA HELPER & SINKRONISASI ---
def standardize_options(opsi_string):
    """Menyederhanakan string opsi untuk pengecekan duplikasi yang akurat"""
    if not opsi_string or str(opsi_string).strip().lower() == "none" or opsi_string == "":
        return ""
    # Pecah, bersihkan spasi, ubah ke kecil, urutkan, dan gabungkan kembali
    parts = [p.strip().lower() for p in opsi_string.split(",") if p.strip()]
    parts.sort()
    return ", ".join(parts)

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
    if "last_tx" not in st.session_state: st.session_state.last_tx = None

    try:
        df_produk = con.execute("SELECT * FROM produk").df()
    except:
        st.warning("Tabel produk belum siap.")
        return

    col_input, col_cart = st.columns([1, 2])

    with col_input:
        st.subheader("Input Pesanan")
        list_kat = ["Semua"] + list(df_produk['kategori'].unique()) if not df_produk.empty else ["Semua"]
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
        if st.session_state.last_tx and not st.session_state.cart:
            st.success(f"✅ Transaksi Berhasil! (ID: {st.session_state.last_tx['id_tx']})")
            df_last = pd.DataFrame(st.session_state.last_tx['items'])
            st.table(df_last[['nama', 'opsi', 'qty', 'subtotal']])
            if st.button("🆕 Transaksi Baru"):
                st.session_state.last_tx = None
                st.rerun()

        elif st.session_state.cart:
            st.subheader("🛒 Keranjang")
            df_cart = pd.DataFrame(st.session_state.cart)
            total = sum(i['subtotal'] for i in st.session_state.cart)
            st.table(df_cart[['nama', 'opsi', 'qty', 'subtotal']])
            st.write(f"### TOTAL: Rp{total:,.0f}")
            if st.button("✅ SELESAIKAN", type="primary", use_container_width=True):
                id_tx = datetime.now().strftime("%Y%m%d%H%M%S")
                st.session_state.last_tx = {"id_tx": id_tx, "items": list(st.session_state.cart)}
                for b in st.session_state.cart:
                    con.execute("UPDATE produk SET stok = stok - ? WHERE id = ?", [b['qty'], b['id']])
                    if b['opsi']: sync_cumulative_label(b['opsi'], -b['qty'])
                    con.execute("INSERT INTO transaksi VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                [id_tx, b['nama'], b['qty'], b['subtotal'], st.session_state.username, datetime.now(), b['opsi']])
                st.session_state.cart = []
                st.rerun()

def admin_ui():
    st.title("🏗️ Panel Admin")
    menu = st.sidebar.selectbox("Menu", ["Dashboard", "Produk", "Label", "Transaksi"])
    
    if menu == "Dashboard":
        h = con.execute("SELECT SUM(total_harga) FROM transaksi WHERE CAST(waktu AS DATE) = CURRENT_DATE").fetchone()[0] or 0
        st.metric("Omset Hari Ini", f"Rp{h:,.0f}")
        df_tx = con.execute("SELECT * FROM transaksi").df()
        if not df_tx.empty:
            st.plotly_chart(px.bar(df_tx, x='waktu', y='total_harga', color='nama_produk'), use_container_width=True)

    elif menu == "Produk":
        st.subheader("📦 Daftar Produk")
        col_f1, col_f2 = st.columns([2, 1])
        with col_f1:
            search = st.text_input("🔍 Cari Produk...")
        with col_f2:
            limit = st.number_input("Tampilkan Baris", min_value=5, max_value=100, value=10)

        query = "SELECT * FROM produk"
        if search:
            query += f" WHERE LOWER(nama_produk) LIKE LOWER('%{search}%')"
        query += " ORDER BY id DESC"
        df_p = con.execute(query).df()
        
        st.dataframe(df_p.head(limit), use_container_width=True, hide_index=True)

        st.markdown("---")
        st.subheader("🛠️ Kelola Data Produk")
        tab_add, tab_edit, tab_stock, tab_del = st.tabs([
            "➕ Tambah Baru", "✏️ Edit Detail", "📦 Update Stok", "🗑️ Hapus"
        ])

        with tab_add:
            with st.form("form_add", clear_on_submit=True):
                c1, c2 = st.columns(2)
                with c1:
                    n = st.text_input("Nama Produk").strip()
                    k = st.selectbox("Kategori", ["Minuman", "Makanan", "Snack"])
                with c2:
                    h = st.number_input("Harga", min_value=0, step=500)
                    s = st.number_input("Stok Awal", min_value=0, step=1)
                o = st.text_input("Opsi/Label (Pisahkan dengan koma)")
                
                if st.form_submit_button("Simpan Produk"):
                    if n:
                        # STANDARISASI INPUT OPSI UNTUK CEK DUPLIKAT
                        standard_input_o = standardize_options(o)
                        
                        # Ambil semua produk dengan nama yang sama (case insensitive)
                        existing_items = con.execute("SELECT opsi FROM produk WHERE LOWER(nama_produk) = LOWER(?)", [n]).fetchall()
                        
                        is_duplicate = False
                        for item in existing_items:
                            # Bandingkan opsi input dengan opsi di DB yang sudah distandarisasi
                            if standardize_options(item[0]) == standard_input_o:
                                is_duplicate = True
                                break
                        
                        if is_duplicate:
                            st.error(f"❌ Gagal! Produk '{n}' dengan opsi [{o if o else 'Tanpa Opsi'}] sudah ada di database.")
                        else:
                            nid = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM produk").fetchone()[0]
                            con.execute("INSERT INTO produk VALUES (?,?,?,?,?,?)", [nid, n, k, h, s, o])
                            sync_cumulative_label(o, s)
                            st.success(f"✅ Berhasil menambah produk: {n} ({o if o else 'No Opsi'})")
                            st.rerun()
                    else: st.error("Nama produk tidak boleh kosong!")

        with tab_edit:
            if not df_p.empty:
                # Menampilkan nama + opsi di selectbox agar admin tahu mana yang mau diedit
                df_p['display_name'] = df_p['nama_produk'] + " (" + df_p['opsi'].fillna("No Opsi") + ")"
                sel_display = st.selectbox("Pilih Produk Edit", df_p['display_name'].sort_values())
                row = df_p[df_p['display_name'] == sel_display].iloc[0]
                
                with st.form("form_edit"):
                    en = st.text_input("Nama Produk", value=row['nama_produk'])
                    eh = st.number_input("Harga", value=float(row['harga']))
                    eo = st.text_input("Opsi", value=str(row['opsi']) if row['opsi'] else "")
                    
                    if st.form_submit_button("Update Info Produk"):
                        # Validasi duplikasi saat edit nama/opsi
                        std_eo = standardize_options(eo)
                        check_others = con.execute("""
                            SELECT id, opsi FROM produk 
                            WHERE LOWER(nama_produk) = LOWER(?) AND id != ?
                        """, [en, int(row['id'])]).fetchall()
                        
                        is_edit_dup = False
                        for other in check_others:
                            if standardize_options(other[1]) == std_eo:
                                is_edit_dup = True
                                break
                        
                        if is_edit_dup:
                            st.error(f"❌ Gagal! Nama & Opsi ini sudah digunakan oleh produk lain.")
                        else:
                            con.execute("UPDATE produk SET nama_produk=?, harga=?, opsi=? WHERE id=?", 
                                        [en, eh, eo, int(row['id'])])
                            st.success(f"✅ Detail '{en}' diperbarui.")
                            st.rerun()

        with tab_stock:
            if not df_p.empty:
                df_p['display_name'] = df_p['nama_produk'] + " (" + df_p['opsi'].fillna("No Opsi") + ")"
                sel_stock = st.selectbox("Pilih Produk Update Stok", df_p['display_name'].sort_values(), key="stk_sel")
                row_s = df_p[df_p['display_name'] == sel_stock].iloc[0]
                st.write(f"Stok saat ini: **{row_s['stok']}**")
                
                with st.form("form_update_stok"):
                    change = st.number_input("Perubahan Stok (+/-)", value=0, step=1)
                    if st.form_submit_button("Konfirmasi Stok"):
                        con.execute("UPDATE produk SET stok = stok + ? WHERE id = ?", [int(change), int(row_s['id'])])
                        if row_s['opsi']:
                            sync_cumulative_label(row_s['opsi'], change)
                        st.success(f"✅ Stok diperbarui!")
                        st.rerun()

        with tab_del:
            if not df_p.empty:
                df_p['display_name'] = df_p['nama_produk'] + " (" + df_p['opsi'].fillna("No Opsi") + ")"
                sel_del = st.selectbox("Pilih Produk Hapus", df_p['display_name'].sort_values(), key="del_box")
                row_d = df_p[df_p['display_name'] == sel_del].iloc[0]
                if st.button("🔥 KONFIRMASI HAPUS PERMANEN", use_container_width=True):
                    con.execute("DELETE FROM produk WHERE id = ?", [int(row_d['id'])])
                    st.success(f"🗑️ Produk '{sel_del}' dihapus!")
                    st.rerun()

    elif menu == "Label":
        st.subheader("🏷️ Stok Label / Bahan Baku")
        df_l = con.execute("SELECT * FROM label_stok ORDER BY id_label ASC").df()
        st.dataframe(df_l, use_container_width=True, hide_index=True)
        with st.expander("🔄 Koreksi Stok"):
            with st.form("up_l"):
                sel_l = st.selectbox("Label", df_l['nama_label']) if not df_l.empty else []
                asl = st.number_input("Koreksi (+/-)", value=0)
                if st.form_submit_button("Update"):
                    con.execute("UPDATE label_stok SET stok=stok+? WHERE nama_label=?", [asl, sel_l])
                    st.success("✅ Stok label diperbarui")
                    st.rerun()

    elif menu == "Transaksi":
        st.subheader("📜 Riwayat Transaksi")
        st.dataframe(con.execute("SELECT * FROM transaksi ORDER BY waktu DESC").df(), use_container_width=True)

# --- 5. LOGIKA UTAMA ---
if "logged_in" not in st.session_state:
    login_ui()
else:
    st.sidebar.write(f"User: **{st.session_state.username}**")
    if st.sidebar.button("Logout"):
        for k in list(st.session_state.keys()): del st.session_state[k]
        st.rerun()
    
    if st.session_state.role == "admin":
        admin_ui()
    else:
        cashier_ui()