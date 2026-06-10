from pathlib import Path
import json

from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET


@require_GET
@cache_control(max_age=0, no_cache=True, no_store=True, must_revalidate=True)
def service_worker(request):
    """Serve sw.js from static files"""

    sw_path = Path(settings.STATIC_ROOT) / "sw.js"

    if not sw_path.exists():
        for d in settings.STATICFILES_DIRS:
            candidate = Path(d) / "sw.js"
            if candidate.exists():
                sw_path = candidate
                break

    if not sw_path.exists():
        return HttpResponse("sw.js not found", status=404)

    return FileResponse(
        open(sw_path, "rb"),
        content_type="application/javascript",
        headers={"Service-Worker-Allowed": "/"},
    )


@require_GET
@cache_control(max_age=86400)
def web_manifest(request):
    """Serve manifest.json from BASE_DIR"""

    manifest_file = Path(settings.BASE_DIR) / "manifest.json"

    if not manifest_file.exists():
        return HttpResponse("manifest.json not found", status=404)

    with open(manifest_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    return HttpResponse(
        json.dumps(data),
        content_type="application/manifest+json"
    )


@require_GET
def offline_page(request):
    """Simple offline fallback page"""

    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Lynctel — You're Offline</title>
        <style>
            * { box-sizing: border-box; margin: 0; padding: 0; }
            body {
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                background: #f8f9fa;
                color: #333;
                display: flex;
                align-items: center;
                justify-content: center;
                min-height: 100vh;
                padding: 20px;
            }
            .card {
                background: white;
                border-radius: 16px;
                padding: 40px 32px;
                text-align: center;
                max-width: 380px;
                width: 100%;
                box-shadow: 0 4px 24px rgba(0,0,0,.08);
            }
            .icon { font-size: 64px; margin-bottom: 16px; }
            h1 { font-size: 24px; color: #1a1a2e; margin-bottom: 8px; }
            p { color: #666; line-height: 1.6; margin-bottom: 24px; }
            button {
                background: #1a1a2e;
                color: white;
                border: none;
                padding: 12px 28px;
                border-radius: 8px;
                font-size: 16px;
                cursor: pointer;
                width: 100%;
            }
            button:hover { background: #2d2d5e; }
        </style>
    </head>
    <body>
        <div class="card">
            <div class="icon">📶</div>
            <h1>You're offline</h1>
            <p>
                Check your internet connection and try again.
                Your cart and browsing history are saved for when you reconnect.
            </p>
            <button onclick="location.reload()">Try again</button>
        </div>
    </body>
    </html>
    """

    return HttpResponse(html)