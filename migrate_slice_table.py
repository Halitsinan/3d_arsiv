#!/usr/bin/env python3
"""
Slice Jobs tablosunu güncelle
"""

import psycopg2

DB_CONFIG = {
    "dbname": "asset_db",
    "user": "postgres",
    "password": "gizli_sifre",
    "host": "localhost",
    "port": "5435"
}

def migrate():
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    
    try:
        # Eski tabloyu sil
        print("Eski slice_jobs tablosu siliniyor...")
        cur.execute("DROP TABLE IF EXISTS slice_jobs CASCADE")
        
        # Yeni tabloyu oluştur
        print("Yeni slice_jobs tablosu oluşturuluyor...")
        cur.execute("""
            CREATE TABLE slice_jobs (
                id SERIAL PRIMARY KEY,
                asset_id INTEGER REFERENCES assets(id) ON DELETE CASCADE,
                printer VARCHAR(200),
                filament VARCHAR(200),
                process VARCHAR(200),
                output_file TEXT,
                status VARCHAR(20) DEFAULT 'pending',
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            )
        """)
        
        # İndeks ekle
        print("İndeksler oluşturuluyor...")
        cur.execute("CREATE INDEX idx_slice_jobs_asset ON slice_jobs(asset_id)")
        cur.execute("CREATE INDEX idx_slice_jobs_status ON slice_jobs(status)")
        
        conn.commit()
        print("✅ Migrasyon başarılı!")
        
    except Exception as e:
        conn.rollback()
        print(f"❌ Hata: {e}")
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    migrate()
