"""Small, bounded helpers for transient Kubernetes transport failures."""

TRANSIENT_MARKERS = (
    "tls handshake timeout",
    "unable to connect to the server: eof",
    "connection reset by peer",
    "connection refused",
    "i/o timeout",
    "context deadline exceeded",
    "server is currently unable to handle the request",
    "service unavailable",
    "gateway timeout",
)


def transient_failure(stdout: str | None, stderr: str | None) -> bool:
    message = f"{stdout or ''}\n{stderr or ''}".lower()
    return any(marker in message for marker in TRANSIENT_MARKERS)
