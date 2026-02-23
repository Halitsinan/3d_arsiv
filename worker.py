import os
import sys
import psycopg2
import zipfile
import rarfile
import py7zr
import time
import shutil
import fcntl

# Proje yolunu ekle
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from googleapiclient.http import MediaIoBaseDownload
from app.indexer import get_drive_service, extract_best_image_recursive
from app.renderer import render_3d_model

# --- HDD AYARLARI ---
BASE_WORK_DIR = "/home/hsa/3d_asset_manager/temp_work"
os.makedirs(BASE_WORK_DIR, exist_ok=True)

DB_CONFIG = {
    "dbname": "asset_db",
    "user": "postgres",
    "password": "gizli_sifre",
    "host": "localhost",
    "port": "5435"
}

def find_3d_file_recursively(directory):
    """Klasör içindeki tüm alt klasörleri gezip ilk STL veya OBJ'yi bulur."""
    for root, dirs, files in os.walk(directory):
        for file in files:
            # Gizli dosyaları ve Mac çöp dosyalarını atla
            if file.startswith('.') or "__MACOSX" in root:
                continue
            if file.lower().endswith(('.stl', '.obj')):
                return os.path.join(root, file)
    return None

def extract_and_render_from_archive(archive_path):
    """Arşivi HDD'ye açar, derinlemesine arar ve render alır."""
    ext = os.path.splitext(archive_path)[1].lower()
    timestamp = str(int(time.time() * 1000))
    temp_extract_dir = os.path.join(BASE_WORK_DIR, f"extract_{timestamp}")
    os.makedirs(temp_extract_dir, exist_ok=True)
    
    blob = None
    try:
        # 1. Arşiv Türüne Göre Tam Ayıklama
        print(f"      📦 Ayıklanıyor: {ext}...")
        if ext == '.7z':
            with py7zr.SevenZipFile(archive_path, mode='r') as a:
                a.extractall(path=temp_extract_dir)
        elif ext in ['.zip', '.cbz']:
            with zipfile.ZipFile(archive_path, 'r') as a:
                a.extractall(path=temp_extract_dir)
        elif ext in ['.rar', '.cbr']:
            with rarfile.RarFile(archive_path, 'r') as a:
                a.extractall(path=temp_extract_dir)

        # 2. Ayıklanan klasörde DERİN ARAMA yap
        found_path = find_3d_file_recursively(temp_extract_dir)
        
        if found_path:
            print(f"      🎯 Dosya bulundu: {os.path.relpath(found_path, temp_extract_dir)}")
            blob = render_3d_model(found_path)
            if blob:
                print(f"      🎨 Render başarılı!")
        else:
            print(f"      ℹ️ Arşiv içinde geçerli 3D dosya (.stl, .obj) yok.")

    except Exception as e:
        print(f"      🚨 Ayıklama Hatası: {e}")
    finally:
        # HDD'yi temizle
        if os.path.exists(temp_extract_dir):
            shutil.rmtree(temp_extract_dir)
    return blob

def deep_scan():
    print(f"⬇️ HDD Derin Tarama Başladı: {time.strftime('%H:%M:%S')}")
    
    # Lock dosyası ile çakışmayı önle
    lock_file_path = os.path.join(BASE_WORK_DIR, "worker.lock")
    lock_file = None
    
    try:
        # Lock dosyasını aç/oluştur
        lock_file = open(lock_file_path, 'w')
        
        # Non-blocking lock dene
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("⚠️ Başka bir worker çalışıyor, bu çalışma atlanıyor.")
            return
        
        print("🔒 Worker lock alındı, işlem başlıyor...")
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        svc = get_drive_service()
        
        # İstatistik
        cur.execute("SELECT COUNT(*) FROM assets WHERE thumbnail_blob IS NULL AND thumbnail_attempts < 3")
        total_waiting = cur.fetchone()[0]
        print(f"📊 DURUM: Taranmayı bekleyen {total_waiting} dosya var.")

        if svc:
            # Deneme sayısı az olan resimsizleri getir
            cur.execute("""
                SELECT id, filename, filepath FROM assets 
                WHERE thumbnail_blob IS NULL AND thumbnail_attempts < 3
                ORDER BY thumbnail_attempts ASC, id DESC LIMIT 100
            """)
            
            for aid, fname, fpath in cur.fetchall():
                local_path = os.path.join(BASE_WORK_DIR, fname)
                try:
                    # Extension kontrolü
                    ext = os.path.splitext(fname)[1].lower()
                    is_gdrive = 'drive.google.com' in fpath or '/d/' in fpath

                    # Uzantı yoksa: GDrive assetse dene, değilse atla
                    if not ext and not is_gdrive:
                        print(f"⏭️ Atlandı (klasör/geçersiz): {fname}")
                        cur.execute("UPDATE assets SET thumbnail_attempts = thumbnail_attempts + 1 WHERE id=%s", (aid,))
                        conn.commit()
                        continue

                    # Çok parçalı RAR kontrolü
                    import re as _re
                    is_multipart = bool(_re.search(r'\.part\d+\.rar$', fname.lower())) or bool(_re.search(r'\.r\d+$', fname.lower()))
                    part_num = 0
                    m = _re.search(r'\.part(\d+)\.rar$', fname.lower())
                    if m: part_num = int(m.group(1))

                    if is_multipart and part_num > 1:
                        # part2, part3... — sadece Drive thumbnail'ini almayı dene
                        print(f"⏭️ Atlandı (çok parçalı RAR, part {part_num}): {fname}")
                        cur.execute("UPDATE assets SET thumbnail_attempts = 10 WHERE id=%s", (aid,))
                        conn.commit()
                        continue
                    
                    file_id = fpath.split("id=")[1].split("&")[0] if "id=" in fpath else fpath.split("/d/")[1].split("/")[0]
                    
                    print(f"⬇️ İşleniyor: {fname}")
                    request = svc.files().get_media(fileId=file_id)
                    with open(local_path, "wb") as f:
                        downloader = MediaIoBaseDownload(f, request)
                        done = False
                        while not done:
                            _, done = downloader.next_chunk()
                    
                    blob = None
                    ext = os.path.splitext(fname)[1].lower()

                    # part1.rar veya .r00 (çok parçalı) → extract etme, sadece Drive thumbnail dene
                    import re as _re
                    if _re.search(r'\.part1\.rar$', fname.lower()) or _re.search(r'\.r00$', fname.lower()):
                        print(f"      📦 Çok parçalı RAR part1 — extract edilemiyor, Drive thumbnail deneniyor")
                        # Dosyayı indirmeden Drive API thumbnail'ini svc ile al
                        try:
                            fmeta = svc.files().get(fileId=file_id, fields='thumbnailLink').execute()
                            tlink = fmeta.get('thumbnailLink', '')
                            if tlink:
                                import requests as _req
                                blob = _req.get(tlink.split('=')[0] + '=s400', timeout=10).content
                        except Exception as et:
                            print(f"      ⚠️ Drive thumbnail alınamadı: {et}")
                        if blob:
                            cur.execute("UPDATE assets SET thumbnail_blob=%s, thumbnail_attempts = 10 WHERE id=%s", (blob, aid))
                            conn.commit()
                            print(f"    ✅ Drive thumbnail alındı!")
                        else:
                            cur.execute("UPDATE assets SET thumbnail_attempts = 10 WHERE id=%s", (aid,))
                            conn.commit()
                        continue

                    # Uzantı yoksa (GDrive klasör-adı olarak kaydedilmiş) → magic bytes ile tespit et
                    if not ext:
                        with open(local_path, 'rb') as _f:
                            magic = _f.read(8)
                        if magic[:2] == b'PK':
                            ext = '.zip'
                        elif magic[:6] == b'7z\xbc\xaf\x27\x1c':
                            ext = '.7z'
                        elif magic[:7] in (b'Rar!\x1a\x07\x00',) or magic[:8] == b'Rar!\x1a\x07\x01\x00':
                            ext = '.rar'
                        else:
                            # STL dene (solid text veya binary)
                            ext = '.stl'
                        print(f"      🔍 Uzantı yok, magic bytes → {ext}")
                        # Dosyayı rename et
                        new_local = local_path + ext
                        os.rename(local_path, new_local)
                        local_path = new_local

                    # Dosya tipine göre işlem yap
                    if ext in ['.stl', '.obj']:
                        # Direkt 3D dosya → Render al
                        print(f"      🎨 3D dosya tespit edildi, render alınıyor...")
                        blob = render_3d_model(local_path)
                    
                    elif ext in ['.zip', '.rar', '.7z', '.cbz', '.cbr']:
                        # Arşiv dosyası → İçinde resim/3D ara
                        print(f"      📦 Arşiv tespit edildi...")
                        # Önce hazır resim ara
                        blob = extract_best_image_recursive(local_path)
                        
                        # Yoksa içinde 3D dosya bul ve render al
                        if not blob:
                            blob = extract_and_render_from_archive(local_path)
                    
                    else:
                        print(f"      ⚠️ Desteklenmeyen dosya tipi: {ext}")

                    if blob:
                        cur.execute("UPDATE assets SET thumbnail_blob=%s, thumbnail_attempts = 10 WHERE id=%s", (blob, aid))
                        conn.commit()
                        print(f"    ✅ İŞLEM BAŞARILI!")
                    else:
                        cur.execute("UPDATE assets SET thumbnail_attempts = thumbnail_attempts + 1 WHERE id=%s", (aid,))
                        conn.commit()
                        print(f"    ❌ Resim/Render üretilemedi.")

                except Exception as e:
                    print(f"    🚨 Kritik Hata: {e}")
                    cur.execute("UPDATE assets SET thumbnail_attempts = thumbnail_attempts + 1 WHERE id=%s", (aid,))
                    conn.commit()
                finally:
                    if os.path.exists(local_path):
                        os.remove(local_path)

        cur.close(); conn.close()
        print(f"✅ Tarama tamamlandı: {time.strftime('%H:%M:%S')}")
        
    except Exception as e:
        print(f"❌ DB Hatası: {e}")
    
    finally:
        # Lock'u serbest bırak
        if lock_file:
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
                os.remove(lock_file_path)
                print("🔓 Worker lock serbest bırakıldı.")
            except:
                pass

if __name__ == "__main__": 
    deep_scan()