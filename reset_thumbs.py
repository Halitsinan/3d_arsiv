#!/usr/bin/env python3
"""GDrive thumbnail_attempts'i sıfırlar — uzantısız ve thumbnaili boş olan assetler için."""
import sys
sys.path.append('/home/hsa/3d_asset_manager')
import psycopg2

DB_CONFIG = {
    "dbname": "asset_db", "user": "postgres", "password": "gizli_sifre",
    "host": "localhost", "port": "5435"
}

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()

cur.execute("""
    UPDATE assets SET thumbnail_attempts = 0
    WHERE thumbnail_blob IS NULL 
      AND (filepath LIKE '%drive.google.com%' OR filepath LIKE '%/d/%')
""")
updated = cur.rowcount
conn.commit()

cur.execute("SELECT COUNT(*) FROM assets WHERE thumbnail_blob IS NULL AND thumbnail_attempts = 0")
waiting = cur.fetchone()[0]
conn.close()

print(f"✅ {updated} GDrive asset sıfırlandı. Şu an {waiting} asset thumbnail bekliyor.")
