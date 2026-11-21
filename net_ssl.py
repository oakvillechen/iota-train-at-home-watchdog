#!/usr/bin/env python3
"""
net_ssl.py - 带证书校验的 HTTPS 上下文

PyInstaller 打包的 Python 自带 OpenSSL，通常找不到系统 CA，过去的做法是直接关闭证书校验。
这里改为：默认 CA + macOS 钥匙串中的根证书 (含 Zscaler 等企业代理根证书) + 可选 certifi，
始终开启证书与主机名校验。
"""
import os
import ssl
import subprocess
import threading

_KEYCHAINS = [
    "/System/Library/Keychains/SystemRootCertificates.keychain",
    "/Library/Keychains/System.keychain",
    os.path.expanduser("~/Library/Keychains/login.keychain-db"),
]

_lock = threading.Lock()
_cached_pem = None


def _keychain_pem() -> str:
    global _cached_pem
    with _lock:
        if _cached_pem is not None:
            return _cached_pem
        chunks = []
        for kc in _KEYCHAINS:
            if not os.path.exists(kc):
                continue
            try:
                out = subprocess.run(
                    ["/usr/bin/security", "find-certificate", "-a", "-p", kc],
                    capture_output=True, text=True, timeout=20,
                )
                if out.returncode == 0:
                    chunks.append(out.stdout)
            except Exception:
                pass
        _cached_pem = "\n".join(chunks)
        return _cached_pem


def create_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(cafile=certifi.where())
    except Exception:
        pass
    for env in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        path = os.environ.get(env, "")
        if path and os.path.isfile(path):
            try:
                ctx.load_verify_locations(cafile=path)
            except Exception:
                pass
    pem = _keychain_pem()
    if pem:
        # 逐张加载：钥匙串中个别证书格式异常时不影响其他证书
        for block in pem.split("-----END CERTIFICATE-----"):
            if "-----BEGIN CERTIFICATE-----" not in block:
                continue
            try:
                ctx.load_verify_locations(cadata=block.strip() + "\n-----END CERTIFICATE-----\n")
            except Exception:
                pass
    return ctx


_default_ctx = None


def default_context() -> ssl.SSLContext:
    global _default_ctx
    if _default_ctx is None:
        _default_ctx = create_context()
    return _default_ctx


def install_default():
    """让 urllib 等未显式传 context 的调用也使用校验证书的上下文。"""
    ssl._create_default_https_context = lambda *a, **kw: default_context()
