from pathlib import Path
import json

from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET


# ─────────────────────────────────────────────
# SAFE FILE RESOLVER
# ─────────────────────────────────────────────
def find_static_file(filename: str):
    """
    Searches in:
    1. STATIC_ROOT (production)
    2. STATICFILES_DIRS (dev)
    3. BASE_DIR/static (fallback)
    """

    search_paths = []

    if getattr(settings, "STATIC_ROOT", None):
        search_paths.append(Path(settings.STATIC_ROOT) / filename)

    for d in getattr(settings, "STATICFILES_DIRS", []):
        search_paths.append(Path(d) / filename)

    search_paths.append(Path(settings.BASE_DIR) / "static" / filename)

    for path in search_paths:
        if path.exists():
            return path

    return None


# ─────────────────────────────────────────────
# SERVICE WORKER
# ─────────────────────────────────────────────
@require_GET
@cache_control(max_age=0, no_cache=True, no_store=True, must_revalidate=True)
def service_worker(request):
    sw_path = find_static_file("sw.js")

    if not sw_path:
        return HttpResponse("sw.js not found", status=404)

    response = FileResponse(open(sw_path, "rb"), content_type="application/javascript")
    response["Service-Worker-Allowed"] = "/"
    return response


# ─────────────────────────────────────────────
# MANIFEST
# ─────────────────────────────────────────────
@require_GET
@cache_control(max_age=86400)
def web_manifest(request):
    manifest_path = Path(settings.BASE_DIR) / "manifest.json"

    if not manifest_path.exists():
        return HttpResponse("manifest.json not found", status=404)

    with open(manifest_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    return HttpResponse(
        json.dumps(data),
        content_type="application/manifest+json"
    )


# ─────────────────────────────────────────────
# OFFLINE PAGE
# ─────────────────────────────────────────────
@require_GET
def offline_page(request):
    html = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Lynctel — Offline</title>
<style>
body{font-family:sans-serif;background:#f8f9fa;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}
.card{background:#fff;padding:30px;border-radius:16px;box-shadow:0 4px 20px rgba(0,0,0,.1);text-align:center;max-width:360px}
button{background:#1a1a2e;color:#fff;border:0;padding:12px 20px;border-radius:8px;width:100%}
</style>
</head>
<body>
<div class="card">
<div style="font-size:50px">📶</div>
<h2>You are offline</h2>
<p>Check your internet connection.</p>
<button onclick="location.reload()">Retry</button>
</div>
</body>
</html>"""

    return HttpResponse(html)