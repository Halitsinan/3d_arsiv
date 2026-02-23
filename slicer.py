"""
Orca Slicer Docker entegrasyonu.
STL dosyalarını slice edip G-code oluşturur.
Çalışan lscr.io/linuxserver/orcaslicer container'ına docker exec ile bağlanır.
"""

import subprocess
import os
import shutil
import json
import config

# linuxserver/orcaslicer image içindeki binary yolu
ORCA_BINARY = "/opt/orcaslicer/bin/orca-slicer"
# Host config mount base -> container'da /config
CONTAINER_CONFIG_MOUNT = "/config"


def _to_container_path(host_path):
    """
    Host config yolunu container içi yola çevirir.
    Host: /srv/orcaslicer/config/.config/...
    Container: /config/.config/...
    """
    orca_profile = config.get_orca_profile_path()
    config_mount_base = orca_profile.split("/.config")[0]  # /srv/orcaslicer/config
    if host_path.startswith(config_mount_base):
        return CONTAINER_CONFIG_MOUNT + host_path[len(config_mount_base):]
    return host_path


def _run(cmd, timeout=10):
    """subprocess.run wrapper, (returncode, stdout+stderr) döner."""
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr).strip()


def slice_stl_with_docker(stl_path, printer_json, filament_json, process_json=None, output_gcode=None):
    """
    Çalışan OrcaSlicer container'ı içinde STL dosyasını slice eder.
    Adımlar:
      1. STL dosyasını docker cp ile container /tmp/'ye kopyala
      2. docker exec ile orca-slicer CLI çalıştır
      3. Oluşan gcode'u docker cp ile host'a kopyala
      4. Container'daki geçici dosyaları temizle

    Returns:
        (bool, str|None): (başarılı mı, hata mesajı)
    """
    container = config.get_docker_container()
    temp_dir  = config.get_temp_dir()
    os.makedirs(temp_dir, exist_ok=True)

    if not os.path.exists(stl_path):
        return False, f"STL dosyası bulunamadı: {stl_path}"

    stl_filename  = os.path.basename(stl_path)
    base_name     = os.path.splitext(stl_filename)[0]

    # Boşluk ve özel karakterleri temizle, uzantı yoksa .stl ekle
    safe_name = base_name.replace(" ", "_").replace("(", "").replace(")", "")
    ext = os.path.splitext(stl_filename)[1].lower()
    if ext not in ['.stl', '.obj', '.3mf', '.amf']:
        ext = '.stl'
    safe_stl_filename = safe_name + ext

    if not output_gcode:
        output_gcode = os.path.join(temp_dir, f"{safe_name}.gcode")

    gcode_filename   = os.path.basename(output_gcode)
    container_stl    = f"/tmp/{safe_stl_filename}"
    container_gcode  = f"/tmp/{safe_name}.gcode"

    # Printer/filament/process host yollarını container yoluna çevir
    c_printer  = _to_container_path(printer_json)
    c_filament = _to_container_path(filament_json)
    c_process  = _to_container_path(process_json) if process_json else None

    try:
        # 1. STL'yi container'a kopyala
        rc, out = _run(["docker", "cp", stl_path, f"{container}:{container_stl}"])
        if rc != 0:
            return False, f"docker cp (STL) hatası: {out}"
        print(f"📋 STL kopyalandı: {container_stl}")

        # 2. Slice komutu oluştur (OrcaSlicer 2.3.1 CLI)
        # bash -c ile çalıştırıyoruz ki boşluklu path'ler doğru tırnaklansın
        orca_datadir = "/config/.config/OrcaSlicer"

        bash_parts = [
            "xvfb-run", "-a", ORCA_BINARY,
            "--datadir",        f'"{orca_datadir}"',
            "--load-settings",  f'"{c_printer}"',
            "--load-filaments", f'"{c_filament}"',
        ]
        if c_process:
            bash_parts += ["--load-settings", f'"{c_process}"']
        bash_parts += ["--slice", "1", "--outputdir", "/tmp", f'"{container_stl}"']

        bash_cmd = " ".join(bash_parts)

        slice_cmd = ["docker", "exec", container, "bash", "-c", bash_cmd]

        print(f"🔪 Slice komutu: {' '.join(slice_cmd)}")

        rc, out = _run(slice_cmd, timeout=300)
        if rc != 0:
            return False, f"Slice hatası (rc={rc}):\n{out}"
        print(f"✅ Slice tamamlandı. Çıktı: {container_gcode}")

        # 3. Gcode'u host'a kopyala
        rc, out = _run(["docker", "cp", f"{container}:{container_gcode}", output_gcode])
        if rc != 0:
            return False, f"docker cp (gcode) hatası: {out}"

        if not os.path.exists(output_gcode):
            return False, "Gcode dosyası host'a kopyalanamadı"

        return True, None

    except subprocess.TimeoutExpired:
        return False, "Slice işlemi zaman aşımına uğradı (5 dakika)"
    except Exception as e:
        return False, str(e)
    finally:
        # 4. Container içi geçici dosyaları temizle
        subprocess.run(
            ["docker", "exec", container, "rm", "-f", container_stl, container_gcode],
            capture_output=True
        )


def get_available_printers():
    """
    Docker config'deki tüm printer JSON dosyalarını listeler.
    
    Returns:
        list: [json_path1, json_path2, ...]
    """
    printers_dir = config.get_printers_dir()
    
    if not printers_dir or not os.path.exists(printers_dir):
        return []
    
    printers = []
    for filename in os.listdir(printers_dir):
        if filename.endswith('.json'):
            json_path = os.path.join(printers_dir, filename)
            printers.append(json_path)
    
    return sorted(printers)


def get_available_filaments():
    """
    Docker config'deki tüm filament JSON dosyalarını listeler.
    
    Returns:
        list: [json_path1, json_path2, ...]
    """
    filaments_dir = config.get_filaments_dir()
    
    if not filaments_dir or not os.path.exists(filaments_dir):
        return []
    
    filaments = []
    for filename in os.listdir(filaments_dir):
        if filename.endswith('.json'):
            json_path = os.path.join(filaments_dir, filename)
            filaments.append(json_path)
    
    return sorted(filaments)


def get_available_processes():
    """
    Docker config'deki tüm process JSON dosyalarını listeler.
    
    Returns:
        list: [json_path1, json_path2, ...]
    """
    process_dir = config.get_process_dir()
    
    if not process_dir or not os.path.exists(process_dir):
        return []
    
    processes = []
    for filename in os.listdir(process_dir):
        if filename.endswith('.json'):
            json_path = os.path.join(process_dir, filename)
            processes.append(json_path)
    
    return sorted(processes)


if __name__ == "__main__":
    # Test
    print("=== Orca Slicer Docker Test ===")
    print(f"Config yolu: {config.get_orca_profile_path()}")
    print(f"Docker container: {config.get_docker_container()}")
    print(f"Web URL: {config.get_orca_web_url()}")
    print()
    
    print("Mevcut Printerlar:")
    for path in get_available_printers():
        print(f"  - {os.path.basename(path)}")
    
    print("\nMevcut Filamentler:")
    for path in get_available_filaments():
        print(f"  - {os.path.basename(path)}")
    
    print("\nMevcut Process'ler:")
    for path in get_available_processes():
        print(f"  - {os.path.basename(path)}")
