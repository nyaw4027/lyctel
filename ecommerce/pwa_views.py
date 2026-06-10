
# ecommerce/pwa_views.py

from pathlib import Path
import json

from django.conf import settings
from django.http import FileResponse, HttpResponse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET


@require_GET
@cache_control(max_age=0, no_cache=True, no_store=True, must_revalidate=True)
def service_worker(request):
    """
    Serve the service worker from /sw.js
    """

    sw_file = Path(settings.BASE_DIR) / "static" / "sw.js"

    if not sw_file.exists():
        return HttpResponse(
            "Service worker not found",
            status=404,
            content_type="text/plain"
        )

    response = FileResponse(
        open(sw_file, "rb"),
        content_type="application/javascript"
    )

    response["Service-Worker-Allowed"] = "/"

    return response


@require_GET
@cache_control(max_age=86400)
def web_manifest(request):
    """
    Serve manifest.json from the project root.
    """

    manifest_file = Path(settings.BASE_DIR) / "manifest.json"

    if not manifest_file.exists():
        return HttpResponse(
            "manifest.json not found",
            status=404,
            content_type="text/plain"
        )

    with open(manifest_file, "r", encoding="utf-8") as f:
        manifest_data = json.load(f)

    return HttpResponse(
        json.dumps(manifest_data),
        content_type="application/manifest+json"
    )


@require_GET
def offline_page(request):
    """
    Offline fallback page.
    """

    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">

        <title>Lynctel — You're Offline</title>

        <style>
            * {
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }

            body {
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                background: #f8f9fa;
                color: #333;
                display: flex;
                justify-content: center;
                align-items: center;
                min-height: 100vh;
                padding: 20px;
            }

            .card {
                background: #fff;
                border-radius: 16px;
                padding: 40px 32px;
                max-width: 400px;
                width: 100%;
                text-align: center;
                box-shadow: 0 4px 24px rgba(0,0,0,.08);
            }

            .icon {
                font-size: 64px;
                margin-bottom: 16px;
            }

            h1 {
                color: #1a1a2e;
                margin-bottom: 12px;
            }

            p {
                color: #666;
                line-height: 1.6;
                margin-bottom: 24px;
            }

            button {
                background: #1a1a2e;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 12px 24px;
                cursor: pointer;
                font-size: 16px;
                width: 100%;
            }

            button:hover {
                opacity: 0.95;
            }
        </style>
    </head>

    <body>
        <div class="card">
            <div class="icon">📶</div>

            <h1>You're Offline</h1>

            <p>
                Check your internet connection and try again.
                Your cart and browsing history will be available
                when you reconnect.
            </p>

            <button onclick="window.location.reload()">
                Try Again
            </button>
        </div>
    </body>
    </html>
    """

    return HttpResponse(html)

