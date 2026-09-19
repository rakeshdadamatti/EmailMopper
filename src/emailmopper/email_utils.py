import re
from email.header import decode_header

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover
    BeautifulSoup = None


def decode_subject(value) -> str:
    parts = []
    for part, encoding in decode_header(value or ""):
        if isinstance(part, bytes):
            try:
                parts.append(part.decode(encoding or "utf-8", errors="ignore"))
            except LookupError:
                parts.append(part.decode("utf-8", errors="replace"))
        else:
            parts.append(str(part))
    return "".join(parts)


def clean_html(html_body: str) -> str:
    text = html_body or ""
    if BeautifulSoup is not None:
        try:
            return BeautifulSoup(text, "html.parser").get_text(separator=" ", strip=True)[:1000]
        except Exception:
            pass
    text = re.sub(r"<script.*?</script>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style.*?</style>", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:1000]


def extract_body(message) -> str:
    body = ""
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            decoded = payload.decode(errors="ignore")
            if content_type == "text/plain":
                body = decoded
                break
            if content_type == "text/html" and not body:
                body = clean_html(decoded)
    else:
        payload = message.get_payload(decode=True) or b""
        body = payload.decode(errors="ignore")
        if message.get_content_type() == "text/html":
            body = clean_html(body)
    return body[:800]
