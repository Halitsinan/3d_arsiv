import os
import sys
import psycopg2
import zipfile
import rarfile
import io
import requests
import shutil
from PIL import Image
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- BU SATIR ÇALIŞTIĞINI KANITLAR ---
print("🚀 Indexer Scripti Yüklendi...")

Image.MAX_IMAGE_PIXELS = None 

# --- AYARLAR ---
DB_CONFIG = {
    "dbname": "asset_db",
    "user": "postgres",
    "password": "gizli_sifre",
    "host": "localhost",
    "port": "5435"
}
CREDENTIALS = '/home/hsa/3d_asset_manager/app/service_account.json'

def connect_db(): return psycopg2.connect(**DB_CONFIG)

def get_drive_service():
    if not os.path.exists(CREDENTIALS): 
        print(f"⚠️ HATA: Kimlik dosyası yok: {CREDENTIALS}")
        return None
    creds = service_account.Credentials.from_service_account_file(CREDENTIALS)
    return build('drive', 'v3', credentials=creds)

def process_image(image_data):
    try:
        img = Image.open(io.BytesIO(image_data))
        if img.mode in ("RGBA", "P", "CMYK"): img = img.convert("RGB")
        img.thumbnail((400, 400))
        output = io.BytesIO()
        img.save(output, format="JPEG", quality=75)
        return output.getvalue()
    except: return None

def score_filename(filename):
    fn = filename.lower()
    score = 0
    if 'render' in fn: score += 100
    if 'preview' in fn: score += 80
    if 'main' in fn: score += 70
    if 'thumb' in fn: score += 60
    if fn.endswith('.jpg') or fn.endswith('.jpeg'): score += 10
    return score

def extract_best_image_recursive(file_path):
    best_img = None
    best_score = -1
    
    if file_path.lower().endswith('.rar') and not shutil.which("unrar"):
        print("⚠️ Uyarı: 'unrar' komutu bulunamadı.")
        return None

    try:
        ext = os.path.splitext(file_path)[1].lower()
        archive = None
        file_list = []
        
        if ext in ['.zip', '.cbz']: 
            if not zipfile.is_zipfile(file_path): return None
            archive = zipfile.ZipFile(file_path, 'r')
            file_list = archive.infolist()
        elif ext in ['.rar', '.cbr']: 
            if not rarfile.is_rarfile(file_path): return None
            archive = rarfile.RarFile(file_path, 'r')
            file_list = archive.infolist()
        
        if not archive: return None

        for info in file_list:
            if "__MACOSX" in info.filename or info.filename.startswith('.'): continue
            if info.filename.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                current_score = score_filename(info.filename) + (info.file_size / 1024 / 1024)
                if current_score > best_score:
                    try:
                        data = archive.read(info)
                        processed = process_image(data)
                        if processed:
                            best_img = processed
                            best_score = current_score
                    except: pass
        archive.close()
    except: pass
    return best_img

def is_multipart_rar(filename):
    """Checks if file is a multi-part RAR: .part1.rar, .part2.rar, .r00, .r01 etc."""
    fn = filename.lower()
    import re
    return bool(re.search(r'\.part\d+\.rar$', fn)) or bool(re.search(r'\.r\d+$', fn))

def multipart_rar_index(filename):
    """Returns part number from multi-part RAR filename, or 0 if not detected."""
    import re
    m = re.search(r'\.part(\d+)\.rar$', filename.lower())
    if m: return int(m.group(1))
    m = re.search(r'\.r(\d+)$', filename.lower())
    if m: return int(m.group(1)) + 1  # .r00 = part2
    return 0


    token = None
    while True:
        try:
            results = service.files().list(
                q=f"'{folder_id}' in parents and trashed=false",
                fields="nextPageToken, files(id, name, mimeType, size, thumbnailLink, webViewLink, parents)",
                pageToken=token, pageSize=100
            ).execute()
            
            files = results.get('files', [])
            if not files: break

            # Dosya türlerine göre ayır
            folders = [f for f in files if f.get('mimeType') == 'application/vnd.google-apps.folder']
            direct_files = [f for f in files if f.get('mimeType') != 'application/vnd.google-apps.folder']
            
            # Eğer alt klasör VARSA → Sadece recursive tara, burada kayıt yapma
            if folders:
                for folder_item in folders:
                    folder_name = folder_item['name']
                    new_path = f"{path}/{folder_name}" if path else folder_name
                    print(f"📂 Klasör: {new_path}")
                    scan_drive(service, folder_item['id'], source_id, cur, conn, new_path)
            
            # Eğer bu klasörde SADECE DOSYALAR varsa → Grupla ve kaydet
            if direct_files and not folders:
                # Dosya türlerine göre grupla
                images = []
                archives = []
                models = []
                
                for item in direct_files:
                    fname_lower = item['name'].lower()
                    if fname_lower.endswith(('.jpg', '.jpeg', '.png', '.webp', '.bmp', '.gif')):
                        images.append(item)
                    elif fname_lower.endswith(('.zip', '.rar', '.7z', '.cbz', '.cbr')):
                        archives.append(item)
                    elif fname_lower.endswith(('.stl', '.obj', '.fbx', '.blend', '.step', '.3ds', '.dae')):
                        models.append(item)
                
                # GRUPLAMA: Eğer model/arşiv varsa tek kayıt yap
                if archives or models:
                    # Klasör adını asset ismi olarak kullan (path'in son kısmı)
                    asset_name = path.split('/')[-1] if path else "Root"
                    
                    # Thumbnail: Önce görsel ara, yoksa model/arşiv dosyasının kendi Drive thumbnail'ı
                    thumb_blob = None
                    if images:
                        img_file = images[0]
                        if 'thumbnailLink' in img_file:
                            try:
                                thumb_blob = requests.get(img_file['thumbnailLink'].split('=')[0] + "=s250", timeout=5).content
                            except: pass
                    
                    # Çok parçalı RAR'ları grupla: sadece part1'i (veya en küçük parçayı) kaydet
                    multipart_rars = [a for a in archives if is_multipart_rar(a['name'])]
                    normal_archives = [a for a in archives if not is_multipart_rar(a['name'])]
                    
                    if multipart_rars and not normal_archives and not models:
                        # Sadece çok parçalı RAR var — part1'i bul
                        part1 = min(multipart_rars, key=lambda x: multipart_rar_index(x['name']))
                        model_file = part1
                        if not thumb_blob and 'thumbnailLink' in part1:
                            try:
                                thumb_blob = requests.get(part1['thumbnailLink'].split('=')[0] + "=s250", timeout=5).content
                            except: pass
                    else:
                        # Normal arşiv veya model dosyası: Önce normal archive, yoksa model
                        model_file = (normal_archives[0] if normal_archives else None) or (models[0] if models else None)
                        if not thumb_blob and model_file and 'thumbnailLink' in model_file:
                            try:
                                thumb_blob = requests.get(model_file['thumbnailLink'].split('=')[0] + "=s250", timeout=5).content
                            except: pass
                    
                    if not model_file:
                        continue
                    model_link = model_file.get('webViewLink')
                    model_size = int(model_file.get('size', 0))
                    
                    print(f"    📦 Grup: {asset_name} (📷 {len(images)} görsel, 📦 {len(archives)} arşiv, 🔷 {len(models)} model)")
                    
                    try:
                        cur.execute("""
                            INSERT INTO assets (filename, filepath, source_id, file_size, thumbnail_blob, folder_path)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (filepath) DO UPDATE SET file_size=EXCLUDED.file_size, thumbnail_blob=EXCLUDED.thumbnail_blob
                        """, (asset_name, model_link, source_id, model_size, thumb_blob, path))
                        conn.commit()
                    except Exception as e:
                        print(f"    ⚠️ Kayıt hatası: {e}")
                        conn.rollback()
            
            # Eğer bu klasörde ALT KLASÖR VAR ama aynı zamanda DOĞRUDAN DOSYALAR da varsa
            # Bu dosyaları ayrı ayrı kaydet (karışık yapı)
            elif direct_files and folders:
                for item in direct_files:
                    name = item['name']
                    size = int(item.get('size', 0))
                    fname_lower = name.lower()
                    
                    if fname_lower.endswith(('.zip', '.rar', '.7z', '.cbz', '.cbr', '.stl', '.obj', '.fbx', '.blend', '.step', '.3ds', '.dae')):
                        thumb = None
                        if 'thumbnailLink' in item:
                            try: 
                                thumb = requests.get(item['thumbnailLink'].split('=')[0] + "=s250", timeout=5).content
                            except: pass
                        
                        try:
                            print(f"📄 Dosya: {name}")
                            cur.execute("""
                                INSERT INTO assets (filename, filepath, source_id, file_size, thumbnail_blob, folder_path)
                                VALUES (%s, %s, %s, %s, %s, %s)
                                ON CONFLICT (filepath) DO UPDATE SET file_size=EXCLUDED.file_size, thumbnail_blob=EXCLUDED.thumbnail_blob
                            """, (name, item.get('webViewLink'), source_id, size, thumb, path))
                            conn.commit()
                        except Exception as e:
                            print(f"⚠️ Dosya hatası: {e}")
                            conn.rollback()

            # Her sayfa işlemi bitince
            token = results.get('nextPageToken')
            if not token: break
        except Exception as e:
            print(f"❌ Drive Hatası: {e}")
            conn.rollback()
            break

def scan_local(cur, conn):
    cur.execute("SELECT id, path FROM source WHERE source_type='local'")
    sources = cur.fetchall()
    
    # --- EĞER HİÇ KAYNAK YOKSA UYAR ---
    if not sources:
        print("⚠️ Veritabanında kayıtlı 'local' kaynak yok.")

    for sid, spath in sources:
        if not os.path.exists(spath): 
            print(f"⚠️ Yol bulunamadı: {spath}")
            continue
        print(f"🚀 Yerel Tarama Başlıyor: {spath}")
        for root, dirs, files in os.walk(spath):
            rel_path = os.path.relpath(root, spath)
            if rel_path == ".": rel_path = ""
            three_d_files = []
            image_files = []
            archive_count = 0
            
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                full_path = os.path.join(root, file)
                
                # Arşiv dosyaları - HER BİRİNİ TEK TEK KAYDET
                if ext in ['.zip', '.rar', '.cbz', '.cbr', '.7z']:
                    try:
                        thumb = extract_best_image_recursive(full_path)
                        f_size = os.path.getsize(full_path)
                        print(f"📦 Arşiv: {file}")
                        cur.execute("""
                            INSERT INTO assets (filename, filepath, source_id, file_size, thumbnail_blob, folder_path)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            ON CONFLICT (filepath) DO UPDATE SET file_size=EXCLUDED.file_size, thumbnail_blob=EXCLUDED.thumbnail_blob
                        """, (file, full_path, sid, f_size, thumb, rel_path))
                        conn.commit()  # Her arşivi hemen kaydet
                        archive_count += 1
                    except Exception as e:
                        print(f"⚠️ Arşiv hatası ({file}): {e}")
                        conn.rollback()
                
                # 3D dosyaları
                elif ext in ['.stl', '.obj', '.fbx', '.blend', '.step', '.3ds', '.dae']:
                    three_d_files.append((file, full_path))
                
                # Görsel dosyaları
                elif ext in ['.jpg', '.jpeg', '.png', '.webp']:
                    image_files.append((file, full_path))
            
            # 3D dosyaları varsa VE alt klasördeyse grupla
            # Ana dizinde (rel_path == "") ise SADECE 5+ dosya varsa grupla
            should_group = False
            if three_d_files:
                if rel_path != "":  # Alt klasördeyse
                    should_group = True
                elif len(three_d_files) >= 5:  # Ana dizinde ve çok dosya varsa
                    should_group = True
            
            if should_group:
                folder_name = os.path.basename(root) if rel_path else f"Proje_{len(three_d_files)}_Dosya"
                
                # Klasör için thumbnail bul
                folder_thumb = None
                if image_files:
                    for img_name, img_path in image_files:
                        if 'render' in img_name.lower() or 'preview' in img_name.lower():
                            try:
                                with open(img_path, 'rb') as f:
                                    folder_thumb = process_image(f.read())
                                break
                            except: pass
                    if not folder_thumb and image_files:
                        try:
                            with open(image_files[0][1], 'rb') as f:
                                folder_thumb = process_image(f.read())
                        except: pass
                
                try:
                    print(f"📁 3D Klasör: {folder_name} ({len(three_d_files)} dosya)")
                    cur.execute("""
                        INSERT INTO assets (filename, filepath, source_id, file_size, thumbnail_blob, folder_path)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (filepath) DO UPDATE SET thumbnail_blob=EXCLUDED.thumbnail_blob
                    """, (folder_name, root, sid, 0, folder_thumb, rel_path))
                    conn.commit()
                except Exception as e:
                    print(f"⚠️ Klasör hatası: {e}")
                    conn.rollback()
            
            # Her klasör işlendikten sonra durum raporu
            if archive_count > 0 or three_d_files:
                print(f"✅ {root}: {archive_count} arşiv, {len(three_d_files)} 3D dosya işlendi")

def main():
    print("🚦 Main Fonksiyonu Başladı...")
    
    # İlk iş: İsimleri temizle
    try:
        from app.fix_names import fix_names
        fix_names()
        print("✅ İsim temizleme tamamlandı.\n")
    except Exception as e:
        print(f"⚠️ İsim temizleme hatası (devam ediliyor): {e}\n")
    
    try:
        conn = connect_db()
        cur = conn.cursor()
        print("✅ Veritabanına Bağlanıldı.")

        svc = get_drive_service()
        if svc:
            cur.execute("SELECT id, drive_id FROM source WHERE source_type='gdrive'")
            drive_sources = cur.fetchall()
            
            if not drive_sources:
                print("⚠️ Veritabanında kayıtlı Google Drive kaynağı yok.")
            
            for sid, did in drive_sources: 
                print(f"☁️ Drive Taranıyor: {did}")
                scan_drive(svc, did, sid, cur, conn)
        
        scan_local(cur, conn)
        conn.close()
        print("🏁 Tarama Tamamlandı (Process Bitti).")
    except Exception as e: 
        print(f"🔥 KRİTİK HATA: {e}")

# --- İŞTE BU SATIR ÇOK ÖNEMLİ ---
if __name__ == "__main__": 
    main()