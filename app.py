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
    try:
        df_produk = con.execute("SELECT * FROM produk").df()
    except:
        df_produk = pd.DataFrame() # Jika error, buat dataframe kosong

    # --- TAMBAHKAN BARIS INI UNTUK DEBUG ---
    st.write("Debug: Jumlah baris di database =", len(df_produk))
    if not df_produk.empty:
        st.write("Daftar kolom:", df_produk.columns.tolist())
    # ---------------------------------------

    if df_produk.empty:
        st.warning("Data produk masih kosong. Silakan hubungi Admin untuk isi stok.")
        return

    # 3. LANJUT KE UI INPUT (Keranjang dll)
    # ... sisa kode kasir Anda ...

    # 3. Cek apakah database kosong
    if df_produk.empty:
        st.warning("Data produk masih kosong. Silakan hubungi Admin untuk isi stok.")
        return # Berhenti di sini jika tidak ada produk

    # --- SISA KODE (Layout Kolom Input & Keranjang) TETAP SAMA ---
    col_input, col_cart = st.columns([1, 2])
    
    with col_input:
        st.subheader("Pilih Barang")
        
        # Mulai Form
        with st.form("form_add_to_cart", clear_on_submit=True):
            item_pilih = st.selectbox("Produk", df_produk['nama_produk'].tolist())
            qty_pilih = st.number_input("Jumlah", min_value=1, step=1)
            
            # --- INI BARIS YANG HILANG/BELUM ADA ---
            btn_add = st.form_submit_button("➕ Tambah ke Keranjang")
            # ----------------------------------------

            # Logika saat tombol ditekan
            if btn_add:
                # Ambil data produk yang dipilih dari dataframe
                produk_data = df_produk[df_produk['nama_produk'] == item_pilih].iloc[0]
                
                # Cek apakah stok cukup
                if produk_data['stok'] >= qty_pilih:
                    # Bagian saat tombol "Tambah" diklik
                    st.session_state.cart.append({
                        "id": produk_data['id'],
                        "nama": item_pilih,
                        "harga": produk_data['harga'],
                        "qty": qty_pilih,
                        "subtotal": qty_pilih * produk_data['harga'] # Pastikan namanya 'subtotal'
                    })
                    st.success(f"Masuk keranjang: {item_pilih}")
                    st.rerun()
                else:
                    st.error(f"Stok tidak cukup! (Sisa: {produk_data['stok']})")

    with col_cart:
        st.subheader("Isi Keranjang")
        if st.session_state.cart:
            # --- TAMPILAN KERANJANG INTERAKTIF ---
            total_bayar = 0
            for i, barang in enumerate(st.session_state.cart):
                with st.container():
                    c1, c2, c3 = st.columns([3, 2, 1])
                    c1.write(f"**{barang['nama']}** \n{barang['qty']} x Rp{barang['harga']:,.0f}")
        
                    # BARIS YANG ERROR TADI: Pastikan pakai ['subtotal']
                    c2.write(f"  \nRp{barang['subtotal']:,.0f}") 
        
                    if c3.button("🗑️", key=f"del_{i}"):
                        st.session_state.cart.pop(i)
                        st.rerun()
            
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
                    wib_skrg = get_wib_now()
                    # 1. Ambil stok lama sebelum dikurangi
                    stok_lama = con.execute("SELECT stok FROM produk WHERE nama_produk = ?", [b['nama']]).fetchone()[0]
                    stok_baru = stok_lama - b['qty']

                    # 2. Update stok dan waktu di tabel produk
                    con.execute("""
                        UPDATE produk 
                        SET stok = ?, terakhir_diupdate = ? 
                        WHERE nama_produk = ?
                    """, [stok_baru, wib_skrg, b['nama']])

                    # 3. Catat ke log_stok (Audit Trail)
                    max_id_log = con.execute("SELECT COALESCE(MAX(id_log), 0) + 1 FROM log_stok").fetchone()[0]
                    con.execute("""
                        INSERT INTO log_stok VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, [int(max_id_log), None, b['nama'], int(stok_lama), int(stok_baru), "Transaksi Kasir", wib_skrg])
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
        
        df_produk = con.execute("SELECT * FROM produk ORDER BY id ASC").df()
        st.dataframe(df_produk, use_container_width=True, hide_index=True)
        
        # Tambahkan "🗑️ Hapus Produk" ke dalam list Tabs
        tab1, tab2, tab3, tab4 = st.tabs(["➕ Tambah Baru", "✏️ Edit Produk", "🔄 Update Stok Cepat", "🗑️ Hapus Produk"])
        
        with tab1:
            with st.form("form_tambah"):
                st.write("### Tambah Produk Baru")
                n_baru = st.text_input("Nama Produk")
                h_baru = st.number_input("Harga", min_value=0, step=500)
                s_baru = st.number_input("Stok Awal", min_value=0, step=1)
                
                if st.form_submit_button("Simpan Produk"):
                    # --- CEK DUPLIKAT NAMA ---
                    cek_nama = con.execute("SELECT COUNT(*) FROM produk WHERE lower(nama_produk) = lower(?)", [n_baru]).fetchone()[0]
                    
                    if not n_baru:
                        st.error("Nama produk tidak boleh kosong!")
                    elif cek_nama > 0:
                        st.warning(f"Gagal! Produk dengan nama '{n_baru}' sudah ada di database.")
                    else:
                        max_id = con.execute("SELECT COALESCE(MAX(id), 0) + 1 FROM produk").fetchone()[0]
                        con.execute("INSERT INTO produk VALUES (?, ?, ?, ?)", [int(max_id), n_baru, h_baru, s_baru])
                        st.success(f"Berhasil menambah {n_baru}!")
                        st.rerun()

        with tab2:
            st.write("### Edit Detail Produk")
            if not df_produk.empty:
                pilihan_nama = st.selectbox("Pilih Produk yang akan diubah:", df_produk['nama_produk'])
                data_lama = df_produk[df_produk['nama_produk'] == pilihan_nama].iloc[0]
                
                with st.form("form_edit_detail"):
                    nama_edit = st.text_input("Nama Produk", value=data_lama['nama_produk'])
                    harga_edit = st.number_input("Harga Jual", value=float(data_lama['harga']), step=500.0)
                    stok_edit = st.number_input("Jumlah Stok", value=int(data_lama['stok']), step=1)
                    
                    if st.form_submit_button("Simpan Perubahan"):
                        # --- CEK DUPLIKAT NAMA (Kecuali ID produk ini sendiri) ---
                        cek_nama_edit = con.execute("""
                            SELECT COUNT(*) FROM produk 
                            WHERE lower(nama_produk) = lower(?) AND id != ?
                        """, [nama_edit, int(data_lama['id'])]).fetchone()[0]
                        
                        if cek_nama_edit > 0:
                            st.warning(f"Gagal! Nama '{nama_edit}' sudah digunakan oleh produk lain.")
                        else:
                            con.execute("""
                                UPDATE produk SET nama_produk = ?, harga = ?, stok = ? WHERE id = ?
                            """, [str(nama_edit), float(harga_edit), int(stok_edit), int(data_lama['id'])])
                            st.success("Perubahan disimpan!")
                            st.rerun()

        with tab3:
            # Fitur update stok cepat (tambah/kurang) yang sudah kita buat sebelumnya
            with st.form("form_update_stok"):
                st.write("### Update Stok Cepat (+/-)")
                prod_target = st.selectbox("Pilih Produk", df_produk['nama_produk'] if not df_produk.empty else ["Kosong"])
                qty_ubah = st.number_input("Jumlah Perubahan", step=1)
                if st.form_submit_button("Update Stok"):
                    wib_skrg = get_wib_now()
                    row = con.execute("SELECT id, stok FROM produk WHERE nama_produk = ?", [str(prod_target)]).fetchone()
                    stok_awal = row[1]
                    stok_akhir = stok_awal + int(qty_ubah)

                    con.execute("""
                        UPDATE produk SET stok = ?, terakhir_diupdate = ? WHERE nama_produk = ?
                    """, [stok_akhir, wib_skrg, str(prod_target)])

                    # Catat log
                    max_id_log = con.execute("SELECT COALESCE(MAX(id_log), 0) + 1 FROM log_stok").fetchone()[0]
                    con.execute("""
                        INSERT INTO log_stok VALUES (?, ?, ?, ?, ?, ?, ?)
                    """, [int(max_id_log), int(row[0]), str(prod_target), int(stok_awal), int(stok_akhir), "Update Manual Admin", wib_skrg])

        with tab4:
            st.write("### ⚠️ Hapus Produk dari Sistem")
            if not df_produk.empty:
                # Pilih produk yang akan dihapus
                prod_hapus = st.selectbox("Pilih produk yang ingin dihapus secara permanen:", df_produk['nama_produk'], key="sb_hapus")
                data_target = df_produk[df_produk['nama_produk'] == prod_hapus].iloc[0]
                
                st.warning(f"Apakah Anda yakin ingin menghapus **{prod_hapus}**? Tindakan ini tidak dapat dibatalkan.")
                
                # Cek apakah produk ini punya riwayat transaksi (opsional, untuk informasi admin)
                jml_tx = con.execute("SELECT COUNT(*) FROM transaksi WHERE nama_produk = ?", [prod_hapus]).fetchone()[0]
                if jml_tx > 0:
                    st.info(f"Catatan: Produk ini memiliki {jml_tx} riwayat transaksi. Menghapus produk tidak akan menghapus data transaksi lama, tapi produk ini tidak akan muncul lagi di menu kasir.")

                # Konfirmasi dengan checkbox atau input teks untuk keamanan
                konfirmasi_hapus = st.checkbox(f"Saya yakin ingin menghapus {prod_hapus}")
                
                if st.button("🔥 Hapus Produk Sekarang"):
                    if konfirmasi_hapus:
                        con.execute("DELETE FROM produk WHERE id = ?", [int(data_target['id'])])
                        st.success(f"Produk '{prod_hapus}' telah berhasil dihapus.")
                        st.rerun()
                    else:
                        st.error("Silakan centang kotak konfirmasi terlebih dahulu!")
            else:
                st.info("Tidak ada produk yang bisa dihapus.")            

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