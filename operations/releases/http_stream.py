"""Copy available HTTP bytes and close upstream when the caller disconnects."""
import select
import socket
import threading


def copy_response(response, connection, output):
    upstream = response
    for _ in range(6):
        if hasattr(upstream, "_sock"):
            upstream = upstream._sock
            break
        upstream = getattr(upstream, "raw", None) or getattr(upstream, "fp", None)
        if upstream is None:
            break
    done = threading.Event()

    def watch_disconnect():
        while not done.is_set():
            try:
                readable, _, _ = select.select([connection], [], [], 0.1)
                if readable:
                    if not connection.recv(1, socket.MSG_PEEK) and upstream is not None and hasattr(upstream, "shutdown"):
                        upstream.shutdown(socket.SHUT_RDWR)
                    return
            except OSError:
                return

    watcher = threading.Thread(target=watch_disconnect, daemon=True)
    watcher.start()
    try:
        read = getattr(response, "read1", response.read)
        while chunk := read(65536):
            output.write(chunk)
            output.flush()
    finally:
        done.set()
        response.close()
