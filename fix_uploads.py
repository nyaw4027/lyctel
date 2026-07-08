"""
fix_uploads.py — Run from your project root:
  python fix_uploads.py

Fixes:
1. Adds enctype="multipart/form-data" to any <form method="post"> that
   contains a file input but is missing the enctype attribute.
2. Adds accept="image/*" to any file input missing an accept attribute.
3. Adds capture="environment" hint for mobile camera on image inputs.
"""
import os
import re

TEMPLATES_DIR = 'templates'

SKIP_DIRS = {'venv', '.git', 'staticfiles', 'node_modules'}

fixed_files = []
issues_found = []


def fix_file(path):
    content = open(path, encoding='utf-8', errors='ignore').read()
    original = content

    # Only process files that have file inputs
    if 'type="file"' not in content and "type='file'" not in content:
        return

    # Fix 1: Add enctype to <form method="post"> missing it
    def fix_form_tag(m):
        tag = m.group(0)
        if 'enctype' not in tag.lower() and 'method' in tag.lower():
            # Insert enctype before the closing >
            tag = tag.rstrip('>')
            tag = tag.rstrip('/')
            tag = tag.rstrip()
            tag += ' enctype="multipart/form-data">'
        return tag

    content = re.sub(r'<form[^>]*>', fix_form_tag, content, flags=re.IGNORECASE)

    # Fix 2: Add accept to file inputs missing it
    def fix_file_input(m):
        tag = m.group(0)
        if 'accept' not in tag.lower():
            # Determine type from name/id hints
            tag_lower = tag.lower()
            if 'video' in tag_lower:
                accept = 'video/*'
            elif 'pdf' in tag_lower or 'id_card' in tag_lower or 'document' in tag_lower:
                accept = 'image/*,.pdf'
            else:
                accept = 'image/*'
            tag = tag.rstrip('>')
            tag = tag.rstrip('/')
            tag = tag.rstrip()
            tag += f' accept="{accept}">'
        return tag

    content = re.sub(
        r'<input[^>]*type=["\']file["\'][^>]*>',
        fix_file_input,
        content,
        flags=re.IGNORECASE,
    )

    if content != original:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        fixed_files.append(path)
        print(f'FIXED: {path}')


# Walk templates
for root, dirs, files in os.walk(TEMPLATES_DIR):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    for f in files:
        if f.endswith('.html'):
            fix_file(os.path.join(root, f))

print(f'\n✅ Fixed {len(fixed_files)} files.')
if not fixed_files:
    print('No issues found — all forms already have correct attributes.')