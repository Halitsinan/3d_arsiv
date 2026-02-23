#!/bin/bash
# Orca Slicer Ubuntu Server Kurulum Scripti

echo "=== Orca Slicer Ubuntu Kurulumu ==="

# 1. Gerekli kütüphaneleri kur
echo "📦 Gerekli paketler kuruluyor..."
sudo apt update
sudo apt install -y \
    libwebkit2gtk-4.1-0 \
    libgtk-3-0t64 \
    libgl1 \
    libglib2.0-0 \
    libcairo2 \
    libpango-1.0-0 \
    xvfb \
    wget \
    fuse \
    libfuse2

# 2. Orca Slicer AppImage indir (en son versiyon)
ORCA_VERSION="2.1.1"
ORCA_URL="https://github.com/SoftFever/OrcaSlicer/releases/download/v${ORCA_VERSION}/OrcaSlicer_Linux_V${ORCA_VERSION}.AppImage"

echo "⬇️  Orca Slicer indiriliyor..."
cd /tmp
wget -O OrcaSlicer.AppImage "$ORCA_URL"

# 3. Çalıştırılabilir yap ve /opt'a taşı
sudo mkdir -p /opt/orcaslicer
sudo mv OrcaSlicer.AppImage /opt/orcaslicer/
sudo chmod +x /opt/orcaslicer/OrcaSlicer.AppImage

# 4. CLI wrapper oluştur (headless mod için)
echo "🔧 CLI wrapper oluşturuluyor..."
sudo tee /usr/local/bin/orcaslicer > /dev/null << 'EOF'
#!/bin/bash
# Orca Slicer CLI Wrapper - Headless mod için Xvfb kullanır

# Eğer DISPLAY yoksa (headless server), Xvfb ile sanal X server başlat
if [ -z "$DISPLAY" ]; then
    echo "🖥️  Headless mod tespit edildi, Xvfb başlatılıyor..."
    xvfb-run -a /opt/orcaslicer/OrcaSlicer.AppImage "$@"
else
    # GUI varsa direkt çalıştır
    /opt/orcaslicer/OrcaSlicer.AppImage "$@"
fi
EOF

sudo chmod +x /usr/local/bin/orcaslicer

# 5. Test et
echo ""
echo "✅ Kurulum tamamlandı!"
echo ""
echo "Test için:"
echo "  orcaslicer --help"
echo ""
echo "Slice örneği:"
echo "  orcaslicer --export-gcode --load model.stl --output output.gcode"
