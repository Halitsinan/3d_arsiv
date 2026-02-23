import sys
import os

# --- KRİTİK DÜZELTME: Ana klasörü Python'a tanıtıyoruz ---
# Bu sayede 'from app.indexer' komutu hata vermez.
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import requests
import io
import time
from PIL import Image
from app.indexer import connect_db, get_drive_service, extract_best_image_recursive, process_image
from app.renderer import render_3d_model

def retry_missing_thumbnails():
    print("🕵️‍♂️ Kayıp Thumbnail Avı Başladı...")
    
    conn = connect_db()
    cur = conn.cursor()
    svc = get_drive_service()
    
    # Sadece thumbnail_blob'u NULL olanları getir
    cur.execute("SELECT COUNT(*) FROM assets WHERE thumbnail_blob IS NULL")
    total_missing = cur.fetchone()[0]
    print(f"📉 Toplam {total_missing} adet eksik resim var.")
    
    if total_missing == 0:
        print("✅ Her şey tamam, eksik yok.")
        return

    offset = 0
    batch_size = 50
    
    while True:
        # Cursor'ı her turda yenilemek bazen bağlantı kopmasını önler
        cur.execute("""
            SELECT id, filename, filepath, source_id, folder_path 
            FROM assets 
            WHERE thumbnail_blob IS NULL 
            ORDER BY id DESC 
            LIMIT %s OFFSET %s
        """, (batch_size, offset))
        
        rows = cur.fetchall()
        if not rows: break
        
        for aid, fname, fpath, sid, folder_path in rows:
            blob = None
            try:
                # 1. SENARYO: GOOGLE DRIVE
                if fpath.startswith('http'):
                    if svc:
                        file_id = None
                        if "id=" in fpath: file_id = fpath.split("id=")[1].split("&")[0]
                        elif "/d/" in fpath: file_id = fpath.split("/d/")[1].split("/")[0]
                        
                        if file_id:
                            try:
                                meta = svc.files().get(fileId=file_id, fields="thumbnailLink, mimeType").execute()
                                if 'thumbnailLink' in meta:
                                    link = meta['thumbnailLink'].split('=')[0] + "=s400"
                                    blob = requests.get(link, timeout=10).content
                                    print(f"☁️ Drive'dan Kurtarıldı: {fname}")
                            except: pass

                # 2. SENARYO: YEREL DOSYA
                elif os.path.exists(fpath):
                    ext = os.path.splitext(fpath)[1].lower()
                    
                    if ext in ['.jpg', '.jpeg', '.png']:
                        with open(fpath, "rb") as f: blob = process_image(f.read())
                        if blob: print(f"🖼️ Resim Okundu: {fname}")

                    elif ext in ['.zip', '.rar', '.cbz', '.7z']:
                        blob = extract_best_image_recursive(fpath)
                        if blob: print(f"📦 Arşivden Çıkarıldı: {fname}")

                    elif ext in ['.stl', '.obj', '.fbx']:
                        print(f"🎨 Render Alınıyor: {fname}")
                        blob = render_3d_model(fpath)

            except Exception as e:
                print(f"Hata ({fname}): {e}")

            if blob:
                cur.execute("UPDATE assets SET thumbnail_blob = %s WHERE id = %s", (blob, aid))
                conn.commit()
            
        offset += batch_size
        print(f"⏳ {min(offset, total_missing)}/{total_missing} tarandı...")

    conn.close()
    print("✅ Tamamlandı.")

if __name__ == "__main__":
    retry_missing_thumbnails()