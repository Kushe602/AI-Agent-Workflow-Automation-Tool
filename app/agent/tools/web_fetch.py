"""Fetch a public web page as plain text, with SSRF protections.

Guards against server-side request forgery: only http/https, no redirects, and the
host must resolve exclusively to public IP addresses (loopback, private, link-local
— including the cloud metadata address 169.254.169.254 — and reserved ranges are
refused). Responses are size- and length-capped.
"""
import asyncio
import ipaddress
import re
import socket
from urllib.parse import urlparse

import httpx

from app.agent.tools.base import Tool, ToolContext
from app.config import settings

_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_INLINE_WS_RE = re.compile(r"[ \t\r\f\v]+")
_BLANK_LINES_RE = re.compile(r"\n\s*\n+")
_ENTITIES = {
    "&nbsp;": " ",
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&#39;": "'",
    "&quot;": '"',
}


def _is_blocked_ip(ip_text: str) -> bool:
    ip = ipaddress.ip_address(ip_text)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


async def _check_host(host: str) -> None:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    addresses = {info[4][0] for info in infos}
    if not addresses:
        raise ValueError("could not resolve host")
    for address in addresses:
        if _is_blocked_ip(address):
            raise ValueError("refusing to fetch a private, loopback or link-local address")


def _html_to_text(html: str) -> str:
    text = _SCRIPT_STYLE_RE.sub(" ", html)
    text = _TAG_RE.sub(" ", text)
    for entity, char in _ENTITIES.items():
        text = text.replace(entity, char)
    text = _INLINE_WS_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


async def _run(tool_input: dict, ctx: ToolContext) -> str:
    url = str(tool_input.get("url", "")).strip()
    if not url:
        return "Error: no url provided."
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return "Error: only http and https URLs are allowed."
    if not parsed.hostname:
        return "Error: invalid URL (no host)."
    try:
        await _check_host(parsed.hostname)
    except ValueError as exc:
        return f"Error: {exc}"
    except socket.gaierror:
        return "Error: could not resolve host."

    try:
        async with (
            httpx.AsyncClient(
                timeout=settings.fetch_timeout_seconds, follow_redirects=False
            ) as client,
            client.stream("GET", url, headers={"User-Agent": "AgentFlow/1.0"}) as resp,
        ):
            if 300 <= resp.status_code < 400:
                location = resp.headers.get("location", "?")
                return (
                    f"HTTP {resp.status_code}: {url} redirects to {location}. "
                    "Redirects are not followed; re-request the target URL directly."
                )
            content_type = resp.headers.get("content-type", "")
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                chunks.append(chunk)
                total += len(chunk)
                if total >= settings.fetch_max_bytes:
                    break
    except httpx.HTTPError as exc:
        return f"Error: request failed ({exc.__class__.__name__})."

    raw = b"".join(chunks)
    body = raw.decode(resp.encoding or "utf-8", errors="replace")
    if "html" in content_type or (not content_type and "<html" in body.lower()):
        body = _html_to_text(body)
    else:
        body = body.strip()

    truncated = len(body) > settings.fetch_max_chars
    body = body[: settings.fetch_max_chars]
    header = f"HTTP {resp.status_code} — {url}"
    suffix = "\n\n... (truncated)" if truncated else ""
    return f"{header}\n\n{body}{suffix}"


web_fetch_tool = Tool(
    name="web_fetch",
    description=(
        "Fetch a public web page over http/https and return its text content. "
        "Private, loopback and link-local addresses are refused, and redirects are "
        "not followed."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Absolute http(s) URL of the page to fetch.",
            }
        },
        "required": ["url"],
    },
    handler=_run,
)
