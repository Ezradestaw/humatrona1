from django.http import HttpResponse
from django.shortcuts import render
from subscriptions.models import SubscriptionPlan


def home_view(request):
    """
    Section 6: Professional landing page.
    Explains the product concisely:
    Convert PDF documents into image-based PDFs quickly and securely.
    Primary action: Process a PDF. Secondary action: View Subscriptions.
    1. Upload PDF, 2. Process PDF, 3. Download result.
    """
    plans = SubscriptionPlan.objects.filter(active=True).order_by('sort_order', 'price')[:4]
    return render(request, 'home.html', {'plans': plans})


def about_view(request):
    """
    Section 7: About page.
    Explains what Humatron does, PDF processing service, privacy/security principles, supported workflow.
    """
    return render(request, 'about.html')


def robots_txt_view(request):
    lines = [
        "User-agent: *",
        "Disallow: /admin/",
        "Disallow: /api/",
        "Disallow: /pdf/jobs/",
        "Disallow: /payments/",
        "Disallow: /accounts/",
        "Allow: /",
        "Sitemap: https://humatron.me/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def sitemap_xml_view(request):
    content = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://humatron.me/</loc><priority>1.0</priority></url>
  <url><loc>https://humatron.me/about/</loc><priority>0.8</priority></url>
  <url><loc>https://humatron.me/subscriptions/</loc><priority>0.9</priority></url>
  <url><loc>https://humatron.me/contact/</loc><priority>0.7</priority></url>
  <url><loc>https://humatron.me/accounts/register/</loc><priority>0.6</priority></url>
  <url><loc>https://humatron.me/accounts/login/</loc><priority>0.6</priority></url>
</urlset>"""
    return HttpResponse(content, content_type="application/xml")


def error_400(request, exception=None):
    return render(request, 'errors/400.html', status=400)


def error_403(request, exception=None):
    return render(request, 'errors/403.html', status=403)


def error_404(request, exception=None):
    return render(request, 'errors/404.html', status=404)


def error_500(request):
    return render(request, 'errors/500.html', status=500)
