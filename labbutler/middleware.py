"""Project-wide response-header middleware."""

from __future__ import annotations

from django.conf import settings


class ContentSecurityPolicyMiddleware:
    """Attach the Content-Security-Policy header to every response.

    Template auto-escaping is the first line of defence against XSS; the CSP is the
    safety net if an escape is ever missed. The policy lives in
    ``settings.CONTENT_SECURITY_POLICY`` so a deployment can adjust it via env.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.policy = settings.CONTENT_SECURITY_POLICY

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("Content-Security-Policy", self.policy)
        return response
