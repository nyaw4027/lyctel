content = open('templates/base.html', encoding='utf-8').read()

# Remove the first (duplicate) occurrence only
dup = '<link rel="stylesheet" href="{% static \'css/output.css\' %}"/>\n  <link rel="stylesheet" href="{% static \'css/main.css\' %}"/>\n  <link rel="stylesheet" href="{% static \'css/uploads.css\' %}"/>\n'
content = content.replace(dup, '', 1)
open('templates/base.html', 'w', encoding='utf-8').write(content)
print('Done')
