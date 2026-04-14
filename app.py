import streamlit as st
import duckdb
import pandas as pd
import pytz 
from datetime import datetime

# Fungsi untuk mendapatkan waktu WIB sekarang
def get_wib_now():
    tz_wib = pytz.timezone('Asia/Jakarta')
    return datetime.now(tz_wib)

# --- KONFIGURASI HALAMAN ---
st.set_page_config(page_title="Sistem Kasir Pro v1", layout="wide")

# --- KONEKSI DATABASE ---
@st.cache_resource
def get_connection():
    TOKEN = st.secrets["MOTHERDUCK_TOKEN"]
    return duckdb.connect(f"md:my_db?motherduck_token={TOKEN}")

con = get_connection()

# --- FUNGSI LOGIN ---
def login_ui():
    st.title("🔐 Login Sistem Kasir")
    with st.form("login_form"):
        user = st.text_input("Username")
        pw = st.text_input("Password", type="password")
        submit = st.form_submit_button("Login")
        
        if submit:
            res = con.execute("SELECT role FROM users WHERE username = ? AND password = ?", [user, pw]).fetchone()
            if res:
                st.session_state.logged_in = True
                st.session_state.username = user
                st.session_state.role = res[0]
                st.rerun()
            else:
                st.error("Username atau Password salah!")

# --- HALAMAN KASIR (INPUT TRANSAKSI) ---
def cashier_ui():
    st.header(f"🛒 Kasir: {st.session_state.username}")
    
    if "cart" not in st.session_state:
        st.session_state.cart = []

    df_produk = con.execute("SELECT * FROM produk").df()

    col_input, col_cart = st.columns([1, 2])

    with col_input:
        st.subheader("Pilih Barang")
        with st.form("form_add_to_cart", clear_on_submit=True):
            item_pilih = st.selectbox("Produk", df_produk['nama_produk'])
            qty_pilih = st.number_input("Jumlah", min_value=1, step=1)
            btn_add = st.form_submit_button("➕ Tambah")

            if btn_add:
                row = df_produk[df_produk['nama_produk'] == item_pilih].iloc[0]
                if int(row['stok']) >= qty_pilih:
                    st.session_state.cart.append({
                        "nama": item_pilih, 
                        "qty": int(qty_pilih),
                        "harga": float(row['harga']), 
                        "subtotal": float(row['harga'] * qty_pilih)
                    })
                    st.toast(f"{item_pilih} ditambah!")
                else:
                    st.error("Stok habis!")

    with col_cart:
        st.subheader("Isi Keranjang")
        if st.session_state.cart:
            # --- TAMPILAN KERANJANG INTERAKTIF ---
            total_bayar = 0
            for i, barang in enumerate(st.session_state.cart):
                c1, c2, c3 = st.columns([3, 2, 1])
                c1.write(f"**{barang['nama']}** \n{barang['qty']} x Rp{barang['harga']:,.0f}")
                c2.write(f"  \nRp{barang['subtotal']:,.0f}")
                # Tombol hapus spesifik per baris
                if c3.button("🗑️", key=f"del_{i}"):
                    st.session_state.cart.pop(i)
                    st.rerun()
                total_bayar += barang['subtotal']
            
            st.divider()
            st.write(f"### TOTAL: Rp{total_bayar:,.0f}")
            
            c1, c2 = st.columns(2)
            if c1.button("🧹 Kosongkan"):
                st.session_state.cart = []
                st.rerun()

            if c2.button("✅ PROSES TRANSAKSI"):
                wib_now = get_wib_now() # Ambil jam Jakarta
                id_tx = wib_now.strftime("%Y%m%d%H%M%S")
                waktu_str = wib_now.strftime("%Y-%m-%d %H:%M:%S")
                tgl_hari_ini = wib_now.strftime("%Y-%m-%d") # Untuk filter history nanti
                for b in st.session_state.cart:
                    con.execute("UPDATE produk SET stok = stok - ? WHERE nama_produk = ?", [b['qty'], b['nama']])
                    con.execute("""
                        INSERT INTO transaksi (id_transaksi, nama_produk, jumlah, total_harga, kasir, waktu) 
                        VALUES (?, ?, ?, ?, ?, ?)
                    """, [id_tx, b['nama'], b['qty'], b['subtotal'], str(st.session_state.username), waktu_str])
                
                st.success("Transaksi Berhasil!")
                st.session_state.cart = []
                st.rerun()
        else:
            st.info("Keranjang kosong.")

    # (Bagian Riwayat Harian tetap di bawah sini)

    # --- FITUR BARU: RIWAYAT HARIAN KASIR ---
    def cashier_ui():
    # ... (kode keranjang belanja Anda) ...
        # Baris ini harus menjorok ke dalam (4 spasi atau 1 tab)
        tz_wib = pytz.timezone('Asia/Jakarta')
        return datetime.now(tz_wib)

    st.divider()
    
    # 1. BUAT DULU UI UNTUK LIMIT
    col_head, col_opt = st.columns([2, 2])
    with col_head:
        st.subheader("📜 Riwayat Struk Hari Ini")
    
    with col_opt:
        opsi_limit = [5, 10, 20, 50, "Semua"]
        pilihan_limit = st.selectbox("Tampilkan maksimal:", opsi_limit, index=1)
        
        # DISINI VARIABEL limit_sql DIBUAT
        if pilihan_limit == "Semua":
            limit_sql = ""
        else:
            limit_sql = f"LIMIT {pilihan_limit}"

    # 2. AMBIL TANGGAL WIB
    tgl_wib_ini = get_wib_now().strftime("%Y-%m-%d")

    # 3. BARU GUNAKAN limit_sql DI DALAM QUERY
    query_tabel = f"""
        SELECT 
            id_transaksi AS "ID Struk", 
            MAX(waktu) AS "Jam", 
            SUM(total_harga) AS "Total Belanja",
            COUNT(nama_produk) AS "Jenis Barang"
        FROM transaksi 
        WHERE kasir = ? AND CAST(waktu AS DATE) = ? 
        GROUP BY id_transaksi
        ORDER BY "Jam" DESC
        {limit_sql}
    """
    
    # 4. EKSEKUSI
    df_struk = con.execute(query_tabel, [str(st.session_state.username), tgl_wib_ini]).df()
    
    # ... (tampilkan tabel) ...
    if not df_struk.empty:
        # Hitung omzet harian (selalu hitung total hari ini, tidak terpengaruh limit dropdown)
        total_omzet = con.execute(
            "SELECT SUM(total_harga) FROM transaksi WHERE kasir = ? AND CAST(waktu AS DATE) = CURRENT_DATE",
            [str(st.session_state.username)]
        ).fetchone()[0] or 0
        
        st.metric("Total Omzet Anda Hari Ini", f"Rp{total_omzet:,.0f}")
        st.caption(f"Menampilkan {pilihan_limit} transaksi terbaru hari ini.")
        
        # Tabel Interaktif
        st.dataframe(
            df_struk.style.format({"Total Belanja": "Rp{:,.0f}", "Jam": lambda t: t.strftime('%H:%M:%S')}),
            use_container_width=True,
            hide_index=True
        )
        
        # Detail Struk
        with st.expander("🔍 Cek Detail Barang per Struk"):
            struk_pilihan = st.selectbox("Pilih ID Struk:", df_struk["ID Struk"])
            if struk_pilihan:
                df_det = con.execute(
                    "SELECT nama_produk AS Produk, jumlah AS Qty, total_harga AS Subtotal FROM transaksi WHERE id_transaksi = ?", 
                    [struk_pilihan]
                ).df()
                st.table(df_det)
    else:
        st.info("Belum ada transaksi yang tercatat hari ini.")

# --- HALAMAN ADMIN (UPDATE STOK & DASHBOARD) ---
def admin_ui():
    now = get_wib_now()
    st.title("🏗️ Panel Admin")
    menu_admin = st.sidebar.selectbox("Menu Admin", ["Dashboard Utama", "Manajemen Stok", "Data Transaksi"])
    
    # --- DI DALAM admin_ui() ---
    if menu_admin == "Dashboard Utama":
        st.subheader("📊 Ringkasan Bisnis")
        col1, col2 = st.columns(2)
    
        # 1. Ambil Pendapatan (Cara Aman)
        res_p = con.execute("SELECT SUM(total_harga) FROM transaksi").fetchone()
        # Jika res_p ada dan isinya bukan None, ambil index [0]. Jika tidak, beri 0.
        total_penjualan = res_p[0] if res_p and res_p[0] is not None else 0
    
        # 2. Ambil Total Stok (Cara Aman)
        res_s = con.execute("SELECT SUM(stok) FROM produk").fetchone()
        total_stok = res_s[0] if res_s and res_s[0] is not None else 0
    
        col1.metric("Total Pendapatan", f"Rp{total_penjualan:,.0f}")
        col2.metric("Total Stok Barang", f"{total_stok} unit")
        
        # --- Grafik Penjualan (Hanya muncul jika ada data) ---
        df_tx = con.execute("SELECT * FROM transaksi").df()
        if not df_tx.empty:
            fig = px.bar(df_tx, x='waktu', y='total_harga', title="Tren Penjualan", color='nama_produk')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("Belum ada data transaksi untuk ditampilkan di grafik.")

    elif menu_admin == "Manajemen Stok":
        st.subheader("📦 Manajemen Gudang & Stok")
        
        # Ambil data produk terbaru
        df_produk = con.execute("SELECT * FROM produk ORDER BY id ASC").df()
        st.dataframe(df_produk, use_container_width=True, hide_index=True)
        
        # TAB untuk memisahkan aksi agar rapi
        tab1, tab2, tab3 = st.tabs(["➕ Tambah Baru", "✏️ Edit Produk", "🔄 Update Stok Cepat"])
        
        with tab1:
            with st.form("form_tambah"):
                st.write("### Tambah Produk Baru")
                n_baru = st.text_input("Nama Produk")
                h_baru = st.number_input("Harga", min_value=0, step=500)
                s_baru = st.number_input("Stok Awal", min_value=0, step=1)
                if st.form_submit_button("Simpan Produk"):
                    max_id = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM produk").fetchone()[0]
                    con.execute("INSERT INTO produk VALUES (?, ?, ?, ?)", [int(max_id), n_baru, h_baru, s_baru])
                    st.success("Produk berhasil ditambah!")
                    st.rerun()

        with tab2:
            st.write("### Edit Detail Produk")
            if not df_produk.empty:
                # Pilih produk yang mau diedit
                pilihan_nama = st.selectbox("Pilih Produk yang akan diubah:", df_produk['nama_produk'])
                data_lama = df_produk[df_produk['nama_produk'] == pilihan_nama].iloc[0]
                
                # Form Edit dengan nilai awal dari data lama
                with st.form("form_edit_detail"):
                    nama_edit = st.text_input("Nama Produk", value=data_lama['nama_produk'])
                    harga_edit = st.number_input("Harga Jual", value=float(data_lama['harga']), step=500.0)
                    stok_edit = st.number_input("Jumlah Stok", value=int(data_lama['stok']), step=1)
                    
                    if st.form_submit_button("Simpan Perubahan"):
                        con.execute("""
                            UPDATE produk 
                            SET nama_produk = ?, harga = ?, stok = ? 
                            WHERE id = ?
                        """, [str(nama_edit), float(harga_edit), int(stok_edit), int(data_lama['id'])])
                        
                        st.success(f"Berhasil memperbarui {pilihan_nama}!")
                        st.rerun()
            else:
                st.info("Belum ada produk untuk diedit.")

        with tab3:
            # Fitur update stok cepat (tambah/kurang) yang sudah kita buat sebelumnya
            with st.form("form_update_stok"):
                st.write("### Update Stok Cepat (+/-)")
                prod_target = st.selectbox("Pilih Produk", df_produk['nama_produk'] if not df_produk.empty else ["Kosong"])
                qty_ubah = st.number_input("Jumlah Perubahan", step=1)
                if st.form_submit_button("Update Stok"):
                    con.execute("UPDATE produk SET stok = stok + ? WHERE nama_produk = ?", [int(qty_ubah), str(prod_target)])
                    st.success("Stok berhasil diperbarui!")
                    st.rerun()

    elif menu_admin == "Data Transaksi":
        st.subheader("📝 Histori Transaksi Lengkap")
        df_tx = con.execute("SELECT * FROM transaksi ORDER BY waktu DESC").df()
        st.dataframe(df_tx, use_container_width=True)

# --- LOGIKA UTAMA ---
if "logged_in" not in st.session_state:
    login_ui()
else:
    # Sidebar untuk logout
    st.sidebar.write(f"Logged in as: **{st.session_state.username}** ({st.session_state.role})")
    if st.sidebar.button("Logout"):
        del st.session_state.logged_in
        st.rerun()
    
    # Render UI berdasarkan role
    if st.session_state.role == "admin":
        admin_ui()
    else:
        cashier_ui()