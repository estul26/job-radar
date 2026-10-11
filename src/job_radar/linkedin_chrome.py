"""Read LinkedIn job-search pages in your own signed-in Google Chrome, on a Mac.

AppleScript opens a temporary Chrome window, loads each page and reads it with
JavaScript, which needs Chrome's View > Developer > Allow JavaScript from Apple
Events. It only reads pages: it never applies, saves, messages or follows.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse

CREATE_WINDOW = r"""
on run argv
  tell application "Google Chrome"
    activate
    set searchWindow to make new window
    set URL of active tab of searchWindow to "about:blank"
    return (id of searchWindow) as text
  end tell
end run
"""

RUN_IN_TAB = r"""
on run argv
  set windowId to (item 1 of argv) as integer
  set targetUrl to item 2 of argv
  set javascriptCode to item 3 of argv
  set waitTenths to (item 4 of argv) as integer

  tell application "Google Chrome"
    set searchWindow to first window whose id is windowId
    set URL of active tab of searchWindow to targetUrl
  end tell

  repeat with attempt from 1 to 200
    tell application "Google Chrome"
      set searchWindow to first window whose id is windowId
      set pageIsLoading to loading of active tab of searchWindow
    end tell
    if pageIsLoading is false then exit repeat
    delay 0.2
  end repeat

  repeat waitTenths times
    delay 0.1
  end repeat

  tell application "Google Chrome"
    set searchWindow to first window whose id is windowId
    return execute active tab of searchWindow javascript javascriptCode
  end tell
end run
"""

EXECUTE_IN_TAB = r"""
on run argv
  set windowId to (item 1 of argv) as integer
  set javascriptCode to item 2 of argv
  tell application "Google Chrome"
    set searchWindow to first window whose id is windowId
    return execute active tab of searchWindow javascript javascriptCode
  end tell
end run
"""

CLOSE_WINDOW = r"""
on run argv
  set windowId to (item 1 of argv) as integer
  tell application "Google Chrome"
    try
      close (first window whose id is windowId)
    end try
  end tell
end run
"""

# The job cards on a LinkedIn search page, and whether you're signed in or being challenged.
# Company and location come from LinkedIn's card classes; when those change, a line that looks
# like a place (remote/hybrid/on-site, or "City, Region") is the location.
LINKEDIN_EXTRACT_JS = r"""
(() => {
  const clean = value => String(value || "").replace(/\s+/g, " ").trim();
  const selectors = {
    company: [
      ".job-card-container__primary-description",
      ".job-card-container__company-name",
      ".artdeco-entity-lockup__subtitle",
      "[class*='company-name']"
    ],
    location: [
      ".job-card-container__metadata-item",
      ".artdeco-entity-lockup__caption",
      "[class*='job-card-container__metadata']"
    ]
  };
  const firstText = (root, list) => {
    for (const selector of list) {
      const element = root.querySelector(selector);
      const value = clean(element && element.innerText);
      if (value) return value;
    }
    return "";
  };
  const placeLike = line => /\b(remote|hybrid|on-?site)\b/i.test(line)
    || (/,\s*[A-Za-z][A-Za-z .'-]+$/.test(line) && !/,\s*(inc|llc|ltd|corp|co|gmbh|plc)\.?$/i.test(line));
  const metaLike = line => /\b(posted|applicants?|ago|promoted|easy apply|viewed|alumni)\b/i.test(line);
  const jobMap = new Map();
  for (const anchor of document.querySelectorAll("a[href*='/jobs/view/'], a[href*='currentJobId=']")) {
    const directMatch = String(anchor.href || "").match(/\/jobs\/view\/(\d+)/);
    let jobId = directMatch?.[1] || "";
    if (!jobId) {
      try { jobId = new URL(anchor.href).searchParams.get("currentJobId") || ""; } catch (_) {}
    }
    if (!jobId || jobMap.has(jobId)) continue;
    const card = anchor.closest("li, [data-job-id], .job-card-container, .artdeco-entity-lockup") || anchor;
    const lines = String(card.innerText || "").split(/\n+/).map(clean).filter(Boolean);
    const titleElement = anchor.querySelector("strong, [class*='title'], p");
    let title = clean(titleElement?.innerText || anchor.getAttribute("aria-label") || lines[0]);
    title = title.replace(/^Job title:\s*/i, "").replace(/\s*\(Verified job\)\s*$/i, "");
    if (!title || /show all|see more/i.test(title)) continue;
    const detailLines = lines.filter(line => line !== title && line !== "•");
    const company = firstText(card, selectors.company)
      || detailLines.find(line => !placeLike(line) && !metaLike(line))
      || "";
    const location = firstText(card, selectors.location)
      || detailLines.find(line => placeLike(line) && !metaLike(line))
      || "";
    const timeElement = card.querySelector("time, [class*='time-ago']");
    const posted = clean(timeElement?.getAttribute("datetime") || timeElement?.innerText)
      || detailLines.find(line => /\b(posted|hour|day|week|month)s? ago\b/i.test(line))
      || "";
    jobMap.set(jobId, {
      title,
      company,
      location,
      posted,
      url: `https://www.linkedin.com/jobs/view/${jobId}/`,
      cardText: clean(card.innerText).slice(0, 3000)
    });
  }
  const bodyText = clean(document.body?.innerText).slice(0, 12000);
  return JSON.stringify({
    currentUrl: location.href,
    pageTitle: document.title,
    signedIn: Boolean(document.querySelector(
        "nav.global-nav, #global-nav, a[href*='/feed'], a[href*='/mynetwork'], "
        + "a[href*='/messaging'], a[href*='/notifications']"))
      && !/\/login|\/authwall|\/checkpoint/i.test(location.pathname),
    loginWall: /\/login|\/authwall|\/checkpoint/i.test(location.pathname)
      || /sign in to linkedin|join linkedin/i.test(bodyText),
    challenge: /security verification|let's do a quick security check|captcha/i.test(bodyText),
    jobs: Array.from(jobMap.values()),
    bodyText
  });
})()
"""

SCROLL_LINKEDIN_JS = r"""
(() => {
  const candidates = Array.from(document.querySelectorAll("div, ul"))
    .filter(element => element.scrollHeight > element.clientHeight + 200);
  const list = document.querySelector(".jobs-search-results-list, .scaffold-layout__list")
    || candidates.sort((a, b) => b.scrollHeight - a.scrollHeight)[0];
  if (list) list.scrollTop = Math.min(list.scrollTop + Math.max(list.clientHeight, 600), list.scrollHeight);
  else window.scrollBy(0, 900);
  return "ok";
})()
"""


class ChromeControlError(RuntimeError):
    pass


def run_applescript(source: str, *args: Any, timeout: float = 75) -> str:
    try:
        result = subprocess.run(
            ["osascript", "-", *[str(arg) for arg in args]],
            input=source,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise ChromeControlError("Chrome did not respond before the timeout.") from exc
    except OSError as exc:
        raise ChromeControlError(f"Could not run osascript: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        if "javascript from apple events" in detail.lower() or "javascript through apple events" in detail.lower():
            raise ChromeControlError(
                "Chrome blocked page reading. Turn on View > Developer > Allow JavaScript from Apple Events, "
                "then run this again (and turn it off afterwards)."
            )
        if "not authorized" in detail.lower() or "not allowed assistive access" in detail.lower() or "-1743" in detail:
            raise ChromeControlError(
                "macOS blocked browser control. In System Settings > Privacy & Security > Automation, "
                "allow your terminal app to control Google Chrome."
            )
        raise ChromeControlError(f"Chrome automation failed: {detail or 'unknown AppleScript error'}")
    return result.stdout.rstrip("\n")


class Chrome:
    """A temporary Chrome window driven through AppleScript."""

    def __init__(self, runner: Callable[..., str] = run_applescript) -> None:
        self._run = runner

    def open_window(self) -> str:
        window = self._run(CREATE_WINDOW).strip()
        if not window.isdigit():
            raise ChromeControlError("Chrome did not provide a usable temporary window.")
        return window

    def load(self, window: str, url: str, javascript: str, wait_seconds: float = 3.0) -> dict[str, Any]:
        """Open the URL, wait for it to load, and return what the JavaScript reports."""
        return self._json(self._run(RUN_IN_TAB, window, url, javascript, max(0, round(wait_seconds * 10))))

    def execute(self, window: str, javascript: str) -> dict[str, Any]:
        return self._json(self._run(EXECUTE_IN_TAB, window, javascript))

    def scroll(self, window: str) -> None:
        self._run(EXECUTE_IN_TAB, window, SCROLL_LINKEDIN_JS)

    def close(self, window: str) -> None:
        try:
            self._run(CLOSE_WINDOW, window, timeout=15)
        except ChromeControlError:
            pass

    @staticmethod
    def _json(raw: str) -> dict[str, Any]:
        try:
            data = json.loads(raw or "{}")
        except json.JSONDecodeError as exc:
            raise ChromeControlError(
                "Chrome returned unreadable page data. Check that Allow JavaScript from Apple Events is on."
            ) from exc
        return data if isinstance(data, dict) else {}


def canonical_url(value: str) -> str:
    """One URL per job: LinkedIn job links become https://www.linkedin.com/jobs/view/<id>/."""
    value = " ".join(str(value or "").split())
    if not value:
        return ""
    parsed = urlparse(value)
    if parsed.netloc.endswith("google.com") and parsed.path == "/url":
        target = parse_qs(parsed.query).get("q") or parse_qs(parsed.query).get("url")
        if target:
            value = unquote(target[0])
            parsed = urlparse(value)
    linkedin_match = re.search(r"linkedin\.com/jobs/view/(\d+)", value)
    if linkedin_match:
        return f"https://www.linkedin.com/jobs/view/{linkedin_match.group(1)}/"
    host = parsed.netloc.lower().removeprefix("www.")
    if not parsed.scheme or not host:
        return ""
    path = re.sub(r"/{2,}", "/", parsed.path).rstrip("/") or "/"
    return urlunparse((parsed.scheme.lower(), host, path, "", "", ""))


def search_url(keywords: str, location: str, *, remote: bool, posted_hours: int) -> str:
    """A LinkedIn job search, newest first, for postings at most posted_hours old."""
    params = {
        "keywords": keywords,
        "location": location,
        **({"f_WT": "2"} if remote else {}),
        "f_TPR": f"r{posted_hours * 3600}",
        "sortBy": "DD",
    }
    return "https://www.linkedin.com/jobs/search/?" + urlencode(params)
