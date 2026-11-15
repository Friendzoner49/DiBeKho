"""HTTPS for every network call of the app (Cloud, exchange rate): one SSL context that knows the root certificates.

A Python packed by PyInstaller on macOS finds no certificate store of its own (python.org builds expect the user to run
"Install Certificates.command"), so every https:// call failed there with CERTIFICATE_VERIFY_FAILED and the app only
said 'cannot reach the Cloud' (0.5.3 on a Mac, 15/11/2026). Windows reads its own store, which is why it worked there.
Order: the system's defaults when they hold certificates, else certifi's bundle (shipped with the app), else the file
macOS itself keeps (/etc/ssl/cert.pem)."""

import ssl
from pathlib import Path

_SYSTEM_FILES = ("/etc/ssl/cert.pem", "/private/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt")
_context: ssl.SSLContext | None = None


def ca_count(ctx: ssl.SSLContext) -> int:
    return int(ctx.cert_store_stats().get("x509_ca", 0))


def ssl_context() -> ssl.SSLContext:
    global _context
    if _context is not None:
        return _context
    ctx = ssl.create_default_context()
    if ca_count(ctx) == 0:
        try:
            import certifi
            ctx.load_verify_locations(cafile=certifi.where())
        except (ImportError, OSError, ssl.SSLError):
            pass
    if ca_count(ctx) == 0:
        for name in _SYSTEM_FILES:
            if Path(name).is_file():
                try:
                    ctx.load_verify_locations(cafile=name)
                    break
                except (OSError, ssl.SSLError):
                    continue
    _context = ctx
    return ctx
