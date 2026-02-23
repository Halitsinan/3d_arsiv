import os
import io
import sys
import psycopg2
import zipfile
import rarfile
import py7zr
import time
import shutil
import re
from concurrent.futures import ThreadPoolExecutor
from googleapiclient.errors import HttpError

# Path ayarı
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from googleapiclient.http import MediaIoBaseDownload
from app.indexer import get_drive_service, extract_best_image_recursive
from app.renderer import render_3d_model

# --- AYARLAR ---
BASE_WORK_DIR = "/home/hsa/3d_asset_manager/temp_work"
os.makedirs(BASE_WORK_DIR, exist_ok=True)
MAX_WORKERS = 5  # Aynı anda işlenecek dosya sayısı

DB_CONFIG = {
    "dbname": "asset_db",
    "user": "postgres",
    "password": "gizli_sifre",
    "host": "localhost",
    "port": "5435"
}

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

def find_files_recursively(directory):
    """Arşiv içinde önce resim, sonra model arar."""
    image_extensions = ('.jpg', '.jpeg', '.png', '.webp')
    model_extensions = ('.stl', '.obj')
    
    found_image = None
    found_model = None

    for root, dirs, files in os.walk(directory):
        # Gereksiz sistem dosyalarını ve Mac çöp dosyalarını atla
        if "__MACOSX" in root or any(d.startswith('.') for d in root.split(os.sep)):
            continue
        
        for file in files:
            if file.startswith('.'): continue
            file_lower = file.lower()
            full_path = os.path.join(root, file)
            
            # 1. Resim (Öncelikli)
            if not found_image and file_lower.endswith(image_extensions):
                # 'render', 'preview' gibi kelimeler içerenlere öncelik ver
                if any(x in file_lower for x in ['render', 'preview', 'display', 'screenshot']):
                     return full_path, "image"
                found_image = full_path
            
            # 2. Model
            if not found_model and file_lower.endswith(model_extensions):
                found_model = full_path
                
    # Eğer özel isimli resim bulamadıysak ama normal resim varsa onu döndür
    if found_image: return found_image, "image"
    if found_model: return found_model, "model"
    
    return None, None

def process_single_asset(asset_data):
    """Tek bir dosyayı indirip işleyen Worker Fonksiyonu"""
    aid, fname, fpath = asset_data
    # Her thread kendi temp klasörünü kullanmalı
    thread_id = str(int(time.time() * 1000000) % 1000000)
    local_filename = f"{thread_id}_{fname}"
    local_path = os.path.join(BASE_WORK_DIR, local_filename)
    
    conn = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        svc = get_drive_service()
        
        # 1. Güvenli ID Çekme
        match = re.search(r'[-\w]{25,}', fpath)
        file_id = match.group() if match else None

        if not file_id:
            print(f"    🚨 [ID:{aid}] Geçersiz Link: {fname}")
            cur.execute("UPDATE assets SET thumbnail_attempts = 99 WHERE id=%s", (aid,))
            conn.commit()
            return

        # 2. İndirme (KLASÖR KORUMASI EKLENDİ)
        try:
            print(f"⬇️  [T-{thread_id}] İndiriliyor: {fname}")
            request = svc.files().get_media(fileId=file_id)
            with open(local_path, "wb") as f:
                downloader = MediaIoBaseDownload(f, request)
                done = False
                while not done: _, done = downloader.next_chunk()
        
        except HttpError as e:
            # Eğer hata "fileNotDownloadable" ise bu bir klasördür
            if "fileNotDownloadable" in str(e):
                print(f"    🚫 [T-{thread_id}] Bu bir KLASÖR (Atlandı): {fname}")
                cur.execute("UPDATE assets SET thumbnail_attempts = 99 WHERE id=%s", (aid,))
                conn.commit()
                return
            else:
                raise e

        # 3. Dosya Türüne Göre İşleme
        ext = os.path.splitext(local_path)[1].lower()
        blob = None
        
        # DOĞRUDAN 3D MODEL DOSYALARI
        if ext in ['.stl', '.obj']:
            print(f"    🎯 [T-{thread_id}] 3D Model Render Ediliyor: {fname}")
            try:
                blob = render_3d_model(local_path)
                if blob:
                    print(f"    ✅ [T-{thread_id}] Render başarılı!")
                else:
                    print(f"    ⚠️ [T-{thread_id}] Render başarısız (boş döndü)")
            except Exception as e:
                print(f"    ❌ [T-{thread_id}] Render hatası: {e}")
        
        # ARŞİV DOSYALARI
        elif ext in ['.zip', '.rar', '.cbz', '.cbr', '.7z']:
            temp_extract_dir = os.path.join(BASE_WORK_DIR, f"ext_{thread_id}")
            os.makedirs(temp_extract_dir, exist_ok=True)
            
            try:
                # Arşiv türüne göre aç
                if ext == '.7z':
                    with py7zr.SevenZipFile(local_path, mode='r') as a: a.extractall(path=temp_extract_dir)
                elif ext in ['.zip', '.cbz']:
                    with zipfile.ZipFile(local_path, 'r') as a: a.extractall(path=temp_extract_dir)
                elif ext in ['.rar', '.cbr']:
                    with rarfile.RarFile(local_path, 'r') as a: a.extractall(path=temp_extract_dir)
                
                # Hibrit Arama: Resim > Model
                target_path, target_type = find_files_recursively(temp_extract_dir)
                
                if target_type == "image":
                    print(f"    🖼️  [T-{thread_id}] Resim bulundu: {fname}")
                    with open(target_path, "rb") as f: blob = f.read()
                elif target_type == "model":
                    print(f"    🎯 [T-{thread_id}] Model render ediliyor: {fname}")
                    blob = render_3d_model(target_path)
                else:
                    print(f"    ℹ️  [T-{thread_id}] İçerik bulunamadı: {fname}")
            
            except Exception as e:
                print(f"    ⚠️ [T-{thread_id}] Arşiv hatası ({fname}): {e}")
            finally:
                if os.path.exists(temp_extract_dir): shutil.rmtree(temp_extract_dir)
        
        else:
            print(f"    ⏭️  [T-{thread_id}] Desteklenmeyen format: {ext}")

        # 4. Sonucu Kaydet
        if blob:
            cur.execute("UPDATE assets SET thumbnail_blob=%s, thumbnail_attempts = 10 WHERE id=%s", (blob, aid))
            print(f"    ✅ [T-{thread_id}] BAŞARILI: {fname}")
        else:
            cur.execute("UPDATE assets SET thumbnail_attempts = thumbnail_attempts + 1 WHERE id=%s", (aid,))
            print(f"    ❌ [T-{thread_id}] Başarısız: {fname}")
        
        conn.commit()

    except Exception as e:
        print(f"    🚨 [T-{thread_id}] Kritik Hata ({fname}): {e}")
        if conn: conn.rollback()
    finally:
        if conn: conn.close()
        if os.path.exists(local_path): os.remove(local_path)

def deep_scan():
    print(f"🚀 Deep Scan (MULTI-THREAD x{MAX_WORKERS}) Başladı: {time.strftime('%H:%M:%S')}")
    
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # ÖNCELİK KONTROL: Aynı klasörde aynı isimli resim varsa arşivi atla
        print("🔍 Öncelik analizi yapılıyor...")
        cur.execute("""
            SELECT a1.id, a1.filename, a1.folder_path 
            FROM assets a1
            WHERE a1.thumbnail_blob IS NULL 
            AND a1.thumbnail_attempts < 3
            AND (a1.filename ILIKE '%.zip' OR a1.filename ILIKE '%.rar' OR a1.filename ILIKE '%.7z'
                 OR a1.filename ILIKE '%.stl' OR a1.filename ILIKE '%.obj')
        """)
        archive_rows = cur.fetchall()
        
        skipped_count = 0
        for aid, fname, folder in archive_rows:
            # Base name çıkar (uzantı olmadan) - Hem dosya adı hem de case-insensitive
            base_name = os.path.splitext(fname)[0].lower()
            
            # Aynı klasörde aynı base name'e sahip resim var mı? (Görsel dosya türleri)
            cur.execute("""
                SELECT id, filename FROM assets 
                WHERE LOWER(folder_path) = LOWER(%s)
                AND (LOWER(filename) LIKE %s OR LOWER(filename) LIKE %s 
                     OR LOWER(filename) LIKE %s OR LOWER(filename) LIKE %s 
                     OR LOWER(filename) LIKE %s OR LOWER(filename) LIKE %s)
                LIMIT 1
            """, (folder, f"{base_name}.jpg", f"{base_name}.jpeg", f"{base_name}.png", 
                  f"{base_name}.webp", f"{base_name}.bmp", f"{base_name}.gif"))
            
            has_image = cur.fetchone()
            if has_image:
                print(f"    ⏭️  Atlandı (Görsel mevcut: {has_image[1]}): {fname}")
                cur.execute("UPDATE assets SET thumbnail_attempts = 99 WHERE id=%s", (aid,))
                skipped_count += 1
        
        conn.commit()
        if skipped_count > 0:
            print(f"✅ {skipped_count} dosya atlandı (görsel zaten var)")
        
        # 100 dosyalık paket çek
        cur.execute("""
            SELECT id, filename, filepath FROM assets 
            WHERE thumbnail_blob IS NULL 
            AND thumbnail_attempts < 3
            ORDER BY id ASC LIMIT 100
        """)
        rows = cur.fetchall()
        cur.close(); conn.close()

        if not rows:
            print("💤 İşlenecek dosya kalmadı.")
            return

        print(f"📊 Havuza {len(rows)} dosya gönderiliyor...")
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            executor.map(process_single_asset, rows)
        
        print(f"\n🏁 DEEP SCAN TAMAMLANDI! {len(rows)} dosya işlendi.")
        print(f"⏰ Bitiş Zamanı: {time.strftime('%H:%M:%S')}")
            
    except Exception as e:
        print(f"❌ Ana Süreç Hatası: {e}")

if __name__ == "__main__": 
    deep_scan()