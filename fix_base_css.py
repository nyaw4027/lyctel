"""
fix_base_css.py — Run from project root: python fix_base_css.py
Fixes the mangled line 93 in base.html and adds CSS links correctly.
"""

path = 'templates/base.html'
content = open(path, encoding='utf-8').read()

# The mangled string that PowerShell created
mangled = (
    '<link href="https://fonts.googleapis.com/css2?family=Syne:wght@600;700;800'
    '&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600'
    ';1,9..40,400&display=swap" rel="stylesheet"/>`n  {% load static %}`n  '
    '<link rel="stylesheet" href="{% static \'css/output.css\' %}">`n  '
    '<link rel="stylesheet" href="{% static \'css/uploads.css\' %}">'
)

# What it should be
correct = (
    '<link href="https://fonts.googleapis.com/css2?family=Syne:wght@600;700;800'
    '&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600'
    ';1,9..40,400&display=swap" rel="stylesheet"/>\n'
    '  <link rel="stylesheet" href="/static/css/output.css">\n'
    '  <link rel="stylesheet" href="/static/css/uploads.css">'
)

if mangled in content:
    content = content.replace(mangled, correct)
    open(path, 'w', encoding='utf-8').write(content)
    print('✅ Fixed base.html — CSS links now on separate lines.')
else:
    print('Mangled string not found exactly — checking for partial match...')
    # Try to find and show what line 93 actually contains
    lines = content.split('\n')
    for i, line in enumerate(lines[90:96], 91):
        print(f'{i}: {line[:120]}')
    print('\nManual fix needed — open base.html in VS Code, find line 93, and replace with:')
    print(correct)