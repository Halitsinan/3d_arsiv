import os
import sys
import psycopg2

# Path düzeltmesi
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.indexer import get_drive_service

DB_CONFIG = {
    "dbname": "asset_db",
    "user": "postgres",
    "password": "gizli_sifre",
    "host": "localhost",
    "port": "5435"
}

def fix_names():
    print("🏷️ İsim Düzeltme Başladı...")
    
    # 1. Google Drive klasör isimlerini düzelt
    svc = get_drive_service()
    if svc:
        print("\n📂 Google Drive klasör isimleri düzeltiliyor...")
        token = None
        while True:
            try:
                res = svc.files().list(q="name contains 'Copy of' and mimeType='application/vnd.google-apps.folder' and trashed=false", fields="nextPageToken, files(id, name)", pageToken=token).execute()
                files = res.get('files', [])
                if not files: break
                
                for f in files:
                    new_name = f['name'].replace("Copy of ", "").replace("Kopyası ", "").strip()
                    svc.files().update(fileId=f['id'], body={'name': new_name}).execute()
                    print(f"  ✏️ Drive: {f['name']} -> {new_name}")
                
                token = res.get('nextPageToken')
                if not token: break
            except Exception as e: 
                print(f"  ⚠️ Drive hatası: {e}")
                break
    
    # 2. Database source tablosundaki isimleri düzelt VE Google Drive'dan gerçek isimleri çek
    print("\n🗄️ Database kaynak isimleri düzeltiliyor...")
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        
        # Google Drive kaynaklarının gerçek isimlerini çek
        if svc:
            cur.execute("SELECT id, name, drive_id FROM source WHERE source_type='gdrive'")
            gdrive_sources = cur.fetchall()
            
            for sid, old_name, drive_id in gdrive_sources:
                try:
                    # Google Drive'dan gerçek klasör adını çek
                    file_metadata = svc.files().get(fileId=drive_id, fields="name").execute()
                    real_name = file_metadata.get('name', old_name)
                    
                    # Gereksiz prefix'leri temizle
                    clean_name = real_name.replace("Copy of ", "").replace("Kopyası ", "").replace("Import-", "").strip()
                    
                    if clean_name != old_name:
                        cur.execute("UPDATE source SET name=%s WHERE id=%s", (clean_name, sid))
                        print(f"  ✏️ ID {sid}: {old_name} -> {clean_name}")
                        conn.commit()
                except Exception as e:
                    print(f"  ⚠️ ID {sid} hatası: {e}")
        
        # Local kaynaklardaki gereksiz prefix'leri temizle
        cur.execute("SELECT id, name FROM source WHERE source_type='local'")
        local_sources = cur.fetchall()
        
        for sid, name in local_sources:
            clean_name = name.replace("Copy of ", "").replace("Kopyası ", "").replace("Import-", "").strip()
            
            if clean_name != name:
                cur.execute("UPDATE source SET name=%s WHERE id=%s", (clean_name, sid))
                print(f"  ✏️ DB: {name} -> {clean_name}")
                conn.commit()
        
        cur.close()
        conn.close()
        print("\n✅ İsim düzeltme tamamlandı!")
        
    except Exception as e:
        print(f"  ⚠️ Database hatası: {e}")
        
if __name__ == "__main__": fix_names()