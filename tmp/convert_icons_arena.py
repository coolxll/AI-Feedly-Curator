import os
from PIL import Image

src_path = r'C:\Users\coolx\.gemini\antigravity\brain\0ce00428-194e-4c22-b712-b7e29c8313a4\scoring_arena_no_text_1774948454162.png'
target_dir = r'c:\Workspace\Personal\rss-opml\arena-app\src-tauri\icons'

# Open source image
img = Image.open(src_path)

# 1. Replace icon.png
img_png = img.resize((512, 512), Image.Resampling.LANCZOS)
img_png.save(os.path.join(target_dir, 'icon.png'))
print("Saved icon.png")

# 2. Replace icon.ico
ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
img.save(os.path.join(target_dir, 'icon.ico'), sizes=ico_sizes)
print("Saved icon.ico")
