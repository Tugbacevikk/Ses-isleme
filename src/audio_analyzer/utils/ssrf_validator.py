import ipaddress
import logging
import os
import socket
import urllib.parse
from typing import Optional

logger = logging.getLogger(__name__)

def validate_callback_url(url: Optional[str]) -> bool:
    """
    Callback URL'yi SSRF (Server-Side Request Forgery) saldırılarına karşı doğrular.
    - Sadece https kabul edilir (http yalnızca APP_ENV=development iken izinlidir).
    - WEBHOOK_ALLOWED_HOSTS tanımlıysa kontrol edilir.
    - DNS çözümlemesi ile IP bulunur; private, loopback, link-local (169.254.0.0/16 dahil), multicast ve reserved IP'ler reddedilir.
    """
    if not url or not url.strip():
        return True

    try:
        parsed = urllib.parse.urlparse(url.strip())
        scheme = (parsed.scheme or "").lower()
        hostname = parsed.hostname
    except Exception as ex:
        logger.warning("SSRF Validator URL ayrıştırma hatası (%s): %s", url, ex)
        return False

    if not scheme or not hostname:
        return False

    app_env = os.getenv("APP_ENV", os.getenv("ENV", "production")).lower()

    # 1. Scheme kontrolü (Sadece https; http yalnızca APP_ENV=development'ta)
    if scheme == "http" and app_env != "development":
        logger.warning("SSRF Reddi: Production ortamında HTTP callback URL kabul edilmez (%s).", url)
        return False
    if scheme not in ("http", "https"):
        logger.warning("SSRF Reddi: Desteklenmeyen şema (%s).", scheme)
        return False

    # 2. Whitelist kontrolü (WEBHOOK_ALLOWED_HOSTS)
    allowed_hosts_raw = os.getenv("WEBHOOK_ALLOWED_HOSTS", "").strip()
    if allowed_hosts_raw:
        allowed_hosts = [h.strip().lower() for h in allowed_hosts_raw.split(",") if h.strip()]
        if hostname.lower() not in allowed_hosts:
            logger.warning("SSRF Reddi: Hostname (%s) WEBHOOK_ALLOWED_HOSTS listesinde değil.", hostname)
            return False

    # 3. IP / Hostname çözme ve Özel IP Blokları Kontrolü
    try:
        addr_info = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        logger.warning("SSRF Reddi: Hostname (%s) DNS ile çözülemedi: %s", hostname, e)
        return False

    if not addr_info:
        return False

    for item in addr_info:
        ip_str = item[4][0]
        try:
            ip_obj = ipaddress.ip_address(ip_str)
            if (
                ip_obj.is_private
                or ip_obj.is_loopback
                or ip_obj.is_link_local
                or ip_obj.is_multicast
                or ip_obj.is_reserved
                or ip_obj.is_unspecified
            ):
                logger.warning("SSRF Reddi: URL %s iç ağ/özel IP adresine (%s) çözümlendi!", url, ip_str)
                return False
        except ValueError:
            return False

    return True
