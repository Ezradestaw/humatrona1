import time
from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import render

RATE_LIMIT_RULES = {
    # path_prefix: (limit, window_seconds)
    '/accounts/login/': (10, 300),
    '/accounts/register/': (5, 600),
    '/accounts/password-reset/': (5, 600),
    '/contact/': (8, 600),
    '/pdf/upload/': (30, 60),
    '/api/pdf/process/': (30, 60),
}


class RateLimitMiddleware:
    """
    In-memory / Redis cache-backed rate limiting middleware for sensitive endpoints.
    Protects against brute-force authentication, spam, and DoS.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method == 'POST':
            path = request.path
            for rule_path, (max_requests, window_seconds) in RATE_LIMIT_RULES.items():
                if path.startswith(rule_path):
                    ip = self.get_client_ip(request)
                    cache_key = f"ratelimit:{rule_path}:{ip}"
                    requests_count = cache.get(cache_key, 0)
                    
                    if requests_count >= max_requests:
                        response = render(
                            request,
                            'errors/429.html',
                            {'retry_after': window_seconds},
                            status=429
                        )
                        response['Retry-After'] = str(window_seconds)
                        return response
                    
                    # Increment or initialize counter
                    if requests_count == 0:
                        cache.set(cache_key, 1, timeout=window_seconds)
                    else:
                        try:
                            cache.incr(cache_key)
                        except ValueError:
                            cache.set(cache_key, 1, timeout=window_seconds)
                    break

        return self.get_response(request)

    @staticmethod
    def get_client_ip(request):
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0].strip()
        else:
            ip = request.META.get('REMOTE_ADDR', '127.0.0.1')
        return ip
