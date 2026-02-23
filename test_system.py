#!/usr/bin/env python3
"""
3D Asset Manager - Hızlı Test Scripti
Tüm modülleri import edip temel kontrolleri yapar
"""

import sys
import os

print("=" * 60)
print("3D Asset Manager - Sistem Kontrolü")
print("=" * 60)

# Test 1: Import Kontrolleri
print("\n[1/6] Python modülleri kontrol ediliyor...")
try:
    import psycopg2
    print("  ✅ psycopg2")
except ImportError as e:
    print(f"  ❌ psycopg2: {e}")

try:
    import streamlit
    print("  ✅ streamlit")
except ImportError as e:
    print(f"  ❌ streamlit: {e}")

try:
    import pandas
    print("  ✅ pandas")
except ImportError as e:
    print(f"  ❌ pandas: {e}")

try:
    import trimesh
    print("  ✅ trimesh")
except ImportError as e:
    print(f"  ❌ trimesh: {e}")

try:
    import pyrender
    print("  ✅ pyrender")
except ImportError as e:
    print(f"  ❌ pyrender: {e}")

try:
    from google.oauth2 import service_account
    print("  ✅ google-api-python-client")
except ImportError as e:
    print(f"  ❌ google-api-python-client: {e}")

# Test 2: Lokal Modüller
print("\n[2/6] Lokal modüller kontrol ediliyor...")
try:
    import config
    print("  ✅ config")
except Exception as e:
    print(f"  ❌ config: {e}")

try:
    import slicer
    print("  ✅ slicer")
except Exception as e:
    print(f"  ❌ slicer: {e}")

try:
    import renderer
    print("  ✅ renderer")
except Exception as e:
    print(f"  ❌ renderer: {e}")

# Test 3: Config Dosyası
print("\n[3/6] Config dosyası kontrol ediliyor...")
try:
    import config
    cfg = config.load_config()
    print(f"  ✅ config.json yüklendi")
    print(f"     - Database: {cfg['database']['host']}:{cfg['database']['port']}")
    print(f"     - Docker Container: {cfg['orca_slicer']['docker_container']}")
    print(f"     - Temp Dir: {cfg['temp_dir']}")
except Exception as e:
    print(f"  ❌ Config yükleme hatası: {e}")

# Test 4: Database Bağlantısı
print("\n[4/6] Database bağlantısı kontrol ediliyor...")
try:
    import psycopg2
    import config
    db = config.get_db_config()
    conn = psycopg2.connect(
        host=db['host'],
        port=db['port'],
        dbname=db['dbname'],
        user=db['user'],
        password=db['password']
    )
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM assets")
    count = cur.fetchone()[0]
    print(f"  ✅ Database bağlantısı başarılı")
    print(f"     - Toplam asset: {count}")
    
    # Slice_jobs tablosu var mı?
    cur.execute("""
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = 'slice_jobs'
        )
    """)
    exists = cur.fetchone()[0]
    if exists:
        print(f"  ✅ slice_jobs tablosu mevcut")
    else:
        print(f"  ⚠️  slice_jobs tablosu yok - migration gerekli!")
    
    cur.close()
    conn.close()
except Exception as e:
    print(f"  ❌ Database hatası: {e}")

# Test 5: Docker & Orca Slicer
print("\n[5/6] Docker ve Orca Slicer kontrol ediliyor...")
try:
    import subprocess
    import config
    
    container = config.get_docker_container()
    
    # Docker container çalışıyor mu?
    result = subprocess.run(
        ["docker", "ps", "--filter", f"name={container}", "--format", "{{.Names}}"],
        capture_output=True,
        text=True,
        timeout=5
    )
    
    if container in result.stdout:
        print(f"  ✅ Docker container '{container}' çalışıyor")
    else:
        print(f"  ⚠️  Docker container '{container}' bulunamadı")
    
    # Config dizini var mı?
    config_path = config.get_orca_profile_path()
    if os.path.exists(config_path):
        print(f"  ✅ Orca config dizini mevcut: {config_path}")
        
        # Printer/Filament sayıları
        printers_dir = config.get_printers_dir()
        filaments_dir = config.get_filaments_dir()
        
        if os.path.exists(printers_dir):
            printer_count = len([f for f in os.listdir(printers_dir) if f.endswith('.json')])
            print(f"     - Printers: {printer_count} adet")
        
        if os.path.exists(filaments_dir):
            filament_count = len([f for f in os.listdir(filaments_dir) if f.endswith('.json')])
            print(f"     - Filaments: {filament_count} adet")
    else:
        print(f"  ⚠️  Orca config dizini yok: {config_path}")
    
except Exception as e:
    print(f"  ❌ Docker kontrol hatası: {e}")

# Test 6: Slicer Modülü
print("\n[6/6] Slicer modülü fonksiyonları kontrol ediliyor...")
try:
    import slicer
    
    printers = slicer.get_available_printers()
    filaments = slicer.get_available_filaments()
    processes = slicer.get_available_processes()
    
    print(f"  ✅ get_available_printers(): {len(printers)} adet")
    print(f"  ✅ get_available_filaments(): {len(filaments)} adet")
    print(f"  ✅ get_available_processes(): {len(processes)} adet")
    
    if printers:
        print(f"     - Örnek printer: {os.path.basename(printers[0])}")
    if filaments:
        print(f"     - Örnek filament: {os.path.basename(filaments[0])}")
    
except Exception as e:
    print(f"  ❌ Slicer modülü hatası: {e}")

# Özet
print("\n" + "=" * 60)
print("SONUÇ:")
print("=" * 60)
print("✅ Sistem kontrolleri tamamlandı!")
print("\nYapılması gerekenler:")
print("  1. Eğer 'slice_jobs tablosu yok' uyarısı varsa:")
print("     ~/3d_asset_venv/bin/python migrate_slice_table.py")
print("\n  2. Streamlit başlatmak için:")
print("     ~/3d_asset_venv/bin/streamlit run admin.py")
print("\n  3. Docker container yoksa:")
print("     docker start orcaslicer")
print("=" * 60)
