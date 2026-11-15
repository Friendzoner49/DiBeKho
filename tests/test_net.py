"""HTTPS root certificates (core/net.py): a Python with an empty certificate store (the packed Mac app, 0.5.3) still
verifies https:// through certifi's bundle; every network call of the app uses that one context."""

import ssl

from dibekho.core import net


def test_an_empty_system_store_falls_back_to_certifi(monkeypatch):
    monkeypatch.setattr(net, "_context", None)
    monkeypatch.setattr(net.ssl, "create_default_context", lambda: ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
    ctx = net.ssl_context()
    assert net.ca_count(ctx) > 50
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname
    monkeypatch.setattr(net, "_context", None)


def test_the_cloud_and_the_rate_use_it():
    from pathlib import Path

    src = Path(net.__file__).resolve().parent
    for name in ("cloud/client.py", "fx.py"):
        text = (src / name).read_text(encoding="utf-8")
        assert "urlopen(" in text and "context=net.ssl_context()" in text, name
