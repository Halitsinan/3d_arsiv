# 3D Asset Manager PRO — Kurulum Kılavuzu

## Gereksinimler

- Ubuntu 22.04+ (sunucu)
- Python 3.10+
- Docker
- PostgreSQL 14+
- Samba (ağ paylaşımı için isteğe bağlı)
- Google Drive API service account (gdrive kaynakları için)

---

## 1. Sistem Paketleri

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y \
    python3 python3-pip python3-venv \
    git curl wget unzip \
    unrar p7zip-full \
    postgresql postgresql-contrib \
    docker.io docker-compose \
    samba samba-common-bin \
    libpq-dev build-essential
```

Docker servisini başlat:
```bash
sudo systemctl enable docker
sudo systemctl start docker
sudo usermod -aG docker $USER
newgrp docker
```

---

## 2. Proje Dosyaları

```bash
# Proje dizinini oluştur
sudo mkdir -p /home/hsa/3d_asset_manager
sudo chown $USER:$USER /home/hsa/3d_asset_manager

# Uygulama dosyalarını kopyala
cp -r /path/to/app /home/hsa/3d_asset_manager/app

# Gerekli klasörleri oluştur
mkdir -p /home/hsa/3d_asset_manager/temp_work
mkdir -p /home/hsa/3d_asset_manager/logs
```

---

## 3. Python Sanal Ortamı

```bash
cd /home/hsa/3d_asset_manager
python3 -m venv venv
source venv/bin/activate

pip install --upgrade pip
pip install -r app/requirements.txt
```

---

## 4. PostgreSQL Kurulumu

PostgreSQL'i **5435** portunda çalıştır (varsayılan 5432 yerine):

```bash
# PostgreSQL konfigürasyonunu düzenle
sudo nano /etc/postgresql/*/main/postgresql.conf
# port = 5435  satırını bul ve değiştir

# Servis yeniden başlat
sudo systemctl restart postgresql

# Veritabanı ve kullanıcı oluştur
sudo -u postgres psql
```

```sql
CREATE USER postgres WITH PASSWORD 'postgres';
CREATE DATABASE asset_db OWNER postgres;
GRANT ALL PRIVILEGES ON DATABASE asset_db TO postgres;
\q
```

### Veritabanı Tablolarını Oluştur

```bash
cd /home/hsa/3d_asset_manager/app

# Ana assets tablosu
psql -h localhost -p 5435 -U postgres -d asset_db << 'EOF'
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
EOF

# Slicer tabloları
psql -h localhost -p 5435 -U postgres -d asset_db -f app/setup_slicer_tables.sql
```

---

## 5. OrcaSlicer Docker Kurulumu

### 5.1 Config Dizinlerini Oluştur

```bash
sudo mkdir -p /srv/orcaslicer/config/Downloads
sudo chown -R $USER:$USER /srv/orcaslicer
```

### 5.2 Container'ı Başlat

```bash
docker run -d \
  --name=orcaslicer \
  --security-opt seccomp=unconfined \
  -e PUID=1000 \
  -e PGID=1000 \
  -e TZ=Europe/Istanbul \
  -e SUBFOLDER=/ \
  -p 3000:3000 \
  -p 3001:3001 \
  -v /srv/orcaslicer/config:/config \
  --restart unless-stopped \
  lscr.io/linuxserver/orcaslicer:latest
```

### 5.3 Docker Compose (Alternatif)

```yaml
# /srv/orcaslicer/docker-compose.yml
version: "3.8"
services:
  orcaslicer:
    image: lscr.io/linuxserver/orcaslicer:latest
    container_name: orcaslicer
    security_opt:
      - seccomp:unconfined
    environment:
      - PUID=1000
      - PGID=1000
      - TZ=Europe/Istanbul
      - SUBFOLDER=/
    ports:
      - "3000:3000"
      - "3001:3001"
    volumes:
      - /srv/orcaslicer/config:/config
    restart: unless-stopped
```

```bash
cd /srv/orcaslicer
docker compose up -d
```

### 5.4 Binary Yolunu Doğrula

```bash
# Container içinde binary'yi bul
docker exec orcaslicer find /opt -name "orca-slicer" 2>/dev/null
# Beklenen: /opt/orcaslicer/bin/orca-slicer
```

---

## 6. config.json Güncelle

```bash
nano /home/hsa/3d_asset_manager/app/config.json
```

```json
{
  "database": {
    "host": "localhost",
    "port": 5435,
    "dbname": "asset_db",
    "user": "postgres",
    "password": "postgres"
  },
  "orca_slicer": {
    "docker_config_path": "/srv/orcaslicer/config/.config/OrcaSlicer/user/default",
    "docker_container": "orcaslicer",
    "docker_image": "lscr.io/linuxserver/orcaslicer:latest",
    "web_url": "https://SUNUCU_IP:3001",
    "downloads_dir": "/srv/orcaslicer/config/Downloads"
  },
  "thumbnails": {
    "size": 400,
    "quality": 70,
    "google_drive_size": "s250"
  },
  "temp_dir": "/home/hsa/3d_asset_manager/temp_work"
}
```

> ⚠️ `SUNUCU_IP` kısmını gerçek sunucu IP adresiyle değiştir.

---

## 7. Google Drive API Kimlik Bilgileri

1. [Google Cloud Console](https://console.cloud.google.com)'a git
2. Yeni proje oluştur veya mevcut seç
3. **Google Drive API**'yi etkinleştir
4. **IAM & Admin → Service Accounts** altında yeni service account oluştur
5. JSON key indir → `app/service_account.json` olarak kaydet
6. Google Drive klasörlerini bu service account e-postasıyla paylaş

---

## 8. Systemd Servis Kurulumu

```bash
sudo nano /etc/systemd/system/asset-admin.service
```

```ini
[Unit]
Description=3D Asset Manager PRO - Streamlit Web UI
After=network.target postgresql.service

[Service]
Type=simple
User=hsa
WorkingDirectory=/home/hsa/3d_asset_manager
ExecStart=/home/hsa/3d_asset_manager/venv/bin/streamlit run app/admin.py \
    --server.port 8501 \
    --server.address 0.0.0.0 \
    --server.headless true \
    --browser.gatherUsageStats false
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable asset-admin.service
sudo systemctl start asset-admin.service

# Durumu kontrol et
sudo systemctl status asset-admin.service
```

---

## 9. Cron Job Kurulumu

```bash
cd /home/hsa/3d_asset_manager/app
chmod +x setup_cron_jobs.sh
./setup_cron_jobs.sh
```

Manuel çalıştırma:
```bash
source /home/hsa/3d_asset_manager/venv/bin/activate
python /home/hsa/3d_asset_manager/app/indexer.py   # Dosyaları tara
python /home/hsa/3d_asset_manager/app/worker.py    # Thumbnail üret
```

---

## 10. Samba Ağ Paylaşımı (Opsiyonel)

VS Code ile uzaktan dosya düzenlemek için:

```bash
sudo nano /etc/samba/smb.conf
```

Aşağıdakileri ekle:
```ini
[share]
   path = /home/hsa/3d_asset_manager
   writable = yes
   browseable = yes
   guest ok = no
   valid users = hsa
   create mask = 0644
   directory mask = 0755
```

```bash
sudo smbpasswd -a hsa
sudo systemctl restart smbd
```

Windows'tan erişim: `\\SUNUCU_IP\share`

---

## 11. Güvenlik Duvarı

```bash
sudo ufw allow 8501/tcp   # Streamlit web UI
sudo ufw allow 3000/tcp   # OrcaSlicer HTTP
sudo ufw allow 3001/tcp   # OrcaSlicer HTTPS
sudo ufw allow 445/tcp    # Samba
sudo ufw allow 139/tcp    # Samba (legacy)
sudo ufw enable
```

---

## 12. Kurulum Doğrulama

```bash
# Tüm servisleri kontrol et
sudo systemctl status asset-admin.service
sudo systemctl status postgresql
docker ps | grep orcaslicer

# Uygulama logları
sudo journalctl -u asset-admin.service -f

# Test scripti
source /home/hsa/3d_asset_manager/venv/bin/activate
python /home/hsa/3d_asset_manager/app/test_system.py
```

---

## Sunucu Adresleri

| Servis | URL |
|--------|-----|
| Web UI | `http://SUNUCU_IP:8501` |
| OrcaSlicer (HTTP) | `http://SUNUCU_IP:3000` |
| OrcaSlicer (HTTPS) | `https://SUNUCU_IP:3001` |

---

## Sorun Giderme

### Servis başlamıyor
```bash
sudo journalctl -u asset-admin.service -n 50 --no-pager
```

### Veritabanına bağlanılamıyor
```bash
psql -h localhost -p 5435 -U postgres -d asset_db -c "SELECT 1"
```

### OrcaSlicer container çalışmıyor
```bash
docker logs orcaslicer --tail 50
docker restart orcaslicer
```

### Google Drive erişim hatası
```bash
# service_account.json dosyasının varlığını kontrol et
ls -la /home/hsa/3d_asset_manager/app/service_account.json

# Drive API etkinleştirildi mi?
# → Google Cloud Console → APIs & Services → Enabled APIs
```
