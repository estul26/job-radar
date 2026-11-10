"""Read one LinkedIn job posting from its public page, the one LinkedIn shows people who aren't signed in.

No account, cookie or sign-in is involved, so nothing here can get a LinkedIn account restricted.
LinkedIn's terms still forbid automated access to its pages, so `radar linkedin-describe` (the
only caller) is opt-in and reads a few postings per run, slowly, from your own computer.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup
from bs4.element import Comment, NavigableString, Tag

GUEST_URL = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)
# LinkedIn answers 429 or 999 when it wants automated readers to stop.
BLOCKED_STATUSES = {401, 403, 429, 999}
GONE_STATUSES = {404, 410}
_SIGN_IN_PATH = re.compile(r"^/(?:authwall|login|checkpoint|uas)\b", re.IGNORECASE)
_BLOCK_TAGS = {"p", "div", "ul", "ol", "section", "h1", "h2", "h3", "h4", "h5", "h6", "table", "tr"}


class GuestError(RuntimeError):
    """This posting could not be read; the next one may be fine."""


class PostingGone(GuestError):
    """LinkedIn no longer shows this posting to the public."""


class GuestBlocked(GuestError):
    """LinkedIn is refusing or rate-limiting public reads: stop the whole run."""


def http_get(url: str, timeout: float = 20) -> tuple[int, str, str]:
    """(status, final URL, body) of a plain GET with no cookies."""
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"})
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - a fixed https URL
            return response.status, response.geturl(), response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        return exc.code, exc.geturl() or url, ""
    except (URLError, TimeoutError, OSError) as exc:
        raise GuestError(f"network error: {exc}") from exc


def fetch_posting(job_id: str, *, get: Callable[[str], tuple[int, str, str]] = http_get) -> dict[str, str]:
    """The posting's title, company, location and description; raises a GuestError when it can't be read."""
    status, final_url, body = get(GUEST_URL.format(job_id=job_id))
    if status in GONE_STATUSES:
        raise PostingGone("LinkedIn no longer shows this posting")
    if status in BLOCKED_STATUSES or _SIGN_IN_PATH.search(urlparse(final_url).path):
        raise GuestBlocked(f"LinkedIn refused the request (HTTP {status})")
    if status != 200:
        raise GuestError(f"HTTP {status}")
    posting = parse_posting(body)
    if not posting["description"]:
        raise GuestError("the page had no job description")
    return posting


def _has_class(*wanted: str) -> Callable[[Any], bool]:
    """Match a tag whose class list has every wanted class (BeautifulSoup hands over the class string)."""

    def check(value: Any) -> bool:
        return bool(value) and set(wanted) <= set(str(value).split())

    return check


def _one_line(node: Tag | None) -> str:
    return " ".join(node.get_text(" ", strip=True).split()) if node else ""


def html_to_text(node: Tag) -> str:
    """The description as plain text: paragraphs apart, list items as "- " lines."""
    parts: list[str] = []

    def walk(parent: Tag) -> None:
        for child in parent.children:
            if isinstance(child, Comment):
                continue
            if isinstance(child, NavigableString):
                parts.append(re.sub(r"\s+", " ", str(child)))
            elif not isinstance(child, Tag):
                continue
            elif child.name == "br":
                parts.append("\n")
            elif child.name == "li":
                parts.append("\n- ")
                walk(child)
                parts.append("\n")
            elif child.name in _BLOCK_TAGS:
                parts.append("\n\n")
                walk(child)
                parts.append("\n\n")
            else:
                walk(child)

    walk(node)
    lines: list[str] = []
    for raw in "".join(parts).split("\n"):
        line = raw.strip()
        if line in {"-", ""}:
            line = ""
        elif line.startswith("#"):
            # A "###" line could be read as one of the Issue's own field headings.
            line = line.lstrip("# ").strip()
        if line or (lines and lines[-1]):
            lines.append(line)
    # List items stay together: no blank line between two "- " lines.
    kept = [
        line
        for index, line in enumerate(lines)
        if line or not (lines[index - 1].startswith("- ") and "".join(lines[index + 1 : index + 2]).startswith("- "))
    ]
    return "\n".join(kept).strip()


def parse_posting(html: str) -> dict[str, str]:
    """What the public posting page says; any field it lacks is ""."""
    soup = BeautifulSoup(html or "", "html.parser")
    description = soup.find(class_=_has_class("show-more-less-html__markup")) or soup.find(
        class_=_has_class("description__text")
    )
    return {
        "title": _one_line(soup.find(class_=_has_class("topcard__title"))),
        "company": _one_line(soup.find(class_=_has_class("topcard__org-name-link"))),
        # The applicant count shares the "bullet" class; only the location is a plain flavor.
        "location": _one_line(soup.find(class_=_has_class("topcard__flavor", "topcard__flavor--bullet"))),
        "description": html_to_text(description) if isinstance(description, Tag) else "",
    }
