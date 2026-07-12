import re

path = "templates/base.html"
content = open(path, encoding="utf-8").read()
original_len = len(content)

content = re.sub(
    r"<!-- ── ANTI-FLASH VEIL.*?</script>\s*",
    "",
    content,
    flags=re.DOTALL
)

content = re.sub(
    r"<!-- FIXED: the Tailwind CDN script tag.*?window\.tailwind\.config = \{.*?\};\s*</script>\s*",
    "",
    content,
    flags=re.DOTALL
)

if "css/output.css" not in content:
    content = content.replace(
        "<link rel=\"shortcut icon\" href=\"{% static 'icons/icon-96x96.png' %}\"/>",
        "<link rel=\"shortcut icon\" href=\"{% static 'icons/icon-96x96.png' %}\"/>\n\n  <link rel=\"stylesheet\" href=\"{% static 'css/output.css' %}\"/>"
    )

open(path, "w", encoding="utf-8").write(content)
print("Removed", original_len - len(content), "characters of dead CDN/veil code")
print("output.css link now present:", "css/output.css" in content)
