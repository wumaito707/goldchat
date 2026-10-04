"""Public configuration for hosted sponsorship checkout; no payment secrets exposed."""
import os
from urllib.parse import urlsplit


def approved_checkout_url(value):
    value = value.strip()
    if not value or len(value) > 1000:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port:
            return None
        if parsed.fragment or parsed.query:
            return None
        if parsed.hostname == 'paystack.com' and parsed.path.startswith('/pay/') and len(parsed.path) > 5:
            return value
        if parsed.hostname == 'paystack.shop' and parsed.path not in ('', '/'):
            return value
    except ValueError:
        pass
    return None


def install(app):
    from fastapi.responses import JSONResponse

    @app.get('/api/sponsorship/checkout')
    def checkout_configuration():
        url = approved_checkout_url(os.environ.get('GOLDCHAT_PAYSTACK_PAYMENT_LINK', ''))
        return JSONResponse({'available': bool(url), 'provider': 'Paystack', 'checkout_url': url}, headers={'Cache-Control': 'no-store'})
