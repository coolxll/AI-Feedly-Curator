from PIL import Image
import os

target_dir = r'c:\Workspace\Personal\rss-opml\arena-app\src-tauri\icons'

for f in os.listdir(target_dir):
    if f.endswith('.png') or f.endswith('.ico'):
        try:
            img = Image.open(os.path.join(target_dir, f))
            print(f"{f}: {img.size} {img.format}")
            if f.endswith('.ico'):
                print(f"  ICO layers: {img.info.get('sizes')}")
        except Exception as e:
            print(f"Error opening {f}: {e}")
