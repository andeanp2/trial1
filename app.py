import streamlit as st
import duckdb

# KONFIGURASI AMAN
# Mengambil token dari "brankas" Secrets (bukan diketik langsung)
TOKEN = st.secrets["MOTHERDUCK_TOKEN"]

# Koneksi ke MotherDuck
@st.cache_resource
def get_connection():
        # Mengambil token dari Secrets Streamlit Cloud
    token_auth = st.secrets["MOTHERDUCK_TOKEN"]
    # Cara koneksi yang lebih stabil
    return duckdb.connect(f"md:my_db?motherduck_token={token_auth}")
con = get_connection()

st.title("🚀 Kasir v1.0")

# Ambil data produk terbaru
df = con.execute("SELECT * FROM produk").df()

tab1, tab2 = st.tabs(["Kasir", "Update Stok"])

with tab1:
    st.header("🛒 Input Transaksi")
    with st.form("form_kasir"):
        item = st.selectbox("Pilih Produk", df['nama_produk'])
        jumlah = st.number_input("Jumlah", min_value=1, step=1)
        submit = st.form_submit_button("Kurangi Stok")

        if submit:
            # Cari stok terakhir
            stok_skrg = df[df['nama_produk'] == item]['stok'].values[0]
            if stok_skrg >= jumlah:
                new_stok = stok_skrg - jumlah
                con.execute(f"UPDATE produk SET stok = {new_stok} WHERE nama_produk = '{item}'")
                st.success(f"Berhasil! Stok {item} berkurang. Sisa: {new_stok}")
                st.rerun()
            else:
                st.error("Stok Habis/Kurang!")

with tab2:
    st.header("📦 Inventaris Admin")
    st.dataframe(df, use_container_width=True)
    # Form tambah stok manual
    with st.expander("Tambah Stok Masuk"):
        id_p = st.text_input("Masukkan ID Produk")
        tambah = st.number_input("Jumlah Tambahan", min_value=1)
        if st.button("Update"):
            con.execute(f"UPDATE produk SET stok = stok + {tambah} WHERE id_produk = '{id_p}'")
            st.success("Stok diperbarui!")
            st.rerun()