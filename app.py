import streamlit as st
import duckdb
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta, timezone

# --- 1. KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sistem Kasir Pro v1.1", layout="wide")

# --- 2. KONEKSI & SKEMA DATABASE ---
@st.cache_resource
def get_connection():
    try:
        if "MOTHERDUCK_TOKEN" not in st.secrets:
            st.error("Missing MOTHERDUCK_TOKEN in secrets!")
            st.stop()
        TOKEN = st.secrets["MOTHERDUCK_TOKEN"]
        con = duckdb.connect(f"md:tes_db?motherduck_token={TOKEN}")
        
        # Inisialisasi Tabel Jika Belum Ada
        con.execute("""
            CREATE TABLE IF NOT EXISTS produk (
                id INTEGER PRIMARY KEY,
                nama_produk VARCHAR,
                kategori VARCHAR,
                harga DOUBLE,
                stok INTEGER
            );
            CREATE TABLE IF NOT EXISTS labels (
                id INTEGER PRIMARY KEY,
                nama_label VARCHAR,
                kategori_terkait VARCHAR,
                harga_tambahan DOUBLE
            );
            CREATE TABLE IF NOT EXISTS transaksi (
                id_tx VARCHAR,
                nama_produk VARCHAR,
                qty INTEGER,
                total_harga DOUBLE,
                kasir VARCHAR,
                waktu TIMESTAMP,
                opsi_pilihan VARCHAR
            );
        """)
        return con
    except Exception as e:
        st.error(f"Gagal koneksi database: {e}")
        st.stop()

con = get_connection()
WIB = timezone(timedelta(hours=7))

def get_now_wib():
    return datetime.now(timezone.utc).astimezone(WIB)

# --- 3. UI KASIR (Logika Produk & Label Terpisah) ---
def cashier_ui():
    st.header(f"🛒 Terminal Kasir: {st.session_state.username}")
    now_wib = get_now_wib()
    
    if "cart" not in st.session_state: st.session_state.cart = []

    # Ambil data terbaru dari DB
    df_p = con.execute("SELECT * FROM produk").df()
    df_l = con.execute("SELECT * FROM labels").df()

    col_in, col_cart = st.columns([1, 2])

    with col_in:
        st.subheader("📝 Input Pesanan")
        if not df_p.empty:
            # Pilih Produk
            p_name = st.selectbox("Pilih Produk", sorted(df_p['nama_produk'].unique()))
            p_info = df_p[df_p['nama_produk'] == p_name].iloc[0]
            
            # Filter label secara otomatis berdasarkan kategori produk terpilih
            available_labels = df_l[df_l['kategori_terkait'] == p_info['kategori']]
            
            # Pilihan Opsi (Label)
            selected_opsi = st.multiselect(
                f"Opsi Tambahan ({p_info['kategori']})", 
                available_labels['nama_label'].tolist(),
                help=f"Opsi ini hanya muncul untuk kategori {p_info['kategori']}"
            )
            
            qty = st.number_input("Jumlah", min_value=1, step=1)

            # Kalkulasi Harga Dinamis (Harga Dasar + Total Harga Label)
            harga_label = available_labels[available_labels['nama_label'].isin(selected_opsi)]['harga_tambahan'].sum()
            harga_satuan_total = p_info['harga'] + harga_label

            st.info(f"Harga Satuan: Rp{harga_satuan_total:,.0f} (Dasar: Rp{p_info['harga']:,.0f})")

            if st.button("➕ Tambah ke Keranjang", use_container_width=True):
                if p_info['stok'] >= qty:
                    st.session_state.cart.append({
                        "id_p": int(p_info['id']),
                        "nama": p_name,
                        "opsi": ", ".join(selected_opsi) if selected_opsi else "-",
                        "qty": int(qty),
                        "harga": float(harga_satuan_total),
                        "subtotal": float(harga_satuan_total * qty)
                    })
                    st.rerun()
                else:
                    st.error(f"Stok Kurang! Sisa stok: {p_info['stok']}")
        else:
            st.warning("Data produk masih kosong. Hubungi Admin.")

    with col_cart:
        st.subheader("🛒 Keranjang")
        if st.session_state.cart:
            df_cart = pd.DataFrame(st.session_state.cart)
            st.table(df_cart[['nama', 'opsi', 'qty', 'subtotal']])
            total_akhir = df_cart['subtotal'].sum()
            st.write(f"## TOTAL: Rp{total_akhir:,.0f}")
            
            c1, c2 = st.columns(2)
            if c1.button("🗑️ Kosongkan", use_container_width=True):
                st.session_state.cart = []
                st.rerun()
                
            if c2.button("✅ SELESAIKAN", type="primary", use_container_width=True):
                id_tx = now_wib.strftime("%Y%m%d%H%M%S")
                for i in st.session_state.cart:
                    # Simpan ke tabel transaksi
                    con.execute("INSERT INTO transaksi VALUES (?, ?, ?, ?, ?, ?, ?)",
                                [id_tx, i['nama'], i['qty'], i['subtotal'], st.session_state.username, now_wib.replace(tzinfo=None), i['opsi']])
                    # Potong stok produk dasar
                    con.execute("UPDATE produk SET stok = stok - ? WHERE id = ?", [i['qty'], i['id_p']])
                
                st.session_state.cart = []
                st.success(f"Transaksi {id_tx} Berhasil!")
                st.balloons()
                st.rerun()

# --- 4. UI ADMIN (Full Dashboard & CRUD) ---
def admin_ui():
    now_wib = get_now_wib()
    st.title("🏗️ Panel Kendali Admin")
    
    menu = st.sidebar.selectbox("Pilih Menu", ["📊 Dashboard", "📦 Produk Dasar", "🏷️ Manajemen Label", "📜 Riwayat Transaksi"])

    # --- MENU: DASHBOARD ---
    if menu == "📊 Dashboard":
        st.subheader("Statistik Penjualan")
        today = now_wib.strftime('%Y-%m-%d')
        
        # Metrik Omset
        res_today = con.execute("SELECT SUM(total_harga) FROM transaksi WHERE CAST(waktu AS DATE) = ?", [today]).fetchone()
        omset_today = res_today[0] if res_today[0] else 0
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Omset Hari Ini", f"Rp{omset_today:,.0f}")
        
        # Grafik Omset per Waktu
        df_tx = con.execute("SELECT * FROM transaksi").df()
        if not df_tx.empty:
            df_tx['waktu'] = pd.to_datetime(df_tx['waktu'])
            df_daily = df_tx.groupby(df_tx['waktu'].dt.date)['total_harga'].sum().reset_index()
            fig = px.bar(df_daily, x='waktu', y='total_harga', title="Tren Penjualan Harian", color_discrete_sequence=['#00CC96'])
            st.plotly_chart(fig, use_container_width=True)
            
            # Produk Terlaris
            df_best = df_tx.groupby('nama_produk')['qty'].sum().reset_index().sort_values('qty', ascending=False)
            fig_best = px.pie(df_best, values='qty', names='nama_produk', title="Proporsi Produk Terjual")
            st.plotly_chart(fig_best, use_container_width=True)
        else:
            st.info("Belum ada data transaksi untuk dianalisis.")

    # --- MENU: PRODUK ---
    elif menu == "📦 Produk Dasar":
        st.subheader("Daftar Produk Dasar")
        df_p = con.execute("SELECT * FROM produk ORDER BY id DESC").df()
        st.dataframe(df_p, use_container_width=True, hide_index=True)
        
        with st.expander("➕ Tambah Produk Baru"):
            with st.form("f_add_p", clear_on_submit=True):
                n = st.text_input("Nama Produk (Tanpa keterangan opsi)")
                k = st.selectbox("Kategori", ["Minuman", "Makanan", "Snack", "Lainnya"])
                h = st.number_input("Harga Dasar", min_value=0, step=1000)
                s = st.number_input("Stok Awal", min_value=0, step=1)
                if st.form_submit_button("Simpan Produk"):
                    nid = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM produk").fetchone()[0]
                    con.execute("INSERT INTO produk VALUES (?,?,?,?,?)", [nid, n, k, h, s])
                    st.success("Produk disimpan!")
                    st.rerun()

        with st.expander("🗑️ Hapus Produk"):
            del_id = st.number_input("Masukkan ID Produk", min_value=1, step=1)
            if st.button("Hapus Permanen", type="secondary"):
                con.execute("DELETE FROM produk WHERE id=?", [del_id])
                st.rerun()

    # --- MENU: LABEL/OPSI ---
    elif menu == "🏷️ Manajemen Label":
        st.subheader("Pengaturan Label per Kategori")
        st.caption("Contoh: Label 'Dingin' hanya akan muncul untuk produk kategori 'Minuman'.")
        
        df_l = con.execute("SELECT * FROM labels").df()
        st.dataframe(df_l, use_container_width=True, hide_index=True)

        with st.form("f_add_l", clear_on_submit=True):
            col1, col2, col3 = st.columns(3)
            nl = col1.text_input("Nama Opsi (Contoh: Pedas)")
            kl = col2.selectbox("Untuk Kategori", ["Minuman", "Makanan", "Snack", "Lainnya"])
            hl = col3.number_input("Biaya Tambah (Rp)", min_value=0, step=500)
            if st.form_submit_button("Tambah Label"):
                nid = con.execute("SELECT COALESCE(MAX(id),0)+1 FROM labels").fetchone()[0]
                con.execute("INSERT INTO labels VALUES (?,?,?,?)", [nid, nl, kl, hl])
                st.rerun()
        
        st.info("💡 Tip: Gunakan biaya tambahan Rp0 jika opsi tersebut tidak menambah harga (seperti 'Hangat' atau 'Original').")

    # --- MENU: TRANSAKSI ---
    elif menu == "📜 Riwayat Transaksi":
        st.subheader("Data Riwayat Penjualan")
        df_tx = con.execute("SELECT * FROM transaksi ORDER BY waktu DESC").df()
        if not df_tx.empty:
            df_tx['waktu'] = pd.to_datetime(df_tx['waktu']).dt.strftime('%d/%m/%Y %H:%M:%S')
            st.dataframe(df_tx, use_container_width=True)
            
            csv = df_tx.to_csv(index=False).encode('utf-8')
            st.download_button("📥 Download Data (CSV)", data=csv, file_name="riwayat_kasir.csv", mime="text/csv")
        else:
            st.info("Belum ada transaksi.")

# --- 5. LOGIKA AUTH & MAIN ---
if "logged_in" not in st.session_state:
    st.title("🔐 Sistem Kasir Pro")
    with st.form("login"):
        u = st.text_input("Username")
        p = st.text_input("Password", type="password")
        if st.form_submit_button("Masuk"):
            res = con.execute("SELECT role FROM users WHERE username=? AND password=?", [u, p]).fetchone()
            if res:
                st.session_state.logged_in = True
                st.session_state.username = u
                st.session_state.role = res[0]
                st.rerun()
            else:
                st.error("Akun tidak ditemukan!")
else:
    st.sidebar.markdown(f"User: **{st.session_state.username}**")
    st.sidebar.markdown(f"Role: `{st.session_state.role}`")
    if st.sidebar.button("🚪 Keluar"):
        st.session_state.clear()
        st.rerun()
    
    if st.session_state.role == "admin":
        admin_ui()
    else:
        cashier_ui()