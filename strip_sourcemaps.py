"""
Run this once locally to strip sourcemap comments from Bootstrap files:

    python strip_sourcemaps.py

This removes  /*# sourceMappingURL=...*/  and  //# sourceMappingURL=...
from bootstrap.min.css and bootstrap.bundle.min.js so Whitenoise
never tries to fingerprint the missing .map files.
"""
import re
import os

files_to_fix = [
    'static/css/bootstrap.min.css',
    'static/js/bootstrap.bundle.min.js',
    'static/js/bootstrap.bundle.min.js.map',   # delete if present
]

# Remove sourcemap comments
css_pattern = re.compile(r'/\*#\s*sourceMappingURL=[^\s*]+\s*\*/')
js_pattern  = re.compile(r'//# sourceMappingURL=\S+')

for path in files_to_fix:
    if not os.path.exists(path):
        print(f"  skip (not found): {path}")
        continue
    content = open(path, encoding='utf-8', errors='ignore').read()
    fixed   = css_pattern.sub('', content)
    fixed   = js_pattern.sub('', fixed)
    if fixed != content:
        open(path, 'w', encoding='utf-8').write(fixed.rstrip() + '\n')
        print(f"  ✓ Fixed: {path}")
    else:
        print(f"  ✓ Clean: {path}")

print("Done.")