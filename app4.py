import streamlit as st
import sqlite3
import pandas as pd
import hashlib
import datetime
from datetime import timedelta
import time
import re
import os

# ==========================================
# 0. CONFIG & CSS
# ==========================================
st.set_page_config(page_title="SmartStudio Ultimate", layout="wide", page_icon="🎹")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
    .stChatMessage { background-color: #1e293b; border: 1px solid #334155; border-radius: 12px; }
    div[data-testid="stMetric"] { background-color: #1e293b; padding: 20px; border-radius: 10px; border-left: 4px solid #3b82f6; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }
    h1, h2, h3 { color: #f8fafc !important; }
    .stButton button { background-color: #3b82f6; color: white; border-radius: 8px; font-weight: 600; }
    [data-testid="stDataFrame"] { border-radius: 8px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)

# Nama Database
DB_FILE = 'smartstudio_v16.db'

# ==========================================
# 1. DATABASE SYSTEM
# ==========================================
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Tables
    c.execute('''CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password_hash TEXT)''')
    
    # UPDATE: Menambahkan kolom no_hp
    c.execute('''CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, customer_name TEXT, no_hp TEXT, date TEXT, 
        start_hour INTEGER, duration INTEGER, instruments TEXT, price REAL, status TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS inventory (id INTEGER PRIMARY KEY AUTOINCREMENT, item_name TEXT UNIQUE)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS courses (
        id INTEGER PRIMARY KEY AUTOINCREMENT, student_name TEXT, instrument TEXT, 
        schedule_day TEXT, schedule_time TEXT, duration INTEGER, status TEXT)''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, action TEXT, details TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')

    # Seed Admin (Pass: Hanateam123)
    try: c.execute("INSERT INTO users VALUES (?, ?)", ('admin', hashlib.sha256("Hanateam123".encode()).hexdigest()))
    except: pass

    # Seed Inventory Default
    c.execute("SELECT count(*) FROM inventory")
    if c.fetchone()[0] == 0:
        items = [('gitar elektrik',), ('bass',), ('drum set',), ('keyboard',), ('mic wireless',)]
        c.executemany("INSERT INTO inventory (item_name) VALUES (?)", items)
        conn.commit()
        
    conn.commit()
    return conn

def log_action(conn, action, details):
    wib = datetime.timezone(datetime.timedelta(hours=7))
    now_wib = datetime.datetime.now(wib).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("INSERT INTO audit_logs (action, details, timestamp) VALUES (?, ?, ?)", 
                 (action, details, now_wib))
    conn.commit()

# ==========================================
# 2. LOGIC SYSTEM
# ==========================================
def calculate_price(start, duration):
    base = 50000
    peak_hours = {18, 19, 20, 21, 22}
    rental_hours = set(range(start, start + duration))
    is_peak = not rental_hours.isdisjoint(peak_hours)
    total = (base * duration) * (1.2 if is_peak else 1.0)
    return total, is_peak

def check_conflict(conn, date_str, start, duration, exclude_id=None):
    c = conn.cursor()
    if exclude_id:
        c.execute("SELECT id, start_hour, duration FROM bookings WHERE date = ? AND id != ?", (date_str, exclude_id))
    else:
        c.execute("SELECT id, start_hour, duration FROM bookings WHERE date = ?", (date_str,))
    
    for _, b_start, b_dur in c.fetchall():
        if (start < b_start + b_dur) and (start + duration > b_start): return True
    return False

# --- LOGIC LEVEL CUSTOMER BARU ---
def get_customer_stats(conn, no_hp):
    """Menghitung total jam terbang berdasarkan Nomor HP"""
    c = conn.cursor()
    # Pastikan no_hp ada di database sebelum query
    try:
        c.execute("SELECT SUM(duration) FROM bookings WHERE no_hp = ?", (no_hp,))
        result = c.fetchone()[0]
        return result if result else 0
    except:
        return 0

def get_level_info(total_jam):
    """Menentukan Level dan Diskon berdasarkan Total Jam"""
    if total_jam >= 50:
        return "🎸 Rockstar", "Diskon 15% booking selanjutnya!", 1.0, "gold"
    elif total_jam >= 20:
        return "🎹 Pro Musician", "Diskon 10% booking selanjutnya!", 0.7, "orange"
    elif total_jam >= 5:
        return "🥁 Garage Band", "Diskon 5% (Member setia)", 0.4, "blue"
    else:
        return "🎤 Newcomer", "Main 5 jam lagi untuk dapat diskon!", 0.1, "gray"

def parse_intent(user_input, inventory_list):
    txt = user_input.lower()
    res = {'intent': 'unknown', 'date': None, 'time': None, 'dur': None, 'found_items': []}
    
    if 'batal' in txt or 'cancel' in txt or 'gak jadi' in txt: res['intent'] = 'cancel'
    elif 'ulang' in txt or 'reset' in txt or 'salah' in txt: res['intent'] = 'reset'
    elif 'reschedule' in txt or 'ganti' in txt or 'ubah' in txt: res['intent'] = 'reschedule'
    elif any(x in txt for x in ['booking', 'sewa', 'pesan']): res['intent'] = 'booking'
    
    clean_txt = txt 
    wib = datetime.timezone(datetime.timedelta(hours=7))
    today = datetime.datetime.now(wib).date()

    if 'hari ini' in txt: 
        res['date'] = today.strftime("%Y-%m-%d")
    elif 'besok' in txt: 
        res['date'] = (today + timedelta(days=1)).strftime("%Y-%m-%d")
    elif 'lusa' in txt: 
        res['date'] = (today + timedelta(days=2)).strftime("%Y-%m-%d")
    else:
        date_match = re.search(r'(tanggal|tgl)\s*(\d{1,2})', clean_txt)
        if date_match:
            try: 
                target_day = int(date_match.group(2))
                res['date'] = today.replace(day=target_day).strftime("%Y-%m-%d")
                clean_txt = clean_txt.replace(date_match.group(0), "")
            except: pass

    d_match = re.search(r'(\d+)\s*(jam|hour)', clean_txt)
    if d_match: 
        res['dur'] = int(d_match.group(1))
        clean_txt = clean_txt.replace(d_match.group(0), "")

    time_found = None
    match_explicit = re.search(r'(jam|pukul)\s*(\d{1,2})', clean_txt)
    if match_explicit: time_found = int(match_explicit.group(2))
        
    if time_found is None:
        match_col = re.search(r'(\d{1,2})[:.]\d{2}', clean_txt)
        if match_col: time_found = int(match_col.group(1))

    if time_found is None:
         match_suff = re.search(r'(\d{1,2})\s*(pagi|siang|sore|malam)?', clean_txt)
         if match_suff:
             h = int(match_suff.group(1))
             mod = match_suff.group(2)
             if mod in ['sore', 'malam'] and h <= 12: h += 12
             time_found = h
    
    if time_found is not None:
        if 8 <= time_found <= 23: res['time'] = time_found

    for item in inventory_list:
        if item in txt or (item.split()[0] in txt): 
             res['found_items'].append(item)
            
    return res

def finalize_booking(conn, bs):
    conflict = check_conflict(conn, bs['date'], bs['time'], bs['dur'])
    
    if conflict:
        msg = f"❌ Maaf Kak {bs['name']}, jam {bs['time']}:00 di tanggal {bs['date']} sudah penuh."
        return msg, False
    else:
        price, is_peak = calculate_price(bs['time'], bs['dur'])
        items_str = ", ".join(set(bs['items'])).title() if bs['items'] else "Standard Room"
        
        # Simpan No HP juga
        conn.execute('''INSERT INTO bookings (customer_name, no_hp, date, start_hour, duration, instruments, price, status) 
                        VALUES (?,?,?,?,?,?,?,?)''', 
                        (bs['name'], bs['phone'], bs['date'], bs['time'], bs['dur'], items_str, price, "Confirmed"))
        
        log_action(conn, "NEW_BOOKING", f"{bs['name']} ({bs['phone']}) - {bs['date']}")
        conn.commit()
        
        ticket_html = f"""
<div style="
    font-family: 'Courier New', Courier, monospace;
    background-color: #fffcf5; 
    color: #333;
    padding: 25px;
    max-width: 400px;
    margin: 10px auto;
    border: 2px solid #333;
    border-radius: 10px;
    box-shadow: 8px 8px 0px rgba(0,0,0,0.2);
    position: relative;
 ">
<div style="text-align: center; border-bottom: 2px dashed #333; padding-bottom: 15px; margin-bottom: 15px;">
<p style="margin: 0; font-weight: 900; letter-spacing: 2px; color: #000000 !important;">🎹 SMART STUDIO</h2>
<p style="margin: 5px 0 0; font-size: 12px; color: #000000;">DIGITAL RECEIPT TICKET</p>
<p style="margin: 0; font-size: 10px; color: #777;">ID: #{int(time.time())}</p>
</div>

<div style="font-size: 14px; line-height: 1.6;">
<div style="display: flex; justify-content: space-between;">
<span>👤 Nama:</span>
<strong>{bs['name']}</strong>
</div>
<div style="display: flex; justify-content: space-between;">
<span>📱 No HP:</span>
<strong>{bs['phone']}</strong>
</div>
<div style="display: flex; justify-content: space-between;">
<span>📅 Tgl:</span>
<strong>{bs['date']}</strong>
</div>
<div style="display: flex; justify-content: space-between;">
<span>⏰ Jam:</span>
<strong>{bs['time']}:00 WIB</strong>
</div>
<div style="display: flex; justify-content: space-between;">
<span>⏳ Durasi:</span>
<strong>{bs['dur']} Jam</strong>
</div>
<hr style="border: none; border-top: 1px dashed #bbb; margin: 10px 0;">
<div style="margin-bottom: 5px;">
<span>🎸 Alat:</span><br>
<span style="display: inline-block; background: #eee; padding: 2px 6px; border-radius: 4px; font-size: 12px;">{items_str}</span>
</div>
</div>

<div style="margin-top: 20px; border-top: 2px solid #333; padding-top: 10px; text-align: right;">
<p style="margin: 0; font-size: 12px;">Total Paid</p>
<p style="margin: 0; font-size: 28px; color: #000000;">Rp {price:,.0f}</h1>
</div>

<div style="margin-top: 15px; text-align: center; opacity: 0.7;">
<div style="height: 30px; background: repeating-linear-gradient(90deg, #333, #333 2px, transparent 2px, transparent 4px);"></div>
<p style="font-size: 10px; margin-top: 5px;">*Tunjukkan tiket ini ke Admin*</p>
</div>
</div>
"""
        
        msg = ticket_html
        return msg, True

def process_reschedule(conn, booking_id, new_date, new_time):
    c = conn.cursor()
    c.execute("SELECT customer_name, duration FROM bookings WHERE id=?", (booking_id,))
    row = c.fetchone()
    if not row: return "❌ Data tidak ditemukan.", False
    
    name, duration = row
    if check_conflict(conn, new_date, new_time, duration, exclude_id=booking_id):
        return f"❌ Gagal. Jam {new_time}:00 di tanggal {new_date} bentrok.", False
    
    new_price, _ = calculate_price(new_time, duration)
    conn.execute("UPDATE bookings SET date=?, start_hour=?, price=? WHERE id=?", (new_date, new_time, new_price, booking_id))
    log_action(conn, "RESCHEDULE", f"ID {booking_id} moved to {new_date}")
    conn.commit()
    
    return f"✅ **Reschedule Berhasil!** Jadwal baru Kak **{name}**: {new_date} jam {new_time}:00.", True

# ==========================================
# 3. UI LAYER
# ==========================================
def main():
    conn = init_db()
    
    # --- Sidebar ---
    st.sidebar.title("🎹 SmartStudio Bot")
    st.sidebar.caption("By Hanateam")
    
    # --- UPDATED: CEK STATUS MEMBER (PERSONAL) ---
    st.sidebar.markdown("---")
    st.sidebar.header("🏆 Status Member Kamu")
    st.sidebar.write("Masukkan No HP untuk cek level & diskon!")
    
    cek_hp = st.sidebar.text_input("No. WhatsApp:", placeholder="0812xxx")
    
    if cek_hp:
        # Hitung statistik customer ini
        jam_terbang = get_customer_stats(conn, cek_hp)
        level_name, benefit, progress, lvl_color = get_level_info(jam_terbang)
        
        # Tampilkan Card UI
        st.sidebar.info(f"**Level: {level_name}**")
        st.sidebar.metric("Jam Terbang", f"{jam_terbang} Jam")
        st.sidebar.progress(progress)
        st.sidebar.success(f"🎁 {benefit}")
    else:
        st.sidebar.caption("Data level bersifat personal. Masukkan nomor HP untuk melihat progress Anda.")
    
    # --- UPDATED: ADMIN AREA (TERTUTUP) ---
    st.sidebar.markdown("---")
    
    if "admin_logged_in" not in st.session_state: st.session_state.admin_logged_in = False
    
    # State Setup
    if "chat_history" not in st.session_state: st.session_state.chat_history = []
    if "bot_state" not in st.session_state: 
        st.session_state.bot_state = {
            "mode": "idle", "step": 0, 
            "name": None, "phone": None, # Added phone to state
            "date": None, "time": None, "dur": None, 
            "items": [], "target_id": None
        }

    # Admin Auth (Expanded=False agar tertutup)
    with st.sidebar.expander("🔐 Admin Area (Klik untuk buka)", expanded=False):
        if not st.session_state.admin_logged_in:
            pwd = st.text_input("Password Admin", type="password")
            if st.button("Login"):
                if hashlib.sha256(pwd.encode()).hexdigest() == hashlib.sha256("Hanateam123".encode()).hexdigest():
                    st.session_state.admin_logged_in = True; st.rerun()
                else: st.error("Salah password")
        else:
            if st.button("Logout"): st.session_state.admin_logged_in = False; st.rerun()

    # ==========================================
    # VIEW A: ADMIN DASHBOARD
    # ==========================================
    if st.session_state.admin_logged_in:
        st.title("🎛️ Studio Command Center")
        
       # --- FITUR BACKUP & RESTORE DATABASE ---
        with st.expander("💾 Database Backup & Restore", expanded=True):
            st.info("Gunakan fitur ini untuk menyimpan data agar tidak hilang saat server Cloud restart.")
            c_bk1, c_bk2 = st.columns(2)
            
            with c_bk1:
                conn.commit()
                if os.path.exists(DB_FILE):
                    with open(DB_FILE, "rb") as f:
                        bytes_data = f.read()
                        st.download_button(
                            label="⬇️ Download Full Backup (.db)",
                            data=bytes_data,
                            file_name=f"smartstudio_backup_{datetime.datetime.now().strftime('%Y%m%d_%H%M')}.db",
                            mime="application/octet-stream",
                            help="Klik ini untuk download seluruh data"
                        )
                else:
                    st.warning("Database belum terbentuk.")
            
            with c_bk2:
                uploaded_db = st.file_uploader("⬆️ Restore Backup (Upload .db)", type="db")
                if uploaded_db is not None:
                    if st.button("⚠️ Timpa Database & Restore"):
                        conn.close()
                        try:
                            with open(DB_FILE, "wb") as f:
                                f.write(uploaded_db.getbuffer())
                            st.toast("Restore Berhasil!", icon="✅")
                            st.success("Database berhasil direstore! Restarting...")
                            time.sleep(3)
                            st.session_state.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Gagal restore: {e}")
                            
        # --- FITUR HARD RESET ---
        with st.expander("💀 DANGER ZONE (Hapus Database)", expanded=False):
            st.error("⚠️ PERINGATAN: Ini akan menghapus SEMUA DATA! Data tidak bisa kembali!")
            confirm_del = st.checkbox("Saya yakin ingin menghapus seluruh database")
            
            if confirm_del:
                if st.button("💣 Hapus Total & Reset Aplikasi"):
                    conn.close()
                    if os.path.exists(DB_FILE):
                        try:
                            os.remove(DB_FILE)
                            st.toast("Database terhapus!", icon="🗑️")
                            st.success("Database berhasil dihapus. Merestart sistem...")
                            time.sleep(3)
                            st.session_state.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Gagal menghapus file: {e}")
                    else:
                        st.warning("File database tidak ditemukan.")
                        st.rerun()

        df_bk = pd.read_sql("SELECT * FROM bookings", conn)
        df_crs = pd.read_sql("SELECT * FROM courses", conn)
        
        # Metrics
        c1, c2, c3 = st.columns(3)
        c1.metric("Revenue", f"Rp {df_bk['price'].sum() if not df_bk.empty else 0:,.0f}")
        c2.metric("Bookings", f"{len(df_bk)}")
        c3.metric("Students", f"{len(df_crs)}")
        
        if not df_bk.empty:
            st.markdown("### 📊 Statistik")
            chart_data = df_bk.groupby('date')['price'].sum().reset_index()
            st.bar_chart(chart_data, x='date', y='price', color='#3b82f6')

        # Tabs
        t1, t2, t3, t4 = st.tabs(["📅 Bookings", "🛠️ Inventory", "🎓 Courses", "🛡️ Logs"])
        
        with t1: # Booking Management
            st.dataframe(df_bk, use_container_width=True, hide_index=True)
            st.markdown("---")
            c_del1, c_del2 = st.columns([3, 1])
            with c_del1:
                if not df_bk.empty:
                    del_options = df_bk.apply(lambda x: f"{x['id']} - {x['customer_name']} ({x['date']})", axis=1)
                    selected_del = st.selectbox("Pilih Data Booking untuk Dihapus", del_options)
            with c_del2:
                st.write("")
                st.write("")
                if not df_bk.empty and st.button("❌ Hapus Permanen"):
                    id_to_del = int(selected_del.split(' - ')[0])
                    conn.execute("DELETE FROM bookings WHERE id=?", (id_to_del,))
                    log_action(conn, "DELETE_BOOKING", f"ID {id_to_del} removed by Admin")
                    conn.commit()
                    st.success(f"ID {id_to_del} berhasil dihapus."); time.sleep(1); st.rerun()

            st.markdown("---")
            st.markdown("#### ✏️ Admin Reschedule")
            if not df_bk.empty:
                c_r1, c_r2, c_r3, c_r4 = st.columns(4)
                with c_r1: tid = st.selectbox("ID Booking", df_bk['id'])
                with c_r2: ndate = st.date_input("Tanggal Baru")
                with c_r3: ntime = st.number_input("Jam Baru", 8, 23, 17)
                with c_r4: 
                    st.write("")
                    if st.button("Pindah Jadwal"):
                        m, s = process_reschedule(conn, tid, str(ndate), int(ntime))
                        if s: st.success(m); time.sleep(1); st.rerun()
                        else: st.error(m)

        with t2: # Inventory
            c_a, c_b = st.columns([2, 1])
            with c_a: st.dataframe(pd.read_sql("SELECT * FROM inventory", conn), use_container_width=True)
            with c_b: 
                with st.form("add_inv"):
                    new_item = st.text_input("Tambah Alat Baru")
                    if st.form_submit_button("Simpan"):
                        try:
                            conn.execute("INSERT INTO inventory (item_name) VALUES (?)", (new_item.lower(),))
                            conn.commit(); st.rerun()
                        except: st.error("Item sudah ada!")

        with t3: # Courses
            st.dataframe(df_crs, use_container_width=True)
            
            if not df_crs.empty:
                st.markdown("### 🗑️ Hapus Data Siswa")
                c_del_s1, c_del_s2 = st.columns([3, 1])
                with c_del_s1:
                    del_course_options = df_crs.apply(lambda x: f"{x['id']} - {x['student_name']} ({x['instrument']})", axis=1)
                    selected_course_del = st.selectbox("Pilih Siswa untuk Dihapus", del_course_options)
                with c_del_s2:
                    st.write("") 
                    st.write("")
                    if st.button("❌ Hapus Siswa"):
                        id_to_del = int(selected_course_del.split(' - ')[0])
                        conn.execute("DELETE FROM courses WHERE id=?", (id_to_del,))
                        log_action(conn, "DELETE_COURSE", f"Student ID {id_to_del} removed by Admin")
                        conn.commit()
                        st.success(f"Data siswa ID {id_to_del} berhasil dihapus.")
                        time.sleep(1); st.rerun()
            
            st.markdown("---")
            st.markdown("#### ➕ Tambah Siswa Baru")
            with st.form("new_student"):
                c_s1, c_s2 = st.columns(2)
                with c_s1: 
                    n = st.text_input("Nama Siswa")
                    i = st.selectbox("Alat Musik", ["Gitar", "Piano", "Drum", "Vokal", "Bass", "Biola"])
                    day = st.selectbox("Hari Kursus", ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"])
                with c_s2: 
                    t_val = st.time_input("Jam Mulai", datetime.time(16, 0))
                    dur = st.number_input("Durasi (Jam)", min_value=1, value=1)
                
                if st.form_submit_button("Daftar Siswa"):
                    if n: 
                        conn.execute("""INSERT INTO courses 
                            (student_name, instrument, schedule_day, schedule_time, duration, status) 
                            VALUES (?,?,?,?,?,?)""", 
                            (n, i, day, str(t_val), dur, "Active"))
                        conn.commit()
                        log_action(conn, "NEW_COURSE", f"Added student: {n}")
                        st.success("Siswa berhasil ditambahkan!")
                        time.sleep(1); st.rerun()
                    else:
                        st.warning("Nama siswa wajib diisi.")

        with t4: # Logs
            st.dataframe(pd.read_sql("SELECT * FROM audit_logs ORDER BY id DESC", conn), use_container_width=True)

    # ==========================================
    # VIEW B: CHATBOT (USER)
    # ==========================================
    else:
        st.title("🤖 Assistant Studio")
        
        # --- FITUR UPDATE: CEK JAM RAME & SEPI (DENGAN TANGGAL) ---
        with st.expander("📊 Cek Ketersediaan & Jam Rame (Klik di sini)", expanded=False):
            # 1. Input Pilih Tanggal
            col_date, col_ket = st.columns([1, 2])
            with col_date:
                tgl_pilih = st.date_input("Pilih Tanggal:", datetime.date.today())
            
            with col_ket:
                st.write("") # Spasi
                st.caption(f"Menampilkan kepadatan studio untuk tanggal: **{tgl_pilih.strftime('%d %B %Y')}**")

            # 2. Logic Query Data Spesifik Tanggal
            c_stat = conn.cursor()
            c_stat.execute("SELECT start_hour, duration FROM bookings WHERE date = ?", (str(tgl_pilih),))
            bookings_today = c_stat.fetchall()
            
            # 3. Mapping Jam 8-23
            hours_map = {h: 0 for h in range(8, 24)} # Default 0 (Kosong)
            
            # Isi slot yang terbooking
            for start, dur in bookings_today:
                for h in range(start, start + dur):
                    if h in hours_map:
                        hours_map[h] += 1  # Tambah 1 jika ada booking
            
            # 4. Visualisasi
            df_heat = pd.DataFrame({
                "Jam": [f"{h}:00" for h in hours_map.keys()],
                "Status": ["⛔ Penuh" if v > 0 else "✅ Kosong" for v in hours_map.values()],
                "Value": list(hours_map.values())
            })
            
            # Tampilkan Grafik
            st.bar_chart(df_heat.set_index("Jam")['Value'], color="#F63366")
            
            # Info Teks
            jam_penuh = [k for k, v in hours_map.items() if v > 0]
            if jam_penuh:
                st.warning(f"Jam yang sudah terisi: {', '.join([str(x)+':00' for x in jam_penuh])}")
            else:
                st.success("Asik! Jadwal hari ini masih kosong melompong. Bebas pilih jam!")

        with st.expander("ℹ️  Panduan / Cara Pakai (Klik untuk baca)", expanded=True):
            st.markdown("""
            **1. Mau Booking?**
            👉 Ketik: *"Booking"* atau langsung *"Booking besok jam 5 sore"*
            
            **2. Mau Ganti Jadwal?**
            👉 Ketik: *"Reschedule"* lalu ikuti petunjuk bot.
            """)
        
        if not st.session_state.chat_history:
            greeting = "Halo! 👋 Selamat datang di SmartStudio. Ketik **'Booking'** untuk mulai."
            st.session_state.chat_history.append(("assistant", greeting))

        inv_rows = conn.execute("SELECT item_name FROM inventory").fetchall()
        inv_list = [x[0] for x in inv_rows]
        
        for role, txt in st.session_state.chat_history:
            with st.chat_message(role): 
                if "<div" in txt:
                    st.markdown(txt, unsafe_allow_html=True)
                else:
                    st.markdown(txt)
            
        if prompt := st.chat_input("Ketik 'Booking' atau 'Reschedule'"):
            st.session_state.chat_history.append(("user", prompt))
            with st.chat_message("user"): st.markdown(prompt)

            res = parse_intent(prompt, inv_list)
            bs = st.session_state.bot_state
            
            if res['intent'] == 'cancel':
                reply = "⚠️ **Pembatalan Booking**\n\nHubungi Admin kami: 👉 **[WhatsApp Admin](https://wa.me/6281234567890)**"
                st.session_state.bot_state = {"mode": "idle", "step": 0, "name": None, "phone": None, "date": None, "time": None, "dur": 1, "items": [], "target_id": None}
            
            elif res['intent'] == 'reset':
                reply = "🔄 Oke, diulang. Silakan ketik **'Booking'** lagi."
                st.session_state.bot_state = {"mode": "idle", "step": 0, "name": None, "phone": None, "date": None, "time": None, "dur": 1, "items": [], "target_id": None}
            
            else:
                if res['date']: bs['date'] = res['date']
                if bs['step'] != 'ASK_PHONE':
                    if res['time']: bs['time'] = res['time']
                if res['dur']: bs['dur'] = res['dur']
                if res['found_items']: bs['items'].extend(res['found_items'])

                reply = ""
                
                # 1. STEP: ASK_PHONE (NEW) -> FINALIZE
                if bs['step'] == 'ASK_PHONE':
                    # Validasi simpel
                    if len(prompt) > 8 and any(char.isdigit() for char in prompt):
                        bs['phone'] = prompt
                        if not bs['dur']: bs['dur'] = 1 
                        msg, _ = finalize_booking(conn, bs)
                        reply = msg
                        st.session_state.bot_state = {"mode": "idle", "step": 0, "name": None, "phone": None, "date": None, "time": None, "dur": None, "items": [], "target_id": None}
                    else:
                        reply = "Nomor HP sepertinya kurang valid. Mohon masukkan nomor yang benar agar Level Member bertambah."

                # 2. STEP: ASK_NAME -> ASK_PHONE
                elif bs['step'] == 'ASK_NAME':
                    bs['name'] = prompt.title()
                    bs['step'] = 'ASK_PHONE'
                    reply = f"Halo Kak {bs['name']}. Terakhir, **berapa Nomor WhatsApp kamu?** (Untuk update level member & diskon)."

                # 3. STEP: ASK_GEAR -> ASK_NAME
                elif bs['step'] == 'ASK_GEAR':
                    if "standar" in prompt.lower() or "tidak" in prompt.lower(): pass 
                    bs['step'] = 'ASK_NAME'
                    reply = f"Oke, alat: {', '.join(bs['items']) if bs['items'] else 'Standar'}. **Atas nama siapa?**"

                # 4. STEP: ASK_DURATION -> ASK_GEAR
                elif bs['step'] == 'ASK_DURATION':
                    num_match = re.search(r'\d+', prompt)
                    if num_match:
                        bs['dur'] = int(num_match.group(0))
                        bs['step'] = 'ASK_GEAR'
                        reply = f"Siap {bs['dur']} jam. **Ada tambahan alat?** (Ketik 'Standar' jika tidak ada)."
                    else:
                        reply = "Mohon masukkan angka durasi (contoh: '2' atau '2 jam')."

                # 5. STEP: ASK_TIME
                elif bs['step'] == 'ASK_TIME':
                    if bs['time']:
                        if bs['dur'] is None:
                            bs['step'] = 'ASK_DURATION'
                            reply = "Jam aman. **Mau main berapa jam?**"
                        else:
                            bs['step'] = 'ASK_GEAR'
                            reply = f"Oke {bs['dur']} jam. **Ada tambahan alat?** (Ketik 'Standar' jika tidak ada)."
                    else:
                        reply = "Maaf, jam berapa mulainya? (Contoh: '16' atau 'jam 4 sore')"

                # 6. INTENT: RESCHEDULE
                elif res['intent'] == 'reschedule':
                    bs['mode'] = 'reschedule'
                    bs['step'] = 'RES_NAME'
                    reply = "Siap reschedule. **Atas nama siapa** booking lamanya?"
                
                elif bs['mode'] == 'reschedule':
                    if bs['step'] == 'RES_NAME':
                        c = conn.cursor()
                        c.execute("SELECT id, date, start_hour FROM bookings WHERE customer_name LIKE ? ORDER BY id DESC", (f"%{prompt}%",))
                        row = c.fetchone()
                        if row:
                            bs['target_id'] = row[0]
                            bs['step'] = 'RES_TIME'
                            reply = f"Ketemu! Kak {prompt} tgl {row[1]} jam {row[2]}. **Mau pindah ke Hari & Jam berapa?**"
                        else:
                            reply = "Nama tidak ditemukan. Coba lagi atau hubungi Admin."

                    elif bs['step'] == 'RES_TIME':
                        if bs['date'] and bs['time']:
                            msg, _ = process_reschedule(conn, bs['target_id'], bs['date'], bs['time'])
                            reply = msg
                            st.session_state.bot_state = {"mode": "idle", "step": 0, "name": None, "phone": None, "date": None, "time": None, "dur": None, "items": [], "target_id": None}
                        else:
                            reply = "Mohon sebutkan **Hari dan Jam** baru ya. (Contoh: 'Besok jam 14')"

                # 7. INTENT: BOOKING
                elif res['intent'] == 'booking' or bs['mode'] == 'booking':
                    bs['mode'] = 'booking'
                    if not bs['date']: 
                        wib = datetime.timezone(datetime.timedelta(hours=7))
                        bs['date'] = datetime.datetime.now(wib).strftime("%Y-%m-%d")
                    
                    if not bs['time']:
                        bs['step'] = 'ASK_TIME'
                        reply = f"Siap booking tgl **{bs['date']}**. Jam berapa mainnya?"
                    
                    elif bs['dur'] is None:
                        bs['step'] = 'ASK_DURATION'
                        reply = "Jam oke. **Mau sewa berapa jam?**"

                    elif not bs['items'] and bs['step'] != 'ASK_NAME' and bs['step'] != 'ASK_PHONE':
                        bs['step'] = 'ASK_GEAR'
                        reply = "Sip. **Butuh alat apa saja?**"
                    elif not bs['name']:
                        bs['step'] = 'ASK_NAME'
                        reply = "Siap. **Atas nama siapa**?"
                    elif not bs['phone']:
                        bs['step'] = 'ASK_PHONE'
                        reply = "Terakhir, **Berapa nomor WA kamu?** (Untuk update level member)."
                    else:
                        msg, _ = finalize_booking(conn, bs)
                        reply = msg
                        st.session_state.bot_state = {"mode": "idle", "step": 0, "name": None, "phone": None, "date": None, "time": None, "dur": None, "items": [], "target_id": None}
                
                else:
                    reply = "Halo! Ketik **'Booking'** untuk sewa, **'Reschedule'** untuk ganti jadwal, atau **'Batal'**."
            
            time.sleep(0.5)
            st.session_state.chat_history.append(("assistant", reply))
            with st.chat_message("assistant"): 
                if "<div" in reply:
                    st.markdown(reply, unsafe_allow_html=True)
                else:
                    st.markdown(reply)
            st.rerun()

if __name__ == "__main__":
    main()
