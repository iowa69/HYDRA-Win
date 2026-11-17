"""Downloads that work where the user's browser works, and say why when they do not.

Only the two first-launch databases (PubMLST, CARD) are downloaded on the
user's PC; everything else ships in the zip. Upstream's fetcher
(:mod:`hydra_amr.db.fetch`) uses plain ``urllib``, which on a hospital network
typically fails in one of three ways a browser does not:

* **TLS inspection** - the network re-signs HTTPS with its own root certificate,
  installed in the Windows certificate store but unknown to Python. With
  ``truststore``, Python verifies certificates through Windows itself, exactly
  as the browser does.
* **Proxy auto-configuration (PAC/WPAD)** - ``urllib`` reads a fixed proxy from
  the registry but cannot evaluate a PAC script. Windows is asked which proxy it
  would use for each host (``WebRequest.GetSystemWebProxy``), and that is used.
* **Authenticating proxies** (NTLM/Kerberos) - ``urllib`` cannot answer the
  proxy's challenge. As a last resort the file is fetched by Windows' own
  ``WebClient`` with the system proxy and the user's logon credentials.

Every failure is reduced to one plain reason - an HTTP status, an untrusted
certificate, a timeout, a proxy refusal, a name that does not resolve - which is
logged and recorded per database (:mod:`hydra_win.databases`).
"""

from __future__ import annotations

import logging
import os
import socket
import ssl
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

from hydra_amr.db import fetch as upstream_fetch
from hydra_amr.utils import HydraError

LOG = logging.getLogger("hydra")

#: Seconds without data before a connection is given up (per socket operation).
TIMEOUT = upstream_fetch.TIMEOUT
_installed = False
_truststore = False
_proxy_cache: dict[str, str | None] = {}
#: host -> the route that last worked ("direct", "proxy", "windows"). A PubMLST
#: install is over a thousand files from one host; once the direct route has
#: timed out and another worked, the rest go straight to the one that works.
_route: dict[str, str] = {}
#: host -> consecutive downloads for which every route failed. After a few, the
#: host is treated as unreachable and later files fail at once with the reason.
_dead: dict[str, int] = {}
_dead_reason: dict[str, str] = {}
DEAD_AFTER = 3
#: The Windows-only routes are tried only on Windows (a flag so tests can set it).
WINDOWS = os.name == "nt"


def install() -> None:
    """Route upstream's downloads through this module (idempotent)."""
    global _installed, _truststore
    if _installed:
        return
    _installed = True
    if os.name == "nt":
        try:
            import truststore  # noqa: PLC0415

            truststore.inject_into_ssl()
            _truststore = True
        except Exception as exc:  # noqa: BLE001 - fall back to Python's own store
            LOG.debug("truststore not available (%s); using Python's certificate list", exc)
    original = upstream_fetch._get_once

    def get_once(url: str, dest: Path, progress=None) -> Path:
        return fetch_once(url, dest, progress, _first=original)

    upstream_fetch._get_once = get_once


def describe_failure(exc: BaseException) -> str:
    """One plain-language reason for a failed download."""
    seen = set()
    while isinstance(exc, HydraError) and exc.__cause__ is not None and id(exc) not in seen:
        seen.add(id(exc))
        exc = exc.__cause__
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 407:
            return "the proxy server requires authentication (HTTP 407)"
        return f"the server answered HTTP {exc.code} {exc.reason or ''}".rstrip()
    reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
    if isinstance(reason, ssl.SSLCertVerificationError) or (
            isinstance(reason, ssl.SSLError) and "CERTIFICATE_VERIFY_FAILED" in str(reason)):
        return ("the server's TLS certificate is not trusted (" + _short(reason) + "); if this "
                "network inspects HTTPS traffic, its root certificate must be in the Windows "
                "certificate store")
    if isinstance(reason, ssl.SSLError):
        return f"TLS connection failed ({_short(reason)})"
    if isinstance(reason, (socket.timeout, TimeoutError)):
        return f"no answer within {TIMEOUT} s (timed out)"
    if isinstance(reason, socket.gaierror):
        return "the server name could not be resolved (no internet access, or DNS blocked)"
    if isinstance(reason, ConnectionRefusedError):
        return "the connection was refused"
    if isinstance(reason, ConnectionResetError):
        return "the connection was reset (often a firewall or proxy)"
    if isinstance(reason, OSError) and "proxy" in str(reason).lower():
        return f"the proxy refused the connection ({_short(reason)})"
    if isinstance(reason, HydraError):
        return _short(reason)
    return _short(reason) or type(reason).__name__


def _short(exc) -> str:
    text = str(getattr(exc, "reason", None) or exc).strip()
    return text.splitlines()[0][:200] if text else ""


def _system_proxy(url: str) -> str | None:
    """The proxy Windows would use for *url* (PAC and WPAD included), or None."""
    if not WINDOWS:
        return None
    host = urlsplit(url).netloc
    if host in _proxy_cache:
        return _proxy_cache[host]
    script = ("$p=[System.Net.WebRequest]::GetSystemWebProxy();"
              f"$u=[Uri]'{url}';$r=$p.GetProxy($u);"
              "if($r.AbsoluteUri -ne $u.AbsoluteUri){$r.AbsoluteUri}")
    proxy = None
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, timeout=30,
                             stdin=subprocess.DEVNULL, creationflags=0x08000000)
        proxy = (out.stdout or "").strip() or None
    except (OSError, subprocess.SubprocessError) as exc:
        LOG.debug("could not ask Windows for its proxy: %s", exc)
    _proxy_cache[host] = proxy
    if proxy:
        LOG.info("using the Windows system proxy %s for %s", proxy, host)
    return proxy


def _via_proxy(url: str, dest: Path, proxy: str) -> Path:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(
        {"http": proxy, "https": proxy}))
    request = urllib.request.Request(url, headers={"User-Agent": upstream_fetch.USER_AGENT})
    with opener.open(request, timeout=TIMEOUT) as response, open(dest, "wb") as handle:
        while True:
            block = response.read(1 << 16)
            if not block:
                break
            handle.write(block)
    if dest.stat().st_size == 0:
        raise HydraError(f"{url} returned an empty file")
    return dest


def _via_windows(url: str, dest: Path) -> Path:
    """Windows' own downloader: system proxy, PAC and the user's logon credentials."""
    script = ("$ProgressPreference='SilentlyContinue';"
              "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12;"
              "$w=New-Object System.Net.WebClient;"
              "$w.Proxy=[System.Net.WebRequest]::GetSystemWebProxy();"
              "$w.Proxy.Credentials=[System.Net.CredentialCache]::DefaultNetworkCredentials;"
              f"$w.Headers.Add('User-Agent','{upstream_fetch.USER_AGENT}');"
              "$w.DownloadFile($env:HYDRA_URL,$env:HYDRA_DEST)")
    env = dict(os.environ, HYDRA_URL=url, HYDRA_DEST=str(dest))
    out = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                         capture_output=True, text=True, timeout=TIMEOUT * 3, env=env,
                         stdin=subprocess.DEVNULL, creationflags=0x08000000)
    if out.returncode != 0 or not dest.exists() or dest.stat().st_size == 0:
        message = (out.stderr or out.stdout or "").strip().splitlines()
        raise HydraError(f"Windows downloader failed: {message[0] if message else out.returncode}")
    return dest


def fetch_once(url: str, dest: Path, progress=None, *, _first=None) -> Path:
    """One download attempt: urllib, then the Windows proxy, then Windows itself."""
    first = _first or upstream_fetch._get_once
    host = urlsplit(url).netloc
    if _dead.get(host, 0) >= DEAD_AFTER:
        raise HydraError(f"could not download {url}: {_dead_reason.get(host, 'unreachable')} "
                         f"(gave up on {host} after {DEAD_AFTER} failed downloads)")
    reason = ""
    if _route.get(host, "direct") == "direct":
        try:
            result = first(url, dest, progress)
            _route[host], _dead[host] = "direct", 0
            return result
        except HydraError as exc:
            reason = describe_failure(exc)
            cause = exc.__cause__
            if isinstance(cause, urllib.error.HTTPError) and cause.code != 407:
                # The server answered: a different route would get the same answer.
                raise HydraError(f"could not download {url}: {reason} ({cause})") from exc
            if not WINDOWS:
                raise HydraError(f"could not download {url}: {reason}") from exc
            LOG.debug("direct download of %s failed (%s); trying the Windows network "
                      "settings", url, reason)
    dest.parent.mkdir(parents=True, exist_ok=True)
    proxy = _system_proxy(url)
    if proxy and _route.get(host) in (None, "direct", "proxy"):
        try:
            result = _via_proxy(url, dest, proxy)
            _route[host], _dead[host] = "proxy", 0
            return result
        except (urllib.error.URLError, OSError, HydraError) as exc:
            LOG.debug("via proxy %s: %s", proxy, describe_failure(exc))
            reason = reason or describe_failure(exc)
    try:
        result = _via_windows(url, dest)
        if _route.get(host) != "windows":
            LOG.info("downloading from %s through Windows' own downloader", host)
        _route[host], _dead[host] = "windows", 0
        return result
    except (OSError, subprocess.SubprocessError, HydraError) as exc:
        _dead[host] = _dead.get(host, 0) + 1
        reason = reason or _short(exc)
        _dead_reason[host] = reason
        _route.pop(host, None)
        raise HydraError(f"could not download {url}: {reason} (Windows' own downloader also "
                         f"failed: {_short(exc)})") from exc


def environment() -> dict:
    """What the download path will use, for --db-status and the log."""
    return {"truststore": _truststore,
            "proxies": {k: v for k, v in urllib.request.getproxies().items()
                        if k in ("http", "https")},
            "timeout_s": TIMEOUT}
