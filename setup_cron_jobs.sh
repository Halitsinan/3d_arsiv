#!/bin/bash
# Indexer ve Worker Cron Job Kurulum Scripti
# - Her 6 saatte bir indexer (yeni dosyaları tara)
# - Her 1 saatte bir worker (thumbnail oluştur)

echo "=== 3D Asset Manager Cron Jobs Kurulumu ==="

# Proje yolunu belirle
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INDEXER_PATH="$SCRIPT_DIR/indexer.py"
WORKER_PATH="$SCRIPT_DIR/worker.py"
INDEXER_LOG="/var/log/3d_asset_indexer.log"
WORKER_LOG="/var/log/3d_asset_worker.log"

# Python3 yolunu bul
PYTHON_BIN=$(which python3)

# Dosya kontrolü
if [ ! -f "$INDEXER_PATH" ]; then
    echo "❌ indexer.py bulunamadı: $INDEXER_PATH"
    exit 1
fi

if [ ! -f "$WORKER_PATH" ]; then
    echo "❌ worker.py bulunamadı: $WORKER_PATH"
    exit 1
fi

echo "✅ indexer.py: $INDEXER_PATH"
echo "✅ worker.py: $WORKER_PATH"
echo "✅ Python: $PYTHON_BIN"
echo ""

# Log dosyalarını oluştur
sudo touch "$INDEXER_LOG" "$WORKER_LOG"
sudo chown $(whoami):$(whoami) "$INDEXER_LOG" "$WORKER_LOG"

# Cron job satırları
INDEXER_CRON="0 */6 * * * cd $SCRIPT_DIR && $PYTHON_BIN indexer.py >> $INDEXER_LOG 2>&1"
WORKER_CRON="0 * * * * cd $SCRIPT_DIR && $PYTHON_BIN worker.py >> $WORKER_LOG 2>&1"

# Mevcut crontab'ı yedekle
BACKUP_FILE="/tmp/crontab_backup_$(date +%Y%m%d_%H%M%S).txt"
crontab -l > "$BACKUP_FILE" 2>/dev/null
echo "💾 Mevcut crontab yedeklendi: $BACKUP_FILE"

# Eski job'ları temizle
crontab -l 2>/dev/null | grep -v "indexer.py\|worker.py" | crontab -

# Yeni job'ları ekle
(crontab -l 2>/dev/null; echo ""; echo "# 3D Asset Manager Jobs"; echo "$INDEXER_CRON"; echo "$WORKER_CRON") | crontab -

echo ""
echo "✅ Cron jobs başarıyla kuruldu!"
echo ""
echo "📋 Kurulum Özeti:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📂 Indexer (Yeni dosyaları tara)"
echo "   - Çalışma: Her 6 saatte bir (00:00, 06:00, 12:00, 18:00)"
echo "   - Log: $INDEXER_LOG"
echo ""
echo "🎨 Worker (Thumbnail oluştur)"
echo "   - Çalışma: Her saat başı"
echo "   - Log: $WORKER_LOG"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🔧 Yararlı Komutlar:"
echo "  crontab -l                           # Tüm cron jobs'ları listele"
echo "  crontab -e                           # Crontab'ı düzenle"
echo "  tail -f $INDEXER_LOG      # Indexer log'unu izle"
echo "  tail -f $WORKER_LOG        # Worker log'unu izle"
echo "  python3 $SCRIPT_DIR/indexer.py      # Manuel indexer çalıştır"
echo "  python3 $SCRIPT_DIR/worker.py       # Manuel worker çalıştır"
echo ""
echo "📊 Aktif Cron Jobs:"
crontab -l | grep -E "indexer\.py|worker\.py"
