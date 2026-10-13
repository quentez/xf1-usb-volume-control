"""Report new official XF1 firmware; never download or authorize an image."""
import argparse
from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess

from xf1_usb_volume.catalog import RELEASE
from xf1_usb_volume.storage import LATEST_URL, latest_official_version


SCHEDULE_START = date(2026, 10, 12)


def is_check_day(today):
    # A cron day-of-month */3 resets at month boundaries; this does not.
    return (today - SCHEDULE_START).days % 3 == 0


def version_key(version):
    # Compare numerically and refuse markup, mentions, or unexpected feed formats.
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]{1,8}(?:\.[0-9]{1,8}){3}", version):
        raise ValueError("Expected a firmware version with four numeric components")
    return tuple(int(part) for part in version.split("."))


def github_api(endpoint, *, payload=None, paginate=False):
    command = ["gh", "api", "--hostname", "github.com", endpoint]
    if paginate:
        command += ["--paginate", "--slurp"]
    if payload is not None:
        command += ["--method", "POST", "--input", "-"]
    result = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                            text=True, capture_output=True, check=True, timeout=120)
    return json.loads(result.stdout)


def check_firmware(repository, notify, *, dry_run=False):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Expected a GitHub repository in owner/name form")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", notify):
        raise ValueError("Expected a GitHub username to notify")
    latest = latest_official_version()
    if version_key(latest) <= version_key(RELEASE.version):
        return f"No newer firmware. Creative: {latest}; supported: {RELEASE.version}."

    title = f"New Creative XF1 firmware: {latest}"
    marker = f"<!-- xf1-firmware-version: {latest} -->"
    # List all pages and both states: closed reports must not produce new alerts.
    # The issues endpoint also includes pull requests, which are not reports.
    pages = github_api(f"repos/{repository}/issues?state=all&per_page=100", paginate=True)
    for page in pages:
        for issue in page:
            if "pull_request" not in issue and (
                marker in (issue.get("body") or "") or issue.get("title") == title
            ):
                return f"Firmware {latest} already reported: {issue['html_url']}"

    metadata_url = LATEST_URL.rsplit("/", 1)[0] + f"/{latest}/MF1730_metadata.json"
    body = (
        f"{marker}\n\n"
        f"@{notify} Creative's release feed lists a newer XF1 (MF1730) firmware.\n\n"
        f"- New official version: **{latest}**\n"
        f"- Currently supported version: **{RELEASE.version}**\n"
        f"- [Official release feed]({LATEST_URL})\n"
        f"- [Version metadata]({metadata_url})\n\n"
        "Review the new release, its integrity checks, and patch compatibility before "
        "updating the allowlist. This notification does not add support for the new "
        "version. No firmware was downloaded, patched, or flashed by this check.\n\n"
        "This monitor reports each version once, including when its issue is closed.\n"
    )
    if dry_run:
        return f"Would open issue: {title}\n\n{body}"
    issue = github_api(f"repos/{repository}/issues", payload={"title": title, "body": body})
    return f"Reported firmware {latest}: {issue['html_url']}"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--notify", required=True, help="GitHub username to mention in new issues")
    parser.add_argument("--dry-run", action="store_true", help="Read the feed/issues without creating an issue")
    args = parser.parse_args()
    if not args.repository:
        parser.error("--repository or GITHUB_REPOSITORY is required")
    if os.environ.get("GITHUB_EVENT_NAME") == "schedule" and not is_check_day(datetime.now(timezone.utc).date()):
        message = "Skipping: firmware checks run every third UTC day."
    else:
        message = check_firmware(args.repository, args.notify, dry_run=args.dry_run)
    print(message)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary).open("a", encoding="utf-8") as stream:
            stream.write(message + "\n")


if __name__ == "__main__":
    main()
