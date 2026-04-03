import os
from PIL import Image

src_path = r'C:\Users\coolx\.gemini\antigravity\brain\9956d7bf-12f0-4035-aa65-3f2e3a784a70\arena_app_icon_hq_1774949484112.png'
target_dir = r'c:\Workspace\Personal\rss-opml\arena-app\src-tauri\icons'

# Open source image
img = Image.open(src_path)

# Ensure target icon dir exists
os.makedirs(target_dir, exist_ok=True)

# 1. icon.png (512x512)
img_512 = img.resize((512, 512), Image.Resampling.LANCZOS)
img_512.save(os.path.join(target_dir, 'icon.png'))
print("Saved icon.png")

# 2. icon.ico (multiple sizes)
ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save(os.path.join(target_dir, 'icon.ico'), sizes=ico_sizes, bitmap_format='bmp')
print("Saved icon.ico")

# 3. 32x32.png
img_32 = img.resize((32, 32), Image.Resampling.LANCZOS)
img_32.save(os.path.join(target_dir, '32x32.png'))
print("Saved 32x32.png")

# 4. 128x128.png
img_128 = img.resize((128, 128), Image.Resampling.LANCZOS)
img_128.save(os.path.join(target_dir, '128x128.png'))
print("Saved 128x128.png")

# 5. 128x128@2x.png (256x256)
img_256 = img.resize((256, 256), Image.Resampling.LANCZOS)
img_256.save(os.path.join(target_dir, '128x128@2x.png'))
print("Saved 128x128@2x.png")
