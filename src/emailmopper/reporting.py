import csv
import os
from datetime import datetime, timezone
from pathlib import Path


class ReportStore:
    _INCOMPLETE_ACTIONS = {"classification_failed", "label_failed", "would_label"}
    _TIMESTAMP_FIELD = "timestamp"

    def __init__(self, report_file: Path, labeled_file: Path, skipped_file: Path, enabled: bool = True):
        self.report_file = report_file
        self.labeled_file = labeled_file
        self.skipped_file = skipped_file
        self.enabled = enabled
        self.processed_keys = self._load_keys()
        self._report_handle = None
        self._labeled_handle = None
        self._skipped_handle = None
        self.report_writer = None
        self.labeled_writer = None
        self.skipped_writer = None

    def _load_keys(self):
        keys = set()
        for path in (self.report_file, self.labeled_file, self.skipped_file):
            if not path.exists():
                continue
            try:
                with path.open(newline="", encoding="utf-8") as handle:
                    for row in csv.DictReader(handle):
                        if row.get("action", "") not in self._INCOMPLETE_ACTIONS:
                            keys.add((row.get("folder", ""), row.get("sender", ""), row.get("subject", "")))
            except (OSError, csv.Error):
                continue
        return keys

    def __enter__(self):
        if not self.enabled:
            return self
        self._ensure_report_columns()
        self._report_handle = self.report_file.open("a+", newline="", encoding="utf-8")
        self._labeled_handle = self.labeled_file.open("a+", newline="", encoding="utf-8")
        self._skipped_handle = self.skipped_file.open("a+", newline="", encoding="utf-8")
        self._report_handle.seek(0, os.SEEK_END)
        self._labeled_handle.seek(0, os.SEEK_END)
        self._skipped_handle.seek(0, os.SEEK_END)
        self.report_writer = csv.DictWriter(self._report_handle, fieldnames=["folder", "sender", "subject", "category", "action", "reason", self._TIMESTAMP_FIELD])
        self.labeled_writer = csv.DictWriter(self._labeled_handle, fieldnames=["folder", "sender", "subject", "category", self._TIMESTAMP_FIELD])
        self.skipped_writer = csv.DictWriter(self._skipped_handle, fieldnames=["folder", "sender", "subject", self._TIMESTAMP_FIELD])
        if self._report_handle.tell() == 0:
            self.report_writer.writeheader()
        if self._labeled_handle.tell() == 0:
            self.labeled_writer.writeheader()
        if self._skipped_handle.tell() == 0:
            self.skipped_writer.writeheader()
        return self

    @classmethod
    def _timestamp(cls):
        return datetime.now(timezone.utc).isoformat(timespec="seconds")

    @classmethod
    def _ensure_columns(cls, path: Path, fieldnames: list[str]) -> None:
        if not path.exists() or path.stat().st_size == 0:
            return
        with path.open(newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames or all(field in reader.fieldnames for field in fieldnames):
                return
            rows = list(reader)
        upgraded_fields = [*fieldnames, cls._TIMESTAMP_FIELD]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=upgraded_fields)
            writer.writeheader()
            for row in rows:
                for field in fieldnames:
                    row.setdefault(field, "")
                writer.writerow(row)

    def _ensure_report_columns(self) -> None:
        self._ensure_columns(self.report_file, ["folder", "sender", "subject", "category", "action", "reason", self._TIMESTAMP_FIELD])
        self._ensure_columns(self.labeled_file, ["folder", "sender", "subject", "category", self._TIMESTAMP_FIELD])
        self._ensure_columns(self.skipped_file, ["folder", "sender", "subject", self._TIMESTAMP_FIELD])

    def __exit__(self, exc_type, exc_value, traceback):
        if self._report_handle:
            self._report_handle.close()
        if self._labeled_handle:
            self._labeled_handle.close()
        if self._skipped_handle:
            self._skipped_handle.close()

    def already_processed(self, folder: str, sender: str, subject: str) -> bool:
        return (folder, sender, subject) in self.processed_keys

    def write_skipped(self, folder: str, sender: str, subject: str, category: str, action: str) -> None:
        key = (folder, sender, subject)
        if self.enabled:
            timestamp = self._timestamp()
            self.skipped_writer.writerow({"folder": folder, "sender": sender, "subject": subject, self._TIMESTAMP_FIELD: timestamp})
            self.report_writer.writerow({"folder": folder, "sender": sender, "subject": subject, "category": category, "action": action, "reason": "", self._TIMESTAMP_FIELD: timestamp})
        self.processed_keys.add(key)

    def write_skipped_email(self, folder: str, sender: str, subject: str) -> None:
        if self.enabled:
            self.skipped_writer.writerow({"folder": folder, "sender": sender, "subject": subject, self._TIMESTAMP_FIELD: self._timestamp()})

    def write_result(self, folder: str, sender: str, subject: str, category: str, action: str, reason: str = "") -> None:
        if self.enabled:
            timestamp = self._timestamp()
            self.report_writer.writerow({"folder": folder, "sender": sender, "subject": subject, "category": category, "action": action, "reason": reason, self._TIMESTAMP_FIELD: timestamp})
            if action == "labeled":
                self.labeled_writer.writerow({"folder": folder, "sender": sender, "subject": subject, "category": category, self._TIMESTAMP_FIELD: timestamp})
        if action not in self._INCOMPLETE_ACTIONS:
            self.processed_keys.add((folder, sender, subject))
