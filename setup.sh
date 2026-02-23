#!/bin/bash
# =============================================================
# 3D Asset Manager PRO — Otomatik Kurulum Scripti
# Kullanım: sudo bash setup.sh
# =============================================================
set -e

# --- Renkli çıktı ---
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[OK]${NC} $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $1"; }
error()   { echo -e "${RED}[ERROR]${NC} $1"; exit 1; }

# --- Ayarlar (değiştirilebilir) ---
APP_USER="${SUDO_USER:-hsa}"
APP_HOME="/home/$APP_USER/3d_asset_manager"
APP_DIR="$APP_HOME/app"
VENV_DIR="$APP_HOME/venv"
TEMP_DIR="$APP_HOME/temp_work"
LOG_DIR="$APP_HOME/logs"
ORCA_DATA="/srv/orcaslicer"
DB_PORT=5435
DB_NAME="asset_db"
DB_USER="postgres"
DB_PASS="postgres"
STREAMLIT_PORT=8501

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║    3D Asset Manager PRO — Kurulum Scripti   ║"
echo "╚══════════════════════════════════════════════╝"
echo ""
warn "Bu script şunları yapacak:"
echo "  • Sistem paketlerini kuracak"
echo "  • PostgreSQL'i $DB_PORT portunda yapılandıracak"
echo "  • Python venv ve bağımlılıkları kuracak"
echo "  • OrcaSlicer Docker container'ını başlatacak"
echo "  • Systemd servisini oluşturacak"
echo "  • Cron job'larını kuracak"
echo ""
read -p "Devam etmek istiyor musunuz? (e/H): " CONFIRM
[[ "$CONFIRM" =~ ^[Ee]$ ]] || { info "İptal edildi."; exit 0; }

# =============================================================
# ADIM 1 — Sistem Paketleri
# =============================================================
info "Adım 1/8: Sistem paketleri kuruluyor..."
apt update -qq
apt install -y \
    python3 python3-pip python3-venv \
    curl wget git unzip \
    unrar p7zip-full \
    postgresql postgresql-contrib \
    libpq-dev build-essential \
    docker.io \
    samba samba-common-bin \
    2>/dev/null
success "Sistem paketleri kuruldu."

# Docker
systemctl enable docker --quiet
systemctl start docker
usermod -aG docker "$APP_USER" 2>/dev/null || true
success "Docker hazır."

# =============================================================
# ADIM 2 — Dizinler
# =============================================================
info "Adım 2/8: Dizinler oluşturuluyor..."
mkdir -p "$APP_DIR" "$TEMP_DIR" "$LOG_DIR"
mkdir -p "$ORCA_DATA/config/Downloads"
chown -R "$APP_USER":"$APP_USER" "$APP_HOME"
chown -R "$APP_USER":"$APP_USER" "$ORCA_DATA"

# Uygulama dosyalarını kopyala (script app/ altındaysa)
if [ "$SCRIPT_DIR" != "$APP_DIR" ] && [ -f "$SCRIPT_DIR/admin.py" ]; then
    info "Uygulama dosyaları $APP_DIR dizinine kopyalanıyor..."
    cp -r "$SCRIPT_DIR"/. "$APP_DIR/"
    chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
fi
success "Dizinler hazır."

# =============================================================
# ADIM 3 — Python Venv
# =============================================================
info "Adım 3/8: Python sanal ortamı kuruluyor..."
if [ ! -f "$APP_DIR/requirements.txt" ]; then
    error "requirements.txt bulunamadı: $APP_DIR/requirements.txt"
fi
sudo -u "$APP_USER" python3 -m venv "$VENV_DIR"
sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install --upgrade pip -q
sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt" -q
success "Python sanal ortamı hazır."

# =============================================================
# ADIM 4 — PostgreSQL
# =============================================================
info "Adım 4/8: PostgreSQL yapılandırılıyor (port $DB_PORT)..."
PG_CONF=$(find /etc/postgresql -name "postgresql.conf" 2>/dev/null | head -1)
if [ -z "$PG_CONF" ]; then error "postgresql.conf bulunamadı!"; fi

# Portu değiştir
sed -i "s/^#*port = .*/port = $DB_PORT/" "$PG_CONF"
systemctl restart postgresql
sleep 3

# Veritabanı ve kullanıcı oluştur
sudo -u postgres psql -p "$DB_PORT" -c "
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$DB_USER') THEN
    CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';
  END IF;
END
\$\$;
" 2>/dev/null || true

sudo -u postgres psql -p "$DB_PORT" -c "
SELECT 'already exists' FROM pg_database WHERE datname='$DB_NAME'
" | grep -q "already exists" || sudo -u postgres createdb -p "$DB_PORT" -O "$DB_USER" "$DB_NAME"

# Ana tabloyu oluştur
sudo -u postgres psql -p "$DB_PORT" -d "$DB_NAME" << 'EOSQL'
CREATE TABLE IF NOT EXISTS sources (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    type VARCHAR(20) NOT NULL CHECK (type IN ('local', 'gdrive')),
    path TEXT NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    last_indexed TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS assets (
    id SERIAL PRIMARY KEY,
    filename VARCHAR(500) NOT NULL,
    filepath TEXT UNIQUE NOT NULL,
    source_id INTEGER REFERENCES sources(id) ON DELETE CASCADE,
    file_size BIGINT,
    thumbnail_blob BYTEA,
    folder_path TEXT,
    tags TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_assets_source ON assets(source_id);
CREATE INDEX IF NOT EXISTS idx_assets_filename ON assets(filename);
CREATE INDEX IF NOT EXISTS idx_assets_filepath ON assets(filepath);
EOSQL

# Slicer tablolarını oluştur
if [ -f "$APP_DIR/setup_slicer_tables.sql" ]; then
    sudo -u postgres psql -p "$DB_PORT" -d "$DB_NAME" -f "$APP_DIR/setup_slicer_tables.sql" 2>/dev/null || true
fi
success "PostgreSQL hazır (port $DB_PORT, veritabanı: $DB_NAME)."

# =============================================================
# ADIM 5 — config.json güncelle
# =============================================================
info "Adım 5/8: config.json yapılandırılıyor..."
SERVER_IP=$(hostname -I | awk '{print $1}')
cat > "$APP_DIR/config.json" << EOF
{
  "database": {
    "host": "localhost",
    "port": $DB_PORT,
    "dbname": "$DB_NAME",
    "user": "$DB_USER",
    "password": "$DB_PASS"
  },
  "orca_slicer": {
    "docker_config_path": "$ORCA_DATA/config/.config/OrcaSlicer/user/default",
    "docker_container": "orcaslicer",
    "docker_image": "lscr.io/linuxserver/orcaslicer:latest",
    "web_url": "https://$SERVER_IP:3001",
    "downloads_dir": "$ORCA_DATA/config/Downloads"
  },
  "thumbnails": {
    "size": 400,
    "quality": 70,
    "google_drive_size": "s250"
  },
  "temp_dir": "$TEMP_DIR"
}
EOF
chown "$APP_USER":"$APP_USER" "$APP_DIR/config.json"
success "config.json oluşturuldu (Sunucu IP: $SERVER_IP)."

# =============================================================
# ADIM 6 — OrcaSlicer Docker
# =============================================================
info "Adım 6/8: OrcaSlicer Docker container başlatılıyor..."
PUID=$(id -u "$APP_USER")
PGID=$(id -g "$APP_USER")

if docker ps -a --format "{{.Names}}" | grep -q "^orcaslicer$"; then
    warn "Mevcut 'orcaslicer' container'ı durduruluyor..."
    docker stop orcaslicer 2>/dev/null || true
    docker rm orcaslicer 2>/dev/null || true
fi

docker run -d \
    --name=orcaslicer \
    --security-opt seccomp=unconfined \
    -e PUID=$PUID \
    -e PGID=$PGID \
    -e TZ=Europe/Istanbul \
    -e SUBFOLDER=/ \
    -p 3000:3000 \
    -p 3001:3001 \
    -v "$ORCA_DATA/config:/config" \
    --restart unless-stopped \
    lscr.io/linuxserver/orcaslicer:latest

success "OrcaSlicer container başlatıldı."
info "Web UI: https://$SERVER_IP:3001 (HTTP: http://$SERVER_IP:3000)"

# =============================================================
# ADIM 7 — Systemd Servis
# =============================================================
info "Adım 7/8: Systemd servisi oluşturuluyor..."
cat > /etc/systemd/system/asset-admin.service << EOF
[Unit]
Description=3D Asset Manager PRO - Streamlit Web UI
After=network.target postgresql.service

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_HOME
ExecStart=$VENV_DIR/bin/streamlit run $APP_DIR/admin.py \\
    --server.port $STREAMLIT_PORT \\
    --server.address 0.0.0.0 \\
    --server.headless true \\
    --browser.gatherUsageStats false
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable asset-admin.service
systemctl start asset-admin.service
sleep 3

if systemctl is-active --quiet asset-admin.service; then
    success "asset-admin.service çalışıyor."
else
    warn "Servis başlatılamadı. Log: sudo journalctl -u asset-admin.service -n 30"
fi

# =============================================================
# ADIM 8 — Cron Jobs
# =============================================================
info "Adım 8/8: Cron job'lar kuruluyor..."
PYTHON_BIN="$VENV_DIR/bin/python"
INDEXER_LOG="/var/log/3d_asset_indexer.log"
WORKER_LOG="/var/log/3d_asset_worker.log"

touch "$INDEXER_LOG" "$WORKER_LOG"
chown "$APP_USER":"$APP_USER" "$INDEXER_LOG" "$WORKER_LOG"

INDEXER_CRON="0 */6 * * * cd $APP_DIR && $PYTHON_BIN indexer.py >> $INDEXER_LOG 2>&1"
WORKER_CRON="0 * * * * cd $APP_DIR && $PYTHON_BIN worker.py >> $WORKER_LOG 2>&1"

(crontab -u "$APP_USER" -l 2>/dev/null | grep -v "indexer.py\|worker.py"; \
 echo ""; echo "# 3D Asset Manager Jobs"; \
 echo "$INDEXER_CRON"; echo "$WORKER_CRON") | crontab -u "$APP_USER" -

success "Cron job'lar kuruldu (indexer: her 6 saatte, worker: her saat)."

# =============================================================
# Güvenlik Duvarı (isteğe bağlı)
# =============================================================
if command -v ufw &>/dev/null; then
    ufw allow "$STREAMLIT_PORT/tcp" comment "Asset Manager UI" 2>/dev/null || true
    ufw allow "3000/tcp"  comment "OrcaSlicer HTTP"  2>/dev/null || true
    ufw allow "3001/tcp"  comment "OrcaSlicer HTTPS" 2>/dev/null || true
    ufw allow "445/tcp"   comment "Samba" 2>/dev/null || true
fi

# =============================================================
# Özet
# =============================================================
echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║              KURULUM TAMAMLANDI ✅                     ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "  📺 Web UI          : http://$SERVER_IP:$STREAMLIT_PORT"
echo "  🖨️  OrcaSlicer      : https://$SERVER_IP:3001"
echo "  🗄️  Veritabanı      : localhost:$DB_PORT / $DB_NAME"
echo "  📂 Uygulama        : $APP_DIR"
echo ""
echo "  ⚠️  YAPILMASI GEREKENLER:"
echo "  1. Google Drive service account JSON dosyasını kopyala:"
echo "     cp service_account.json $APP_DIR/service_account.json"
echo ""
echo "  2. İlk indexlemeyi çalıştır:"
echo "     sudo -u $APP_USER $PYTHON_BIN $APP_DIR/indexer.py"
echo ""
echo "  Yardımcı komutlar:"
echo "  sudo systemctl status asset-admin.service"
echo "  sudo systemctl restart asset-admin.service"
echo "  sudo journalctl -u asset-admin.service -f"
echo ""
