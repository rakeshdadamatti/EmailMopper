import csv
import sys
import tempfile
from types import SimpleNamespace
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


class EmailTriageSafetyTests(unittest.TestCase):
    def test_decode_subject_handles_unknown_charset(self):
        from emailmopper.email_utils import decode_subject

        self.assertEqual(decode_subject("=?unknown-8bit?b?VGVzdA==?="), "Test")

    def test_payment_provider_transaction_is_classified_by_llm(self):
        from emailmopper.classifier import EmailClassifier
        import emailmopper.classifier

        original_generate = emailmopper.classifier.ollama.generate
        try:
            calls = []

            def fake_generate(**kwargs):
                calls.append(kwargs)
                return {"response": '{"category": "TRANSACTION", "reason": "Payment alert"}'}

            emailmopper.classifier.ollama.generate = fake_generate
            category, reason = EmailClassifier().classify(
                "Transaction successful",
                "alerts@phonepe.com",
                "Your PhonePe payment transaction was successful.",
            )
        finally:
            emailmopper.classifier.ollama.generate = original_generate

        self.assertEqual(category, "TRANSACTION")
        self.assertTrue(reason)
        self.assertEqual(len(calls), 1)

    def test_duplicate_classification_uses_cache(self):
        from emailmopper.triage import TriageRunner

        settings = SimpleNamespace(
            ollama_model="mistral",
            quiet_output=True,
        )
        runner = TriageRunner(settings)

        class FakeClassifier:
            def __init__(self):
                self.calls = 0

            def classify(self, subject, sender, body):
                self.calls += 1
                return "MARKETING", "cached test"

        runner.classifier = FakeClassifier()
        first = runner._classify_record((b"1", "sender@example.com", "Subject", "Body"))
        second = runner._classify_record((b"2", "sender@example.com", "Subject", "Body"))

        self.assertEqual(first[1], second[1])
        self.assertEqual(runner.classifier.calls, 1)

    def test_fallback_model_handles_unclassified_result(self):
        from emailmopper.triage import TriageRunner

        settings = SimpleNamespace(
            ollama_model="qwen2.5:1.5b",
            use_fallback_model=True,
            ollama_fallback_model="mistral",
            quiet_output=True,
        )
        runner = TriageRunner(settings)

        class PrimaryClassifier:
            def classify(self, subject, sender, body):
                return "UNCLASSIFIED", "uncertain"

        class FallbackClassifier:
            def classify(self, subject, sender, body):
                return "CLEAN", "fallback result"

        runner.classifier = PrimaryClassifier()
        runner.fallback_classifier = FallbackClassifier()

        _, result = runner._classify_record((b"1", "sender@example.com", "Subject", "Body"))

        self.assertEqual(result, ("CLEAN", "Fallback 'fallback' after 'primary': fallback result"))

    def test_unclassified_result_is_retried_instead_of_cached(self):
        from emailmopper.triage import TriageRunner

        settings = SimpleNamespace(
            ollama_model="mistral",
            use_fallback_model=False,
            ollama_fallback_model="",
            quiet_output=True,
        )
        runner = TriageRunner(settings)

        class RetryingClassifier:
            def __init__(self):
                self.calls = 0

            def classify(self, subject, sender, body):
                self.calls += 1
                if self.calls == 1:
                    return "UNCLASSIFIED", "temporary error"
                return "CLEAN", "retry succeeded"

        runner.classifier = RetryingClassifier()
        record = (b"1", "sender@example.com", "Subject", "Body")

        self.assertEqual(runner._classify_record(record)[1][0], "UNCLASSIFIED")
        self.assertEqual(runner._classify_record(record)[1][0], "CLEAN")
        self.assertEqual(runner.classifier.calls, 2)
    def test_invalid_classification_is_not_destructive(self):
        from emailmopper.classifier import EmailClassifier
        import emailmopper.classifier

        original_generate = emailmopper.classifier.ollama.generate
        try:
            emailmopper.classifier.ollama.generate = lambda **kwargs: {"response": '{"category": "UNKNOWN"}'}
            category, _ = EmailClassifier().classify("Subject", "sender@example.com", "body")
        finally:
            emailmopper.classifier.ollama.generate = original_generate

        self.assertEqual(category, "UNCLASSIFIED")

    def test_email_ids_normalizes_bytes_search_response(self):
        from emailmopper.imap_client import get_email_ids

        self.assertEqual(get_email_ids(b"1 2 3"), [b"1", b"2", b"3"])

    def test_email_ids_normalizes_list_search_response(self):
        from emailmopper.imap_client import get_email_ids

        self.assertEqual(get_email_ids([b"1 2 3"]), [b"1", b"2", b"3"])

    def test_fetch_message_batch_maps_sequence_ids(self):
        from emailmopper.imap_client import GmailClient

        class FakeMail:
            def fetch(self, sequence_set, query):
                self.request = (sequence_set, query)
                return "OK", [(b"2 (RFC822 {4})", b"mail2"), (b"1 (RFC822 {4})", b"mail1")]

        mail = FakeMail()
        client = GmailClient("server", "account", "password")
        client.mail = mail
        self.assertEqual(client.fetch_batch([b"1", b"2"]), {b"1": b"mail1", b"2": b"mail2"})
        self.assertEqual(mail.request, ("1,2", "(RFC822)"))

    def test_close_ignores_reset_connection_during_logout(self):
        import imaplib
        from emailmopper.imap_client import GmailClient

        class FakeMail:
            def logout(self):
                raise imaplib.IMAP4.abort("socket error")

        client = GmailClient("server", "account", "password")
        client.mail = FakeMail()
        client.close()
        self.assertIsNone(client.mail)

    def test_fetch_reconnects_after_transient_connection_reset(self):
        import imaplib
        from emailmopper.imap_client import GmailClient

        class FailingMail:
            def fetch(self, sequence_set, query):
                raise imaplib.IMAP4.abort("connection reset")

            def logout(self):
                pass

        class ReconnectedMail:
            def fetch(self, sequence_set, query):
                return "OK", [(b"1 (RFC822 {4})", b"mail")]

            def logout(self):
                pass

        client = GmailClient("server", "account", "password", retry_delay=0)
        client.mail = FailingMail()
        connections = iter([ReconnectedMail()])
        client.connect = lambda: setattr(client, "mail", next(connections))

        self.assertEqual(client.fetch_batch([b"1"]), {b"1": b"mail"})

    def test_retry_restores_selected_folder(self):
        import imaplib
        from emailmopper.imap_client import GmailClient

        class ReconnectedMail:
            def __init__(self):
                self.selected = []

            def select(self, folder):
                self.selected.append(folder)
                return "OK", [b"1"]

            def search(self, mailbox, criterion):
                if len(self.selected) < 2:
                    raise imaplib.IMAP4.abort("connection reset")
                return "OK", [b"1"]

            def logout(self):
                pass

        client = GmailClient("server", "account", "password", retry_delay=0)
        mail = ReconnectedMail()
        client.mail = mail
        client.select("INBOX")
        client.connect = lambda: setattr(client, "mail", mail)

        self.assertEqual(client.search("ALL"), ("OK", [b"1"]))
        self.assertEqual(mail.selected, ['"INBOX"', '"INBOX"'])

    def test_imap_server_default_is_valid_gmail_server(self):
        from emailmopper.settings import get_imap_server

        self.assertEqual(get_imap_server("gmail.com"), "imap.gmail.com")
        self.assertEqual(get_imap_server("imap.gmail.com"), "imap.gmail.com")

    def test_report_store_retries_incomplete_results_and_writes_labeled_list(self):
        from emailmopper.reporting import ReportStore

        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            report_file = base / "email_report.csv"
            labeled_file = base / "labeled_emails.csv"
            skipped_file = base / "skipped_emails.csv"
            with ReportStore(report_file, labeled_file, skipped_file) as reports:
                reports.write_result("INBOX", "sender@example.com", "Preview", "MARKETING", "would_label")
                reports.write_result("INBOX", "sender@example.com", "Labeled", "MARKETING", "labeled", "applied")

            with ReportStore(report_file, labeled_file, skipped_file) as reports:
                self.assertFalse(reports.already_processed("INBOX", "sender@example.com", "Preview"))
                self.assertTrue(reports.already_processed("INBOX", "sender@example.com", "Labeled"))

            with labeled_file.open(newline="", encoding="utf-8") as handle:
                labeled_rows = list(csv.DictReader(handle))
            self.assertEqual(len(labeled_rows), 1)
            self.assertEqual(labeled_rows[0]["subject"], "Labeled")
            self.assertTrue(labeled_rows[0]["timestamp"])

            with report_file.open(newline="", encoding="utf-8") as handle:
                report_rows = list(csv.DictReader(handle))
            self.assertEqual(report_rows[1]["reason"], "applied")


if __name__ == "__main__":
    unittest.main()
