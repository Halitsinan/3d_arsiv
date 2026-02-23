#!/bin/bash
# Worker Cron Job Kurulum Scripti
# Bu script worker.py'yi her saat başı otomatik çalıştırmak için crontab'a ekler

echo "=== Worker Cron Job Kurulumu ==="

# Proje yolunu belirle
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKER_PATH="$SCRIPT_DIR/worker.py"
LOG_PATH="/var/log/3d_asset_worker.log"

# Python3 yolunu bul
PYTHON_BIN=$(which python3)

if [ ! -f "$WORKER_PATH" ]; then
    echo "❌ worker.py bulunamadı: $WORKER_PATH"
    exit 1
fi

echo "✅ Worker bulundu: $WORKER_PATH"
echo "✅ Python: $PYTHON_BIN"

# Log dosyası için izin ver
sudo touch "$LOG_PATH"
sudo chown $(whoami):$(whoami) "$LOG_PATH"

# Cron job satırını oluştur
CRON_JOB="0 * * * * cd $SCRIPT_DIR && $PYTHON_BIN worker.py >> $LOG_PATH 2>&1"

# Mevcut crontab'ı kontrol et
crontab -l 2>/dev/null | grep -q "worker.py"

if [ $? -eq 0 ]; then
    echo "⚠️ worker.py için cron job zaten mevcut."
    echo ""
    echo "Mevcut crontab:"
    crontab -l | grep "worker.py"
    echo ""
    read -p "Güncellemek ister misiniz? (y/n): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "İşlem iptal edildi."
        exit 0
    fi
    
    # Eski job'u sil
    crontab -l | grep -v "worker.py" | crontab -
fi

# Yeni job'u ekle
(crontab -l 2>/dev/null; echo "$CRON_JOB") | crontab -

echo ""
echo "✅ Cron job başarıyla eklendi!"
echo ""
echo "📋 Kurulum Özeti:"
echo "  - Worker: $WORKER_PATH"
echo "  - Çalışma: Her saat başı (00:00)"
echo "  - Log: $LOG_PATH"
echo ""
echo "🔧 Yararlı Komutlar:"
echo "  - Crontab'ı görüntüle:     crontab -l"
echo "  - Crontab'ı düzenle:       crontab -e"
echo "  - Log'u görüntüle:         tail -f $LOG_PATH"
echo "  - Log'u temizle:           > $LOG_PATH"
echo "  - Manuel çalıştır:         python3 $WORKER_PATH"
echo ""
echo "📊 Şu andan itibaren her saat başı worker otomatik çalışacak."
echo "   İlk çalışma: Bir sonraki saat başı (örn: 15:00, 16:00...)"
