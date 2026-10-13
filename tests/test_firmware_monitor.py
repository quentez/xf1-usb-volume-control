from datetime import date
import io
import json
import os
import subprocess
import unittest
from unittest.mock import Mock, patch

from scripts import check_firmware as monitor
from xf1_usb_volume.catalog import RELEASE


REPOSITORY = "example/xf1"
NEW_VERSION = "9.9.999999.9999"
ISSUE_URL = "https://github.com/example/xf1/issues/42"


class FirmwareMonitorTests(unittest.TestCase):
    def setUp(self):
        self.feed = patch.object(monitor, "latest_official_version", return_value=NEW_VERSION).start()
        self.api = patch.object(monitor, "github_api", side_effect=[[], {"html_url": ISSUE_URL}]).start()
        self.addCleanup(patch.stopall)

    def check(self, **kwargs):
        return monitor.check_firmware(REPOSITORY, "maintainer", **kwargs)

    def test_equal_or_older_firmware_does_not_open_an_issue(self):
        for version in (RELEASE.version, "0.0.0.0"):
            with self.subTest(version=version):
                self.feed.return_value = version
                self.assertIn("No newer firmware", self.check())
                self.api.assert_not_called()

    def test_version_comparison_is_numeric(self):
        self.assertGreater(monitor.version_key("1.10.0.0"), monitor.version_key("1.9.0.0"))

    def test_new_version_opens_issue_and_mentions_maintainer(self):
        self.assertIn(ISSUE_URL, self.check())
        self.api.assert_any_call(f"repos/{REPOSITORY}/issues?state=all&per_page=100", paginate=True)
        payload = self.api.call_args.kwargs["payload"]
        self.assertIn(NEW_VERSION, payload["title"])
        self.assertIn("@maintainer", payload["body"])
        self.assertIn(RELEASE.version, payload["body"])
        self.assertIn(monitor.LATEST_URL, payload["body"])
        self.assertIn(f"/{NEW_VERSION}/MF1730_metadata.json", payload["body"])
        self.assertIn("<!-- xf1-firmware-version:", payload["body"])

    def test_open_and_closed_reports_on_later_pages_prevent_duplicates(self):
        for state in ("open", "closed"):
            with self.subTest(state=state):
                self.api.reset_mock()
                self.api.side_effect = None
                self.api.return_value = [
                    [{"title": "Unrelated", "body": None}],
                    [{"title": "Renamed report", "state": state, "html_url": ISSUE_URL,
                      "body": f"<!-- xf1-firmware-version: {NEW_VERSION} -->"}],
                ]
                self.assertIn("already reported", self.check())
                self.assertEqual(self.api.call_count, 1)

    def test_title_still_matches_when_body_marker_is_removed(self):
        self.api.side_effect = None
        self.api.return_value = [[{"title": f"New Creative XF1 firmware: {NEW_VERSION}",
                                  "body": None, "html_url": ISSUE_URL}]]
        self.assertIn("already reported", self.check())
        self.assertEqual(self.api.call_count, 1)

    def test_pull_request_with_same_title_does_not_suppress_notification(self):
        self.api.side_effect = [
            [[{"title": f"New Creative XF1 firmware: {NEW_VERSION}", "pull_request": {}}]],
            {"html_url": ISSUE_URL},
        ]
        self.assertIn("Reported firmware", self.check())
        self.assertEqual(self.api.call_count, 2)

    def test_dry_run_previews_without_posting(self):
        self.assertIn("Would open issue", self.check(dry_run=True))
        self.assertEqual(self.api.call_count, 1)

    def test_malformed_version_does_not_reach_github(self):
        for value in (None, 123, "", "1.2.3", "9.9.9.9\n@someone", "@someone", "９.９.９.９"):
            with self.subTest(value=value):
                self.feed.return_value = value
                with self.assertRaises(ValueError):
                    self.check()
                self.api.assert_not_called()

    def test_feed_failure_does_not_create_issue(self):
        self.feed.side_effect = OSError("Feed unavailable")
        with self.assertRaises(OSError):
            self.check()
        self.api.assert_not_called()

    def test_issue_lookup_failure_does_not_create_issue(self):
        self.api.side_effect = subprocess.CalledProcessError(1, "gh")
        with self.assertRaises(subprocess.CalledProcessError):
            self.check()
        self.assertEqual(self.api.call_count, 1)

    def test_schedule_keeps_three_day_spacing_across_month_boundary(self):
        for day in (date(2026, 10, 12), date(2026, 10, 15), date(2026, 10, 30), date(2026, 11, 2)):
            self.assertTrue(monitor.is_check_day(day), day)
        for day in (date(2026, 10, 13), date(2026, 10, 14), date(2026, 10, 31), date(2026, 11, 1)):
            self.assertFalse(monitor.is_check_day(day), day)

    def test_scheduled_run_skips_feed_on_other_days_but_manual_run_checks(self):
        for event, expected_calls in (("schedule", 0), ("workflow_dispatch", 1)):
            with self.subTest(event=event), patch.dict(os.environ, {
                "GITHUB_EVENT_NAME": event, "GITHUB_REPOSITORY": REPOSITORY,
            }, clear=True), patch("sys.argv", ["check_firmware.py", "--notify", "maintainer"]), \
                    patch.object(monitor, "is_check_day", return_value=False), \
                    patch("sys.stdout", new_callable=io.StringIO):
                self.feed.return_value = RELEASE.version
                self.feed.reset_mock()
                monitor.main()
                self.assertEqual(self.feed.call_count, expected_calls)


class GitHubAPITests(unittest.TestCase):
    @patch.object(monitor.subprocess, "run")
    def test_github_requests_use_all_pages_and_json_stdin(self, run):
        run.return_value = Mock(stdout="[[], []]")
        self.assertEqual(monitor.github_api("repos/example/xf1/issues?state=all", paginate=True), [[], []])
        command = run.call_args.args[0]
        self.assertIn("--paginate", command)
        self.assertIn("--slurp", command)
        payload = {"title": "Version", "body": "first line\nsecond line"}
        run.return_value = Mock(stdout='{"html_url": "https://github.com/example/xf1/issues/42"}')
        monitor.github_api("repos/example/xf1/issues", payload=payload)
        self.assertEqual(json.loads(run.call_args.kwargs["input"]), payload)
        self.assertEqual(run.call_args.args[0][-4:], ["--method", "POST", "--input", "-"])


if __name__ == "__main__":
    unittest.main()
