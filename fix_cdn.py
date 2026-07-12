content = open('templates/base.html', encoding='utf-8').read()
# Remove Tailwind CDN script
content = content.replace('<script src="https://cdn.tailwindcss.com" defer></script>', '')
open('templates/base.html', 'w', encoding='utf-8').write(content)
print('Done')
