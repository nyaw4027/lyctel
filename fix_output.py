content = open('templates/base.html', encoding='utf-8').read()
old = '    <!-- Main Styles -->'
new = '    <!-- Compiled Tailwind (no CDN) -->\n    <link rel="stylesheet" href="{% static \'css/output.css\' %}">\n    <!-- Main Styles -->'
if old in content:
    content = content.replace(old, new, 1)
    open('templates/base.html', 'w', encoding='utf-8').write(content)
    print('SUCCESS')
else:
    print('NOT FOUND - searching...')
    idx = content.find('main.css')
    print(repr(content[idx-200:idx+50]))
