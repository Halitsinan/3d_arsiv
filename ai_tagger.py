import psycopg2
import io
import torch
from PIL import Image
from transformers import CLIPProcessor, CLIPModel
import time

# --- AYARLAR ---
DB_CONFIG = {
    "dbname": "asset_db",
    "user": "postgres",
    "password": "gizli_sifre", # Kendi şifrenle değiştir
    "host": "localhost",
    "port": "5435"
}
MODEL_NAME = "openai/clip-vit-base-patch32"

# Etiket Listesi (Daha spesifik hale getirildi)
CANDIDATE_LABELS = [
    "3d character", "architectural building", "car", "weapon", "scifi", 
    "furniture", "nature tree plant", "miniature figure", "jewelry", 
    "animal", "human anatomy", "mechanical part", "robot", "tools",
    "monster", "vehicle", "terrain", "low poly", "sculpture"
]

def tag_assets():
    # GPU kontrolü (Varsa GPU kullanmak işlemi 10x hızlandırır)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"🧠 AI Modeli yükleniyor ({device})...")
    
    model = CLIPModel.from_pretrained(MODEL_NAME).to(device)
    processor = CLIPProcessor.from_pretrained(MODEL_NAME)

    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()

        # DÜZELTME: thumbnail_blob'u OLAN ama henüz etiketi OLMAYANLARI getir
        cur.execute("""
            SELECT id, thumbnail_blob 
            FROM assets 
            WHERE thumbnail_blob IS NOT NULL 
            AND (tags IS NULL OR tags = '')
            LIMIT 50
        """)
        rows = cur.fetchall()

        if not rows:
            print("✅ Etiketlenecek yeni dosya bulunamadı.")
            return

        print(f"🏷️ {len(rows)} dosya işleniyor...")

        for asset_id, blob in rows:
            try:
                # Resmi hazırla
                image = Image.open(io.BytesIO(blob)).convert("RGB")
                
                # AI İşleme
                inputs = processor(text=CANDIDATE_LABELS, images=image, return_tensors="pt", padding=True).to(device)
                
                with torch.no_grad(): # Bellek tasarrufu için gradient hesaplama yok
                    outputs = model(**inputs)
                
                # Olasılıkları hesapla
                probs = outputs.logits_per_image.softmax(dim=1)
                
                # %15 üzerindeki etiketleri al (Eşik değeri biraz düşürüldü)
                detected_tags = []
                for i, prob in enumerate(probs[0]):
                    if prob > 0.15:
                        detected_tags.append(CANDIDATE_LABELS[i])
                
                tag_str = ", ".join(detected_tags)
                
                # Veritabanına Yaz
                cur.execute("UPDATE assets SET tags = %s WHERE id = %s", (tag_str, asset_id))
                conn.commit()
                print(f"✅ ID {asset_id} -> {tag_str}")

            except Exception as e:
                print(f"⚠️ Hata (ID {asset_id}): {e}")
                conn.rollback()

        cur.close()
        conn.close()
        print("🏁 İşlem tamamlandı.")

    except Exception as e:
        print(f"❌ Bağlantı Hatası: {e}")

if __name__ == "__main__":
    tag_assets()