"""
Uygulama yapılandırma ayarları.
Config.json dosyasından ayarları yükler.
Docker Orca Slicer entegrasyonu.
"""

import json
import os
from pathlib import Path

# Config dosyasının yolu
CONFIG_FILE = Path(__file__).parent / "config.json"

def load_config():
    """Config.json dosyasını yükler."""
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"UYARI: {CONFIG_FILE} bulunamadı. Varsayılan ayarlar kullanılacak.")
        return get_default_config()
    except json.JSONDecodeError as e:
        print(f"HATA: Config.json okunamadı: {e}")
        return get_default_config()

def get_default_config():
    """Varsayılan yapılandırma ayarları."""
    return {
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
            "web_url": "https://localhost:3001"
        },
        "thumbnails": {
            "size": 400,
            "quality": 70,
            "google_drive_size": "s250"
        },
        "temp_dir": "/home/hsa/3d_asset_manager/temp_work"
    }

def get_orca_profile_path():
    """
    Orca Slicer Docker config dizinini döndürür.
    """
    config = load_config()
    return config.get("orca_slicer", {}).get("docker_config_path", "/srv/orcaslicer/config/.config/OrcaSlicer/user/default")

def get_printers_dir():
    """Orca Slicer printer (machine) json dosyalarının olduğu klasörü döndürür."""
    profile = get_orca_profile_path()
    if profile:
        return os.path.join(profile, "machine")
    return None

def get_filaments_dir():
    """Orca Slicer filament json dosyalarının olduğu klasörü döndürür."""
    profile = get_orca_profile_path()
    if profile:
        return os.path.join(profile, "filament")
    return None

def get_process_dir():
    """Orca Slicer process json dosyalarının olduğu klasörü döndürür."""
    profile = get_orca_profile_path()
    if profile:
        return os.path.join(profile, "process")
    return None

def get_docker_container():
    """Orca Slicer Docker container adını döndürür."""
    config = load_config()
    return config.get("orca_slicer", {}).get("docker_container", "orcaslicer")

def get_docker_image():
    """Orca Slicer Docker image adını döndürür."""
    config = load_config()
    return config.get("orca_slicer", {}).get("docker_image", "orcaslicer")

def get_orca_web_url():
    """Orca Slicer web arayüzü URL'ini döndürür."""
    config = load_config()
    return config.get("orca_slicer", {}).get("web_url", "https://localhost:3001")

def get_orca_downloads_dir():
    """OrcaSlicer container'ının Downloads klasörünü döndürür (host path)."""
    config = load_config()
    path = config.get("orca_slicer", {}).get("downloads_dir", "/srv/orcaslicer/config/Downloads")
    os.makedirs(path, exist_ok=True)
    return path

def get_db_config():
    """Veritabanı bağlantı ayarlarını döndürür."""
    config = load_config()
    return config.get("database", {})

def get_temp_dir():
    """Geçici dosyalar için klasör yolunu döndürür."""
    config = load_config()
    temp_dir = config.get("temp_dir", "C:\\Temp\\3d_models")
    
    # Klasörü oluştur (yoksa)
    os.makedirs(temp_dir, exist_ok=True)
    return temp_dir

# Modül import edildiğinde config'i yükle
CONFIG = load_config()

if __name__ == "__main__":
    # Test için
    print("=== Yapılandırma Testi ===")
    print(f"Orca Profil Yolu: {get_orca_profile_path()}")
    print(f"Printerlar Klasörü: {get_printers_dir()}")
    print(f"Filamentler Klasörü: {get_filaments_dir()}")
    print(f"Temp Klasör: {get_temp_dir()}")
    print(f"Veritabanı: {get_db_config()}")
