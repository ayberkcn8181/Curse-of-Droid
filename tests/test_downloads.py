"""Deterministic download boundaries and actual loopback TLS; no public download or USB required."""
import hashlib
import io
import datetime as dt
import ipaddress
import ssl
import threading
import urllib.error
import urllib.request
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from curseofdroid.platform import net

URL = "https://example.org/rom.zip"
BODY = b"abcdef"
HASHES = {"sha256": hashlib.sha256(BODY).hexdigest()}


class Response(io.BytesIO):
    def __init__(self, body=BODY, status=200, **headers):
        super().__init__(body)
        self.status = status
        self.headers = Message()
        for key, value in headers.items():
            self.headers[key.replace("_", "-")] = value

    def geturl(self):
        return getattr(self, "response_url", URL)


def respond(monkeypatch, *responses):
    calls = []
    pending = iter(responses)

    def open_request(req, timeout):
        calls.append(req)
        item = next(pending)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(net, "urlopen", open_request)
    return calls


def partial(monkeypatch, dest, etag='"v1"', **kwargs):
    respond(monkeypatch, Response(b"abc", Content_Length="6", ETag=etag))
    with pytest.raises(net.VerificationError, match="Truncated"):
        net.download(URL, dest, size=6, hashes=HASHES, **kwargs)
    assert dest.with_name(dest.name + ".part").read_bytes() == b"abc"


def test_atomic_verified_download_and_multi_hash_single_pass(tmp_path, monkeypatch):
    dest = tmp_path / "rom.zip"
    hashes = dict(HASHES, md5=hashlib.md5(BODY).hexdigest())
    progress, phases = [], []
    calls = respond(monkeypatch, Response(Content_Length="6", ETag='"v1"'))
    result = net.download(URL, dest, size=6, hashes=hashes, progress=lambda d, t: progress.append((d, t)), phase=phases.append)
    assert result == dest and dest.read_bytes() == BODY
    assert progress == [(0, 6), (6, 6)] and phases == ["downloading", "verifying"]
    assert calls[0].get_header("Accept-encoding") == "identity"
    assert not list(tmp_path.glob("*.part*"))


def test_matching_etag_and_range_resume(tmp_path, monkeypatch):
    dest = tmp_path / "rom.zip"
    partial(monkeypatch, dest, headers={"Authorization": "private-test-token"})
    assert "private-test-token" not in dest.with_name("rom.zip.part.json").read_text()
    calls = respond(monkeypatch, Response(b"def", 206, Content_Range="bytes 3-5/6", Content_Length="3", ETag='"v1"'))
    net.download(URL, dest, size=6, hashes=HASHES, headers={"Authorization": "private-test-token"})
    assert calls[0].get_header("Range") == "bytes=3-" and calls[0].get_header("If-range") == '"v1"'
    assert dest.read_bytes() == BODY


@pytest.mark.parametrize("headers", [
    {"Content_Range": "bytes 0-2/6", "ETag": '"v1"'},
    {"Content_Range": "bytes 3-4/6", "ETag": '"v1"'},
    {"Content_Range": "bytes 3-5/*", "ETag": '"v1"'},
    {"Content_Range": "bytes 3-5/6", "ETag": '"changed"'},
    {"Content_Range": "bytes 3-5/6"},
    {"Content_Range": "bytes 3-5/6", "Content_Length": "4", "ETag": '"v1"'},
])
def test_bad_range_never_appended(tmp_path, monkeypatch, headers):
    dest = tmp_path / "rom.zip"
    partial(monkeypatch, dest)
    respond(monkeypatch, Response(b"def", 206, **headers))
    with pytest.raises(net.VerificationError):
        net.download(URL, dest, size=6, hashes=HASHES)
    assert not dest.exists() and dest.with_name("rom.zip.part").read_bytes() == b"abc"


@pytest.mark.parametrize("etag", ["", 'W/"v1"'])
def test_no_strong_validator_restarts(tmp_path, monkeypatch, etag):
    dest = tmp_path / "rom.zip"
    partial(monkeypatch, dest, etag)
    calls = respond(monkeypatch, Response(Content_Length="6"))
    net.download(URL, dest, size=6, hashes=HASHES)
    assert not calls[0].has_header("Range") and dest.read_bytes() == BODY


def test_redirected_resource_change_cannot_reuse_same_etag(tmp_path, monkeypatch):
    dest = tmp_path / "rom.zip"
    partial(monkeypatch, dest)
    response = Response(b"def", 206, Content_Range="bytes 3-5/6", ETag='"v1"')
    response.response_url = "https://different.example.org/rom.zip"
    respond(monkeypatch, response)
    with pytest.raises(net.VerificationError, match="range"):
        net.download(URL, dest, size=6, hashes=HASHES)
    assert not dest.exists() and dest.with_name("rom.zip.part").read_bytes() == b"abc"


def test_old_partial_and_changed_metadata_restart(tmp_path, monkeypatch):
    dest = tmp_path / "rom.zip"
    dest.with_name("rom.zip.part").write_bytes(b"old bytes")
    calls = respond(monkeypatch, Response(Content_Length="6"))
    net.download(URL, dest, size=6, hashes=HASHES)
    assert not calls[0].has_header("Range")
    partial(monkeypatch, dest)
    calls = respond(monkeypatch, Response(Content_Length="6"))
    net.download(URL, dest, size=6, hashes=dict(HASHES, sha1=hashlib.sha1(BODY).hexdigest()))
    assert not calls[0].has_header("Range") and dest.read_bytes() == BODY


def test_ignored_range_and_416_restart_without_appending(tmp_path, monkeypatch):
    dest = tmp_path / "rom.zip"
    partial(monkeypatch, dest)
    respond(monkeypatch, Response(Content_Length="6", ETag='"v2"'))
    net.download(URL, dest, size=6, hashes=HASHES)
    assert dest.read_bytes() == BODY
    partial(monkeypatch, dest)
    calls = respond(monkeypatch, urllib.error.HTTPError(URL, 416, "range", {}, None), Response(Content_Length="6"))
    net.download(URL, dest, size=6, hashes=HASHES)
    assert len(calls) == 2 and not calls[1].has_header("Range") and dest.read_bytes() == BODY


@pytest.mark.parametrize("response", [
    lambda: Response(b"abc", Content_Length="6"),
    lambda: Response(Content_Length="5"),
    lambda: Response(Content_Length="bad"),
    lambda: Response(Content_Encoding="gzip"),
    lambda: Response(status=206, Content_Range="bytes 0-5/6"),
    lambda: Response(status=204),
    lambda: Response(b"abcdefg"),
])
def test_bad_responses_never_replace_existing_final(tmp_path, monkeypatch, response):
    dest = tmp_path / "rom.zip"
    dest.write_bytes(b"existing final")
    respond(monkeypatch, response())
    with pytest.raises(net.VerificationError):
        net.download(URL, dest, size=6, hashes=HASHES)
    assert dest.read_bytes() == b"existing final"


def test_bad_hash_cannot_resume_and_unverified_is_not_called_verified(tmp_path, monkeypatch):
    dest = tmp_path / "rom.zip"
    respond(monkeypatch, Response(b"xxxxxx", Content_Length="6", ETag='"v1"'))
    with pytest.raises(net.VerificationError, match="sha256 mismatch"):
        net.download(URL, dest, size=6, hashes=HASHES)
    assert not dest.exists() and not dest.with_name("rom.zip.part.json").exists()
    assert net.verification_label() == "Downloaded; no publisher checksum or expected size"
    assert net.verification_label(size=6) == "Size checked; no publisher checksum"
    assert "weak" in net.verification_label(hashes={"md5": "x"})


def test_cancellation_before_request_and_during_hash_does_not_promote(tmp_path, monkeypatch):
    dest = tmp_path / "rom.zip"
    calls = respond(monkeypatch, Response(Content_Length="6"))
    with pytest.raises(net.DownloadCancelled):
        net.download(URL, dest, cancelled=lambda: True)
    assert not calls and not dest.exists()
    cancelled = threading.Event()
    with pytest.raises(net.DownloadCancelled):
        net.download(URL, dest, size=6, hashes=HASHES, cancelled=cancelled.is_set,
                     phase=lambda p: cancelled.set() if p == "verifying" else None)
    assert not dest.exists() and dest.with_name("rom.zip.part").read_bytes() == BODY


def test_disk_budget_and_bad_integrity_inputs_fail_before_body(tmp_path, monkeypatch):
    dest = tmp_path / "rom.zip"
    respond(monkeypatch, Response(Content_Length="6"))
    from collections import namedtuple
    usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr(net.shutil, "disk_usage", lambda p: usage(10, 8, 2))
    with pytest.raises(net.VerificationError, match="disk space"):
        net.download(URL, dest, size=6)
    assert not dest.exists()
    calls = respond(monkeypatch)
    for kwargs in [{"size": -1}, {"size": "6"}, {"hashes": {"sha256": "bad"}}, {"hashes": {"bad": "x"}}]:
        with pytest.raises(net.VerificationError):
            net.download(URL, dest, **kwargs)
    assert not calls


@pytest.mark.parametrize("filename", ["../rom.zip", "/rom.zip", "C:\\rom.zip", "a/b.zip", "a\\b.zip", "CON.zip", "x. ", "a:b.zip", "x\n.zip"])
def test_remote_filename_cannot_escape_download_root(tmp_path, filename):
    with pytest.raises(net.VerificationError):
        net.download_destination(tmp_path, "phone", filename)


def test_https_required_and_redirect_downgrade_rejected_before_request(tmp_path):
    with pytest.raises(net.VerificationError):
        net.download("http://example.org/rom.zip", tmp_path / "rom.zip")
    handler = net._HTTPSRedirect()
    with pytest.raises(net.VerificationError, match="redirect"):
        handler.redirect_request(urllib.request.Request(URL), None, 302, "", {}, "http://example.org/rom.zip")


@pytest.fixture
def tls_server(monkeypatch, tmp_path):
    # Each test generates ephemeral TLS material; no private key is committed or published.
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = dt.datetime.now(dt.timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(days=1)).not_valid_after(now + dt.timedelta(days=2))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost"),
            x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256()))
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.server.requests.append(dict(self.headers))
            start = int(self.headers["Range"].split("=")[1].split("-")[0]) if self.headers.get("Range") else 0
            data = self.server.payload[start:]
            self.send_response(206 if start else 200)
            self.send_header("ETag", '"loopback-v1"')
            self.send_header("Content-Length", str(len(data)))
            if start:
                self.send_header("Content-Range", f"bytes {start}-{len(self.server.payload)-1}/{len(self.server.payload)}")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    server.payload = b"real TLS bytes" * 180000
    server.requests = []
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    client = ssl.create_default_context(cafile=str(cert_path))
    monkeypatch.setattr(net, "ssl_context", lambda: client)
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{server.server_port}/rom.zip", server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_actual_tls_cancel_resume_and_hash(tmp_path, tls_server):
    url, server = tls_server
    dest = tmp_path / "rom.zip"
    cancelled = threading.Event()
    hashes = {"sha256": hashlib.sha256(server.payload).hexdigest()}
    with pytest.raises(net.DownloadCancelled):
        net.download(url, dest, size=len(server.payload), hashes=hashes, cancelled=cancelled.is_set,
                     progress=lambda done, total: cancelled.set() if done else None)
    assert not dest.exists() and dest.with_name("rom.zip.part").stat().st_size == 1 << 20
    net.download(url, dest, size=len(server.payload), hashes=hashes)
    assert dest.read_bytes() == server.payload
    assert server.requests[-1]["Range"] == "bytes=1048576-" and server.requests[-1]["If-Range"] == '"loopback-v1"'


def test_actual_tls_untrusted_certificate_is_rejected(tmp_path, tls_server, monkeypatch):
    url, _server = tls_server
    monkeypatch.setattr(net, "ssl_context", ssl.create_default_context)
    with pytest.raises(urllib.error.URLError):
        net.download(url, tmp_path / "rom.zip")
    assert not (tmp_path / "rom.zip").exists()


@pytest.mark.parametrize("size,hashes,label", [
    (None, {}, "no publisher checksum or expected size"),
    (6, {}, "Size checked; no publisher checksum"),
    (6, HASHES, "Publisher checksum matched: sha256"),
])
def test_cli_reports_only_checks_actually_performed(tmp_path, monkeypatch, capsys, size, hashes, label):
    from types import SimpleNamespace
    from curseofdroid import cli
    from curseofdroid.catalog.base import Artifact, Build, Provider

    class Source(Provider):
        name = "Source"

        def builds(self, codename):
            return [Build(self.name, "rom", codename, "1", None, [Artifact("rom.zip", URL, size, hashes)])]

    monkeypatch.setenv("CURSEOFDROID_HOME", str(tmp_path))
    monkeypatch.setattr(cli, "_provider_names", lambda args: [Source])
    respond(monkeypatch, Response(Content_Length="6"))
    assert cli.cmd_download(SimpleNamespace(codename=["phone"])) == 0
    output = capsys.readouterr().out
    assert label in output and "Verified" not in output
    assert (tmp_path / "downloads" / "phone" / "rom.zip").read_bytes() == BODY
