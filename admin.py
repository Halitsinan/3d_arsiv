import streamlit as st
import streamlit.components.v1 as components
import psycopg2
import pandas as pd
from PIL import Image
import io
import subprocess
import os
import time
import html
import base64
from google.oauth2 import service_account
from googleapiclient.discovery import build
import sys
import json
import config
import slicer

# ==========================================
# 1. AYARLAR VE PATH TANIMLARI
# ==========================================
st.set_page_config(page_title="3D Asset Manager PRO", layout="wide", page_icon="📦")

# Yolları dinamik bul
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if "app" in ROOT_DIR: ROOT_DIR = os.path.dirname(ROOT_DIR)

LOG_DIR = os.path.join(ROOT_DIR, "logs")
LOG_FILE = os.path.join(LOG_DIR, "system.log")
PYTHON_EXE = sys.executable 

os.makedirs(LOG_DIR, exist_ok=True)
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, 'w') as f: f.write("--- SİSTEM BAŞLATILDI ---\n")

DB_CONFIG = {
    "dbname": "asset_db",
    "user": "postgres",
    "password": "gizli_sifre",
    "host": "localhost",
    "port": "5435"
}
CREDENTIALS = os.path.join(ROOT_DIR, 'app/service_account.json')

# ==========================================
# 2. YARDIMCI FONKSİYONLAR
# ==========================================

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

def run_query_df(query, params=None):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(query, params)
            if cur.description:
                columns = [desc[0] for desc in cur.description]
                data = cur.fetchall()
                return pd.DataFrame(data, columns=columns)
            return pd.DataFrame()
    except Exception as e:
        return pd.DataFrame() 
    finally:
        conn.close()

def get_drive_service():
    if not os.path.exists(CREDENTIALS): return None
    creds = service_account.Credentials.from_service_account_file(CREDENTIALS)
    return build('drive', 'v3', credentials=creds)

def extract_drive_id(url_or_id):
    text = url_or_id.strip()
    if "drive.google.com" in text and "/folders/" in text:
        try: return text.split("/folders/")[1].split("?")[0].strip()
        except: return text
    return text

def extract_drive_file_id(url_or_id):
    """Google Drive dosya URL'sinden file ID çıkarır."""
    text = url_or_id.strip()
    if "/file/d/" in text:
        try: return text.split("/file/d/")[1].split("/")[0].split("?")[0].strip()
        except: pass
    if "id=" in text:
        try: return text.split("id=")[1].split("&")[0].strip()
        except: pass
    return text  # zaten raw ID

def download_gdrive_file_to_temp(file_url_or_id, filename):
    """
    Google Drive dosyasını geçici dizine indirir.
    ZIP ise içindeki TÜM STL/OBJ/3MF dosyalarını çıkarır.
    Her zaman (list_of_paths, error) döndürür.
    """
    try:
        import zipfile, io, uuid
        from googleapiclient.http import MediaIoBaseDownload
        service = get_drive_service()
        if not service:
            return None, "Service account credentials bulunamadı"

        file_id = extract_drive_file_id(file_url_or_id)
        temp_dir = config.get_temp_dir()
        os.makedirs(temp_dir, exist_ok=True)

        # Çok parçalı RAR tespiti (indirmeden önce dosya adına bak)
        import re as _re
        _mp = _re.search(r'\.part(\d+)\.rar$', (filename or '').lower())
        if _mp:
            part_n = int(_mp.group(1))
            if part_n > 1:
                return None, (
                    f"⚠️ Bu dosya çok parçalı RAR arşivinin {part_n}. parçasıdır.\n"
                    "Dilimlemek için tüm parçaları (.part1.rar, .part2.rar, ...) aynı klasöre indirip manuel açın."
                )
            else:
                # part1.rar — deneyerek devam et ama anlamlı hata mesajı hazırla
                pass

        # Önce belleğe indir (magic bytes tespiti için)
        raw_buf = io.BytesIO()
        request = service.files().get_media(fileId=file_id)
        downloader = MediaIoBaseDownload(raw_buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        raw_bytes = raw_buf.getvalue()

        magic = raw_bytes[:8]  # 7z=6, RAR=7-8 byte signature için yeterli
        MODEL_EXTS = ('.stl', '.obj', '.3mf', '.step', '.stp')

        if magic[:2] == b'PK':
            # ZIP arşivi — içindeki TÜM model dosyalarını çıkar
            try:
                # Her ZIP için izole klasör (dosya ismi çakışmasın)
                extract_dir = os.path.join(temp_dir, f"zip_{uuid.uuid4().hex[:8]}")
                os.makedirs(extract_dir, exist_ok=True)
                extracted = []
                with zipfile.ZipFile(io.BytesIO(raw_bytes)) as zf:
                    for entry in zf.namelist():
                        if any(entry.lower().endswith(e) for e in MODEL_EXTS):
                            safe_name = os.path.basename(entry)
                            local_path = os.path.join(extract_dir, safe_name)
                            with zf.open(entry) as src, open(local_path, 'wb') as dst:
                                dst.write(src.read())
                            extracted.append(local_path)
                if not extracted:
                    return None, "ZIP içinde desteklenen model dosyası bulunamadı (.stl/.obj/.3mf)"
                return extracted, None
            except zipfile.BadZipFile:
                pass

        # 7Z arşivi — py7zr ile aç
        if magic[:6] == b'7z\xbc\xaf\x27\x1c':
            try:
                import py7zr
                extract_dir = os.path.join(temp_dir, f"sz_{uuid.uuid4().hex[:8]}")
                os.makedirs(extract_dir, exist_ok=True)
                with py7zr.SevenZipFile(io.BytesIO(raw_bytes), mode='r') as zf:
                    zf.extractall(path=extract_dir)
                extracted = []
                for root, _, files in os.walk(extract_dir):
                    for f in files:
                        if any(f.lower().endswith(e) for e in MODEL_EXTS):
                            extracted.append(os.path.join(root, f))
                if not extracted:
                    return None, "7Z içinde desteklenen model dosyası bulunamadı (.stl/.obj/.3mf)"
                return extracted, None
            except Exception as e7:
                return None, f"7Z açma hatası: {e7}"

        # RAR arşivi — rarfile ile aç
        if magic[:7] == b'Rar!\x1a\x07\x00' or magic[:8] == b'Rar!\x1a\x07\x01\x00':
            try:
                import rarfile, tempfile
                tmp_rar = os.path.join(temp_dir, f"tmp_{uuid.uuid4().hex[:8]}.rar")
                with open(tmp_rar, 'wb') as tf:
                    tf.write(raw_bytes)
                extract_dir = os.path.join(temp_dir, f"rar_{uuid.uuid4().hex[:8]}")
                os.makedirs(extract_dir, exist_ok=True)
                with rarfile.RarFile(tmp_rar) as rf:
                    rf.extractall(path=extract_dir)
                os.remove(tmp_rar)
                extracted = []
                for root, _, files in os.walk(extract_dir):
                    for f in files:
                        if any(f.lower().endswith(e) for e in MODEL_EXTS):
                            extracted.append(os.path.join(root, f))
                if not extracted:
                    return None, "RAR içinde desteklenen model dosyası bulunamadı (.stl/.obj/.3mf)"
                return extracted, None
            except rarfile.NeedFirstVolume:
                return None, (
                    "⚠️ Bu dosya çok parçalı RAR arşivinin ortasındaki bir parçadır.\n"
                    "Tüm parçaları (.part1.rar, .part2.rar, ...) aynı klasöre indirip manuel açın."
                )
            except Exception as er:
                return None, f"RAR açma hatası: {er}"

        # Normal model dosyası
        local_path = os.path.join(temp_dir, filename)
        with open(local_path, 'wb') as fh:
            fh.write(raw_bytes)
        return [local_path], None

    except Exception as e:
        return None, str(e)

def run_script_with_log(script_name):
    script_path = os.path.join(ROOT_DIR, "app", script_name)
    with open(LOG_FILE, "a") as log_file:
        log_file.write(f"\n\n--- 🚀 {script_name} BAŞLATILIYOR ({time.strftime('%H:%M:%S')}) ---\n")
    
    log_file_handle = open(LOG_FILE, "a")
    subprocess.Popen(
        [PYTHON_EXE, "-u", script_path],
        stdout=log_file_handle,
        stderr=log_file_handle,
        cwd=ROOT_DIR,
        start_new_session=True
    )

# --- 3D VIEWER ---
def render_3d_viewer(file_path):
    if not os.path.exists(file_path):
        st.error(f"Dosya bulunamadı: {file_path}")
        return

    if os.path.getsize(file_path) > 50 * 1024 * 1024:
        st.warning("⚠️ Dosya çok büyük (>50MB). Önizleme yapılamıyor.")
        return

    ext = os.path.splitext(file_path)[1].lower()
    with open(file_path, "rb") as f:
        file_b64 = base64.b64encode(f.read()).decode('utf-8')

    html_code = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <style>body {{ margin: 0; background-color: #0e1117; overflow: hidden; }}</style>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/STLLoader.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/loaders/OBJLoader.js"></script>
        <script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>
    </head>
    <body>
        <script>
            const scene = new THREE.Scene();
            scene.background = new THREE.Color(0x0e1117);
            const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
            camera.position.z = 100;
            const renderer = new THREE.WebGLRenderer({{ antialias: true }});
            renderer.setSize(window.innerWidth, window.innerHeight);
            document.body.appendChild(renderer.domElement);
            
            const ambientLight = new THREE.AmbientLight(0x404040, 2); scene.add(ambientLight);
            const dirLight = new THREE.DirectionalLight(0xffffff, 1); dirLight.position.set(1,1,1); scene.add(dirLight);
            const controls = new THREE.OrbitControls(camera, renderer.domElement);

            const fileData = atob("{file_b64}");
            const len = fileData.length;
            const bytes = new Uint8Array(len);
            for (let i = 0; i < len; i++) {{ bytes[i] = fileData.charCodeAt(i); }}
            
            let loader;
            const ext = "{ext}";
            
            if (ext === '.stl') {{
                loader = new THREE.STLLoader();
                const geo = loader.parse(bytes.buffer);
                const mat = new THREE.MeshPhongMaterial({{ color: 0x00aaff, specular: 0x111111, shininess: 200 }});
                const mesh = new THREE.Mesh(geo, mat);
                geo.computeBoundingBox(); geo.center(); scene.add(mesh);
            }} 
            else if (ext === '.obj') {{
                const text = new TextDecoder('utf-8').decode(bytes.buffer);
                loader = new THREE.OBJLoader();
                const obj = loader.parse(text);
                scene.add(obj);
            }}
            
            function animate() {{ requestAnimationFrame(animate); renderer.render(scene, camera); }}
            animate();
        </script>
    </body>
    </html>
    """
    components.html(html_code, height=500, scrolling=False)

# ==========================================
# 3. CSS & STİL
# ==========================================
st.markdown("""
<style>
    .stImage img { border-radius: 8px; border: 1px solid #333; object-fit: cover; aspect-ratio: 1/1; }
    .tag-badge { background-color: #262730; color: #00aaff; padding: 2px 8px; border-radius: 10px; font-size: 11px; margin-right: 4px; border: 1px solid #444; }
</style>
""", unsafe_allow_html=True)

# ==========================================
# 4. ARAYÜZ MANTIĞI & STATE TEMİZLİĞİ
# ==========================================

# Varsayılan sayfa ayarı
if 'active_page' not in st.session_state:
    st.session_state['active_page'] = "🖼️ Galeri & Arama"

# Galeri pagination state
if 'gallery_page' not in st.session_state:
    st.session_state['gallery_page'] = 1
if 'gallery_filters' not in st.session_state:
    st.session_state['gallery_filters'] = {}

# Pending page navigation (set before widget renders to avoid Streamlit error)
if 'pending_page' in st.session_state:
    st.session_state['menu_radio'] = st.session_state.pop('pending_page')

with st.sidebar:
    st.title("📦 Asset Manager")
    
    # Menü Seçimi
    page_selection = st.radio("Menü", ["🖼️ Galeri & Arama", "⚙️ Kaynak Yönetimi", "🖨️ Printer Yönetimi", "🛠️ Operasyon Merkezi"], key="menu_radio")
    
    # 🔥🔥🔥 KRİTİK TEMİZLİK PROTOKOLÜ 🔥🔥🔥
    # Sayfa değiştiği an bu blok çalışır ve eski çöpleri siler
    if st.session_state['active_page'] != page_selection:
        st.session_state['active_page'] = page_selection # Yeni sayfayı kaydet
        
        # Temizlenecek değişkenler (Listeyi genişletebilirsin)
        keys_to_clear = ['preview_file', 'search_query', 'sel_src', 'sel_fold']
        for key in keys_to_clear:
            if key in st.session_state:
                del st.session_state[key]
        
        st.rerun() # Sayfayı tazeleyerek temiz başlat
    # ---------------------------------------------

    st.divider()
    if 'preview_file' in st.session_state and st.session_state['preview_file']:
        st.info(f"👁️ Dosya: {os.path.basename(st.session_state['preview_file'])}")
        if st.button("❌ Önizlemeyi Kapat", use_container_width=True):
            del st.session_state['preview_file']
            st.rerun()

# --- SAYFA 1: GALERİ ---
if page_selection == "🖼️ Galeri & Arama":
    st.header("🖼️ 3D Varlık Galerisi")

    if 'preview_file' in st.session_state:
        with st.expander("🔍 3D Görüntüleyici", expanded=True):
            render_3d_viewer(st.session_state['preview_file'])
    
    # Filtre satırı 1: Arama
    search_query = st.text_input("🔍 Ara", placeholder="Örn: robot, scifi...")
    
    # Filtre satırı 2: Kaynak ve Klasör
    c1, c2 = st.columns([1, 1])
    
    sel_src = 0
    with c1:
        srcs = run_query_df("SELECT id, name FROM source")
        if not srcs.empty:
            opts = {row['id']: row['name'] for _, row in srcs.iterrows()}
            opts[0] = "Tüm Kaynaklar"
            sel_src = st.selectbox("📂 Kaynak", list(opts.keys()), format_func=lambda x: opts[x], index=0)

    sel_fold = None
    with c2:
        if sel_src != 0:
            folds = run_query_df(f"SELECT DISTINCT split_part(folder_path, '/', 1) as f FROM assets WHERE source_id={sel_src} AND folder_path != '' ORDER BY f ASC")
            if not folds.empty:
                l1 = st.selectbox("📁 Klasör", ["Tüm Klasörler"] + folds['f'].tolist())
                if l1 != "Tüm Klasörler": sel_fold = l1
        else:
            st.selectbox("📁 Klasör", ["Önce kaynak seçin"], disabled=True)
    
    # Filtre değişikliği kontrolü - değiştiyse sayfa 1'e dön
    current_filters = {'search': search_query, 'source': sel_src, 'folder': sel_fold}
    if st.session_state['gallery_filters'] != current_filters:
        st.session_state['gallery_filters'] = current_filters
        st.session_state['gallery_page'] = 1

    where = ["1=1"]; params = []
    if search_query: 
        where.append("(filename ILIKE %s OR tags ILIKE %s)")
        params.extend([f"%{search_query}%", f"%{search_query}%"])
    if sel_src != 0: 
        where.append("source_id = %s"); params.append(sel_src)
    if sel_fold: 
        where.append("folder_path ILIKE %s"); params.append(f"{sel_fold}%")

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM assets WHERE {' AND '.join(where)}", tuple(params))
            total = cur.fetchone()[0]

    PAGE_SIZE = 100
    total_pages = max(1, (total // PAGE_SIZE) + 1)
    
    # Sayfa numarasını sınırla (filtre değişince toplam sayfa azalabilir)
    if st.session_state['gallery_page'] > total_pages:
        st.session_state['gallery_page'] = total_pages
    
    c_nav1, c_nav2 = st.columns([1, 5])
    curr_page = c_nav1.number_input(
        "Sayfa", 
        min_value=1, 
        max_value=total_pages, 
        value=st.session_state['gallery_page'],
        key="gallery_page_input"
    )
    
    # Sayfa değiştiğinde session state'i güncelle
    if curr_page != st.session_state['gallery_page']:
        st.session_state['gallery_page'] = curr_page
    
    c_nav2.markdown(f"**Toplam: {total} dosya | Sayfa: {curr_page}/{total_pages}**")
    
    offset = (curr_page - 1) * PAGE_SIZE
    query = f"SELECT * FROM assets WHERE {' AND '.join(where)} ORDER BY created_at DESC LIMIT %s OFFSET %s"
    df = run_query_df(query, tuple(params + [PAGE_SIZE, offset]))

    if df.empty:
        st.warning("Dosya bulunamadı.")
    else:
        cols = st.columns(5)
        for i, row in df.iterrows():
            with cols[i % 5]:
                with st.container(border=True):
                    if row['thumbnail_blob']:
                        st.image(io.BytesIO(row['thumbnail_blob']))
                    else:
                        st.image("https://via.placeholder.com/300?text=No+Img")
                    
                    st.caption(f"**{row['filename'][:20]}**")
                    
                    if row['tags']:
                        tags_html = "".join([f'<span class="tag-badge">{t.strip()}</span>' for t in row['tags'].split(",")[:3]])
                        st.markdown(tags_html, unsafe_allow_html=True)
                    
                    # Dosya tipi kontrolü
                    is_gdrive = row['filepath'] and ('drive.google.com' in row['filepath'] or row['filepath'].startswith('http'))
                    file_ext = os.path.splitext(row['filename'])[1].lower()
                    is_3d_model = file_ext in ['.stl', '.obj']
                    
                    # Butonlar
                    if is_gdrive:
                        # Google Drive dosyaları için link aç
                        if st.button("🔗 Aç", key=f"v_{row['id']}", use_container_width=True):
                            st.markdown(f"[Google Drive'da Aç]({row['filepath']})")
                            st.info(f"📎 Link: {row['filepath']}")

                        # GDrive assetleri her zaman 3D dosya — uzantı kontrolü yapma
                        if True:
                            if st.button("🔪 Slice", key=f"s_{row['id']}", use_container_width=True, type="primary"):
                                with st.spinner("⬇️ Google Drive'dan indiriliyor..."):
                                    local_paths, err = download_gdrive_file_to_temp(
                                        row['filepath'], row['filename']
                                    )
                                if local_paths:
                                    st.session_state['slice_asset_id'] = row['id']
                                    st.session_state['slice_filename'] = row['filename']
                                    st.session_state['slice_filepath'] = local_paths  # list
                                    st.session_state['pending_page'] = "🖨️ Printer Yönetimi"
                                    st.session_state['active_page'] = "🖨️ Printer Yönetimi"
                                    st.rerun()
                                else:
                                    st.error(f"❌ İndirme hatası: {err}")
                    else:
                        # Lokal dosyalar için 3D viewer
                        if st.button("👁️ 3D", key=f"v_{row['id']}", use_container_width=True):
                            if row['filepath'] and os.path.exists(row['filepath']):
                                st.session_state['preview_file'] = row['filepath']
                                st.rerun()
                            else:
                                st.error(f"Dosya bulunamadı: {row['filepath']}")

                        # Lokal STL/OBJ için slice butonu
                        if is_3d_model and row['filepath'] and os.path.exists(row['filepath']):
                            if st.button("🔪 Slice", key=f"s_{row['id']}", use_container_width=True, type="primary"):
                                st.session_state['slice_asset_id'] = row['id']
                                st.session_state['slice_filename'] = row['filename']
                                st.session_state['slice_filepath'] = row['filepath']
                                st.session_state['pending_page'] = "🖨️ Printer Yönetimi"
                                st.session_state['active_page'] = "🖨️ Printer Yönetimi"
                                st.rerun()

# --- SAYFA 2: KAYNAK ---
elif page_selection == "⚙️ Kaynak Yönetimi":
    st.title("⚙️ Kaynak Yönetimi")
    t1, t2, t3 = st.tabs(["➕ Tek Ekle", "📚 Toplu Ekle", "📋 Liste"])
    
    with t1:
        with st.form("add"):
            n = st.text_input("İsim"); t = st.selectbox("Tip", ["local", "gdrive"]); p = st.text_input("Link/ID")
            if st.form_submit_button("Kaydet") and p:
                final_p = extract_drive_id(p) if t == 'gdrive' else p
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(f"INSERT INTO source (name, source_type, {'path' if t=='local' else 'drive_id'}) VALUES (%s,%s,%s)", (n or "Yeni",t,final_p))
                        conn.commit()
                st.success("Eklendi!"); st.rerun()
    
    with t2:
        st.info("Her satıra bir link/path yazın. Google Drive linkleri otomatik parse edilir.")
        bulk_type = st.radio("Tip", ["gdrive", "local"], horizontal=True)
        bulk_text = st.text_area("Linkler/Pathler (her satırda bir tane)", height=200, 
                                  placeholder="https://drive.google.com/drive/folders/xxx\nhttps://drive.google.com/drive/folders/yyy\n...")
        
        if st.button("📥 Toplu Ekle", type="primary"):
            lines = [line.strip() for line in bulk_text.split("\n") if line.strip()]
            if not lines:
                st.warning("Hiçbir satır girilmedi.")
            else:
                added = 0
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        for line in lines:
                            try:
                                final_p = extract_drive_id(line) if bulk_type == 'gdrive' else line
                                auto_name = f"Import-{final_p[:15]}"
                                cur.execute(f"INSERT INTO source (name, source_type, {'drive_id' if bulk_type=='gdrive' else 'path'}) VALUES (%s,%s,%s)", 
                                           (auto_name, bulk_type, final_p))
                                added += 1
                            except Exception as e:
                                st.error(f"❌ Hata ({line[:30]}...): {e}")
                        conn.commit()
                st.success(f"✅ {added}/{len(lines)} kaynak eklendi!")
                
                # İsimleri otomatik düzelt
                if added > 0:
                    try:
                        from app.fix_names import fix_names
                        with st.spinner("İsimler düzeltiliyor..."):
                            fix_names()
                        st.info("🏷️ İsim düzeltme tamamlandı!")
                    except Exception as e:
                        st.warning(f"⚠️ İsim düzeltme hatası: {e}")
                
                st.rerun()
                
    with t3:
        df_src = run_query_df("SELECT * FROM source ORDER BY id")
        
        if df_src.empty:
            st.info("Henüz kaynak eklenmemiş.")
        else:
            # Path/Drive ID kolonunu hazırla
            df_src['location'] = df_src.apply(lambda row: row.get('path') or row.get('drive_id', 'N/A'), axis=1)
            
            # Grid görünümü için sütunları seç ve düzenle
            display_df = df_src[['id', 'name', 'source_type', 'location']].copy()
            display_df.columns = ['ID', 'İsim', 'Tip', 'Konum']
            
            # Seçim kolonu ekle
            display_df.insert(0, '✓', False)
            
            # Editable dataframe ile grid + checkbox
            edited_df = st.data_editor(
                display_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "✓": st.column_config.CheckboxColumn("✓", width="small", default=False),
                    "ID": st.column_config.NumberColumn("ID", width="small", disabled=True),
                    "İsim": st.column_config.TextColumn("İsim", width="medium", disabled=True),
                    "Tip": st.column_config.TextColumn("Tip", width="small", disabled=True),
                    "Konum": st.column_config.TextColumn("Konum", width="large", disabled=True)
                },
                disabled=["ID", "İsim", "Tip", "Konum"]
            )
            
            st.divider()
            
            # Seçili satırları bul
            selected_ids = edited_df[edited_df['✓'] == True]['ID'].tolist()
            
            c1, c2 = st.columns([1, 5])
            if c1.button("🗑️ Seçilenleri Sil", type="primary", disabled=len(selected_ids) == 0):
                with get_db_connection() as conn:
                    with conn.cursor() as cur:
                        for src_id in selected_ids:
                            cur.execute("DELETE FROM source WHERE id=%s", (src_id,))
                        conn.commit()
                st.success(f"✅ {len(selected_ids)} kaynak silindi!")
                st.rerun()
            
            c2.caption(f"📌 Seçili: {len(selected_ids)} kaynak")

# --- SAYFA 3: OPERASYON ---


elif page_selection == "🛠️ Operasyon Merkezi":
    st.title("🛠️ Operasyon Merkezi")
    
    # Buradaki "Container" ve "Rerun" kodları temizlendi.
    # Sadece butonlar var.
    
    c1, c2, c3, c4, c5 = st.columns(5)
    if c1.button("🔍 Indexer", use_container_width=True):
        run_script_with_log("indexer.py"); st.toast("Başladı...")
    if c2.button("🧠 AI Tagger", use_container_width=True):
        run_script_with_log("ai_tagger.py"); st.toast("Başladı...")
    if c3.button("⬇️ Deep Scan", use_container_width=True):
        run_script_with_log("deep_scan.py"); st.toast("Başladı...")
    if c4.button("🏷️ Fix Names", use_container_width=True):
        run_script_with_log("fix_names.py")
    if c5.button("♻️ Resim Onar", use_container_width=True):
        run_script_with_log("retry_thumbs.py")

    st.divider()
    
    # --- LOG GÖRÜNÜMÜ ---
    c_log1, c_log2, c_log3 = st.columns([6, 2, 2])
    c_log1.subheader("📟 Canlı Loglar")
    auto_refresh = c_log2.checkbox("🔄 Otomatik", value=True, key="auto_log")
    if c_log3.button("🧹 Temizle", width='stretch'):
        with open(LOG_FILE, 'w', encoding='utf-8') as f:
            f.write("--- LOG TEMİZLENDİ ---\n")
        st.rerun()

    log_content = "Log dosyası henüz oluşmadı."
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
                # En yeni loglar üstte - ters sıralama
                log_content = ''.join(reversed(lines[-100:]))
    except: pass

    st.code(log_content, language="bash", line_numbers=False)
    
    # Otomatik yenileme
    if auto_refresh:
        time.sleep(3)
        st.rerun()

# --- SAYFA 4: PRINTER YÖNETİMİ ---


elif page_selection == "🖨️ Printer Yönetimi":
    st.title("🖨️ 3D Printer & Filament Yönetimi")

    # === ORCASLICER PANELİ ===
    if st.session_state.get('slice_asset_id'):
        filename   = st.session_state.get('slice_filename', 'Dosya')
        stl_raw    = st.session_state.get('slice_filepath', [])
        # Geriye dönük uyumluluk: string veya liste olabilir
        stl_paths  = stl_raw if isinstance(stl_raw, list) else ([stl_raw] if stl_raw else [])

        with st.container(border=True):
            col_title, col_close = st.columns([5, 1])
            with col_title:
                st.subheader(f"🔪 {filename} — OrcaSlicer'a Gönder ({len(stl_paths)} dosya)")
            with col_close:
                if st.button("❌ Kapat", use_container_width=True):
                    for k in ['slice_asset_id', 'slice_filename', 'slice_filepath']:
                        st.session_state.pop(k, None)
                    st.rerun()

            downloads_dir = config.get_orca_downloads_dir()
            container     = config.get_docker_container()
            existing_paths = [p for p in stl_paths if p and os.path.exists(p)]

            if existing_paths:
                try:
                    import shutil as _shutil

                    # 1) Downloads klasörünü temizle
                    if os.path.isdir(downloads_dir):
                        for _f in os.listdir(downloads_dir):
                            _fp = os.path.join(downloads_dir, _f)
                            try:
                                if os.path.isfile(_fp) or os.path.islink(_fp):
                                    os.remove(_fp)
                                elif os.path.isdir(_fp):
                                    _shutil.rmtree(_fp)
                            except Exception:
                                pass
                    else:
                        os.makedirs(downloads_dir, exist_ok=True)

                    # 2) TÜM dosyaları Downloads'a kopyala
                    safe_names = []
                    for src_path in existing_paths:
                        raw = os.path.basename(src_path)
                        base, ext = os.path.splitext(raw)
                        if ext.lower() not in ['.stl', '.obj', '.3mf', '.step']:
                            ext = '.stl'
                        safe = base.replace(" ", "_").replace("(", "").replace(")", "") + ext
                        _shutil.copy2(src_path, os.path.join(downloads_dir, safe))
                        safe_names.append(safe)

                    # 3) Container'ı yeniden başlat
                    with st.spinner("🔄 OrcaSlicer yeniden başlatılıyor..."):
                        subprocess.run(
                            ["docker", "restart", container],
                            capture_output=True, timeout=60
                        )
                        import time as _time
                        _time.sleep(5)

                    # 4) Tüm dosyaları tek komutla tablaya yükle
                    container_paths = " ".join(f'"/config/Downloads/{s}"' for s in safe_names)
                    subprocess.run(
                        ["docker", "exec", "-d", "-u", "abc", container,
                         "bash", "-c",
                         f'DISPLAY=:1 /opt/orcaslicer/bin/orca-slicer {container_paths} > /tmp/orca_load.log 2>&1'],
                        capture_output=True, timeout=10
                    )
                    names_str = ", ".join(f"**{s}**" for s in safe_names)
                    st.success(f"✅ {len(safe_names)} dosya OrcaSlicer tablaya yüklendi: {names_str}")
                except Exception as e:
                    st.warning(f"⚠️ Otomatik gönderme hatası: {e}")
            else:
                st.warning("⚠️ Dosya bulunamadı.")

            # OrcaSlicer aç butonları
            orca_https = config.get_orca_web_url()
            orca_http  = orca_https.replace("https://", "http://")
            c1, c2 = st.columns(2)
            with c1:
                st.link_button("🚀 OrcaSlicer'ı Aç (HTTPS)", orca_https, use_container_width=True, type="primary")
            with c2:
                st.link_button("🚀 OrcaSlicer'ı Aç (HTTP)", orca_http, use_container_width=True)
            st.caption("💡 Tarayıcı sertifika uyarısı verirse 'Yine de devam et' seçin.")