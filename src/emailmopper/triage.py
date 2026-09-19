from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import email
import os
import sys
import threading

from .classifier import EmailClassifier
from .email_utils import decode_subject, extract_body
from .imap_client import GmailClient
from .reporting import ReportStore
from .settings import Settings


class TriageRunner:
    _COLORS = {
        "success": "\033[32m",
        "warning": "\033[33m",
        "error": "\033[31m",
        "reset": "\033[0m",
    }

    def __init__(self, settings: Settings, dry_run: bool = False):
        self.settings = settings
        self.dry_run = dry_run
        self.classifier = EmailClassifier(settings.ollama_model)
        fallback_model = getattr(settings, "ollama_fallback_model", "")
        self.fallback_classifier = (
            EmailClassifier(fallback_model)
            if getattr(settings, "use_fallback_model", False) and fallback_model and fallback_model != settings.ollama_model
            else None
        )
        self.quiet = settings.quiet_output
        self.use_colors = sys.stdout.isatty() and "NO_COLOR" not in os.environ
        self._classification_cache = {}
        self._classification_cache_lock = threading.Lock()

    def _message(self, text, color=None):
        text = f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {text}"
        color_code = self._COLORS.get(color, "")
        if color_code and self.use_colors:
            return f"{color_code}{text}{self._COLORS['reset']}"
        return text

    def run(self) -> None:
        self.settings.validate()
        print(self._message("Starting email triage", "info"))
        if self.dry_run:
            print(self._message("DRY RUN: labels will not be applied.", "warning"))

        with GmailClient(self.settings.imap_server, self.settings.email_account, self.settings.password) as mail:
            print(self._message("Connected to Gmail.", "success"))
            with ReportStore(
                self.settings.email_report_file,
                self.settings.labeled_emails_file,
                self.settings.skipped_emails_file,
                enabled=self.settings.write_reports,
            ) as reports:
                for folder in self.settings.target_folders:
                    self._run_folder(mail, reports, folder)
        print(self._message("Triage complete.", "success"))

    def _run_folder(self, mail: GmailClient, reports: ReportStore, folder: str) -> None:
        print(self._message(f"Scanning folder: {folder}", "info"))
        status, _ = mail.select(folder)
        if status != "OK":
            print(self._message(f"Could not open folder: {folder}", "error"))
            return
            
        status, messages = mail.search("ALL", "NOT", "X-GM-LABELS", f'"{self.settings.stage_folder}"')
        if status != "OK":
            print(self._message(f"Could not search folder: {folder}", "error"))
            return
            
        all_ids = self._limit_ids(self._get_ids(messages))
        print(self._message(f"Found {len(all_ids)} messages", "info"))
        total = len(all_ids)
        labeled = skipped = processed = 0
        with ThreadPoolExecutor(max_workers=self.settings.classifier_workers) as executor:
            chunks = [all_ids[start:start + self.settings.fetch_chunk_size] for start in range(0, len(all_ids), self.settings.fetch_chunk_size)]
            for start, chunk, raw_messages in self._prefetch_chunks(folder, chunks, total):
                if not self.quiet:
                    print(self._message(f"Fetched {len(raw_messages)}/{len(chunk)} messages; parsing chunk", "info"))
                records = []
                for email_id in chunk:
                    raw = raw_messages.get(email_id)
                    if raw is None:
                        records.append((email_id, None, None, "", True, False))
                        continue
                    message = email.message_from_bytes(raw)
                    subject = decode_subject(message["Subject"])
                    sender = decode_subject(message.get("From", "Unknown Sender"))
                    already_processed = reports.already_processed(folder, sender, subject)
                    whitelisted = any(company in sender.lower() for company in self.settings.whitelist_companies)
                    body = extract_body(message) if not already_processed and not whitelisted else ""
                    records.append((email_id, sender, subject, body, whitelisted, already_processed))

                eligible = [(record[0], record[1], record[2], record[3]) for record in records if record[1] and not record[4] and not record[5]]
                already_processed_count = sum(1 for record in records if record[5])
                whitelisted_count = sum(1 for record in records if record[4] and record[1] and not record[5])
                missing_count = len(records) - len(raw_messages)
                if not self.quiet:
                    print(self._message(
                        f"Chunk ready: {len(eligible)} to classify, "
                        f"{whitelisted_count} whitelisted, "
                        f"{already_processed_count} already reported, "
                        f"{missing_count} unavailable.", "info"))
                futures = {}
                if eligible:
                    if not self.quiet:
                        print(self._message(
                            f"Classifying {len(eligible)} messages with {self.settings.classifier_workers} workers...", "warning"
                        ), flush=True)
                    futures = {executor.submit(self._classify_record, record): record for record in eligible}

                classifications = {}
                for completed, future in enumerate(as_completed(futures), 1):
                    email_id = futures[future][0]
                    classified_email_id, result = future.result()
                    classifications[email_id] = (classified_email_id, result)
                    if not self.quiet and (completed == 1 or completed % 10 == 0 or completed == len(futures)):
                        print(self._message(
                            f"Classification progress: {completed}/{len(futures)} ready", "warning"
                        ))

                for email_id, sender, subject, _body, whitelisted, already_processed in records:
                    processed += 1
                    if sender is None or already_processed:
                        continue
                    if whitelisted:
                        reports.write_skipped(folder, sender, subject, "WHITELISTED", "skipped")
                        skipped += 1
                        continue

                    classified_email_id, (category, reason) = classifications[email_id]
                    if classified_email_id != email_id:
                        print(self._message(f"Classification ID mismatch for message {email_id!r}; skipping label.", "error"))
                        continue
                    action = "kept"
                    if category in {"MARKETING", "SOCIAL", "TRANSACTION"}:
                        if self.dry_run:
                            action = "would_label"
                        elif mail.apply_label(email_id, self.settings.stage_folder):
                            action = "labeled"
                            labeled += 1
                        else:
                            action = "label_failed"
                    else:
                        action = "skipped" if category == "CLEAN" else "classification_failed"
                        reports.write_skipped_email(folder, sender, subject)
                        skipped += 1
                    reports.write_result(folder, sender, subject, category, action, reason)
                    if action in {"labeled", "would_label"}:
                        if not self.quiet:
                            print(self._message(f"{action}: {subject[:60]} [{category}]", "success"))
                    elif action in {"label_failed", "classification_failed"}:
                        print(self._message(f"{action}: {subject[:60]} [{category}] - {reason}", "error"))
                    if not self.quiet and (processed == total or processed % 10 == 0):
                        self._progress(processed, total, labeled, skipped)
                if not self.quiet:
                    print(self._message(f"Chunk complete: {len(records)} messages handled.", "success"))
        print()

    def _prefetch_chunks(self, folder, chunks, total):
        if not chunks:
            return

        with GmailClient(self.settings.imap_server, self.settings.email_account, self.settings.password) as fetch_mail:
            status, _ = fetch_mail.select(folder)
            if status != "OK":
                print(self._message(f"Could not open fetch connection for folder: {folder}", "error"))
                return

            with ThreadPoolExecutor(max_workers=1) as fetch_executor:
                fetch_future = fetch_executor.submit(fetch_mail.fetch_batch, chunks[0])
                for chunk_index, chunk in enumerate(chunks):
                    start = chunk_index * self.settings.fetch_chunk_size
                    if not self.quiet:
                        print(self._message(
                            f"Fetching messages {start + 1}-{min(start + len(chunk), total)} of {total}...", "info"
                        ), flush=True)
                    raw_messages = fetch_future.result()
                    if chunk_index + 1 < len(chunks):
                        fetch_future = fetch_executor.submit(fetch_mail.fetch_batch, chunks[chunk_index + 1])
                    yield start, chunk, raw_messages

    def _limit_ids(self, email_ids):
        return email_ids[:self.settings.batch_size] if self.settings.batch_size else email_ids

    @staticmethod
    def _get_ids(messages):
        if isinstance(messages, bytes):
            return messages.split()
        return [item for group in (messages or []) if isinstance(group, bytes) for item in group.split()]

    def _classify_record(self, record):
        email_id, sender, subject, body = record
        cache_key = (sender, subject, body)
        with self._classification_cache_lock:
            result_future = self._classification_cache.get(cache_key)
            if result_future is None:
                result_future = Future()
                self._classification_cache[cache_key] = result_future
                classify = True
            else:
                classify = False

        if classify:
            try:
                result = self.classifier.classify(subject, sender, body)
                if result[0] == "UNCLASSIFIED" and self.fallback_classifier is not None:
                    fallback_result = self.fallback_classifier.classify(subject, sender, body)
                    primary_model = getattr(self.classifier, "model", "primary")
                    fallback_model = getattr(self.fallback_classifier, "model", "fallback")
                    result = (
                        fallback_result[0],
                        f"Fallback '{fallback_model}' after '{primary_model}': {fallback_result[1]}",
                    )
                result_future.set_result(result)
                if result[0] == "UNCLASSIFIED":
                    with self._classification_cache_lock:
                        if self._classification_cache.get(cache_key) is result_future:
                            del self._classification_cache[cache_key]
            except Exception as error:
                result_future.set_exception(error)

        return email_id, result_future.result()

    def _progress(self, current, total, labeled, skipped, classified=None, classify_total=None):
        progress = f"Progress: {current}/{total} processed | {labeled} labeled | {skipped} skipped"
        if classified is not None:
            progress += f" | classified {classified}/{classify_total}"
        print(self._message(progress, "info"), flush=True)
