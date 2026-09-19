from .imap_client import GmailClient
from .settings import Settings


class LabelDeleter:
    def __init__(self, settings: Settings):
        self.settings = settings

    def run(self, confirm: bool = False) -> None:
        self.settings.validate()
        with GmailClient(self.settings.imap_server, self.settings.email_account, self.settings.password) as mail:
            status, _ = mail.select(self.settings.stage_folder)
            if status != "OK":
                print(f"Label not found: {self.settings.stage_folder}")
                return
            email_ids = mail.search_folder(self.settings.stage_folder)
            if not email_ids:
                print(f"No emails found in '{self.settings.stage_folder}'.")
                return
            count = len(email_ids)
            print(f"Found {count} emails in '{self.settings.stage_folder}'.")
            if not confirm:
                print("Preview only. Re-run with --confirm-delete to permanently delete them.")
                return
            answer = input(f"Permanently delete {count} emails from '{self.settings.stage_folder}'? [y/N]: ").strip().lower()
            if answer != "y":
                print("Aborted. No emails were deleted.")
                return
            deleted = sum(mail.mark_deleted(email_id) for email_id in email_ids)
            mail.expunge()
            print(f"Permanently deleted {deleted} emails.")
