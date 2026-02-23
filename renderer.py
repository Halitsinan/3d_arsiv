import os
import sys
import io
import trimesh
import numpy as np
from PIL import Image

# 1. En üstte zorla
os.environ["PYOPENGL_PLATFORM"] = "osmesa"

def render_3d_model(file_path):
    # 2. Fonksiyonun tam içinde tekrar zorla (Hata alan dosyalar için kritik)
    os.environ["PYOPENGL_PLATFORM"] = "osmesa"
    
    import pyrender # İmport işlemini burada yaparak ortam değişkenini garantileyelim
    
    r = None
    try:
        # Mesh Yükleme ve Normalleştirme (Merkeze alma ve Ölçekleme)
        mesh = trimesh.load(file_path, force='mesh')
        if isinstance(mesh, trimesh.Scene):
            mesh = trimesh.util.concatenate(list(mesh.geometry.values()))
        
        # Obje boyutunu normalize et (Küçük/Büyük dosya sorununu çözer)
        mesh.apply_translation(-mesh.centroid)
        scale = 1.0 / np.max(mesh.extents) if np.max(mesh.extents) != 0 else 1.0
        mesh.apply_scale(scale)

        scene = pyrender.Scene(bg_color=[0.1, 0.1, 0.1])
        material = pyrender.MetallicRoughnessMaterial(
            metallicFactor=0.5, roughnessFactor=0.5,
            baseColorFactor=[0.8, 0.5, 0.2, 1.0]
        )
        pyr_mesh = pyrender.Mesh.from_trimesh(mesh, material=material)
        scene.add(pyr_mesh)

        # İzometrik kamera konumu (45° yatay, 35.26° dikey açı)
        camera = pyrender.PerspectiveCamera(yfov=np.pi / 3.0)
        
        # İzometrik görünüm için kamera pozisyonu
        # X, Y, Z eksenlerinin tümünü görebileceğimiz açı
        distance = 2.5
        iso_angle_h = np.pi / 4  # 45 derece yatay
        iso_angle_v = np.arctan(1/np.sqrt(2))  # ~35.26 derece dikey (izometrik)
        
        cam_x = distance * np.cos(iso_angle_v) * np.cos(iso_angle_h)
        cam_y = distance * np.cos(iso_angle_v) * np.sin(iso_angle_h)
        cam_z = distance * np.sin(iso_angle_v)
        
        # Kamerayı objeye doğru yönlendir
        camera_pose = np.eye(4)
        camera_pos = np.array([cam_x, cam_y, cam_z])
        target = np.array([0, 0, 0])
        up = np.array([0, 0, 1])
        
        z_axis = camera_pos - target
        z_axis = z_axis / np.linalg.norm(z_axis)
        x_axis = np.cross(up, z_axis)
        x_axis = x_axis / np.linalg.norm(x_axis)
        y_axis = np.cross(z_axis, x_axis)
        
        camera_pose[:3, 0] = x_axis
        camera_pose[:3, 1] = y_axis
        camera_pose[:3, 2] = z_axis
        camera_pose[:3, 3] = camera_pos
        
        scene.add(camera, pose=camera_pose)
        
        # İki yönlü aydınlatma (izometrik görünüm için)
        light1 = pyrender.DirectionalLight(color=[1.0, 1.0, 1.0], intensity=8.0)
        light2 = pyrender.DirectionalLight(color=[0.8, 0.8, 1.0], intensity=4.0)
        scene.add(light1, pose=camera_pose)
        
        # İkinci ışık karşı taraftan
        light_pose2 = camera_pose.copy()
        light_pose2[:3, 3] = -camera_pos * 0.5
        scene.add(light2, pose=light_pose2)

        # Render motorunu her seferinde temiz başlat (Orta kalite: 400x400)
        r = pyrender.OffscreenRenderer(400, 400)
        color, _ = r.render(scene)
        
        img = Image.fromarray(color).convert("RGB")
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=70, optimize=True)
        return out.getvalue()

    except Exception as e:
        print(f"      🚨 Render Motoru Hatası: {str(e)}")
        return None
    finally:
        if r:
            try: r.delete()
            except: pass