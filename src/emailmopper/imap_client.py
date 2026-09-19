import imaplib
import time


def get_email_ids(messages) -> list[bytes]:
    if isinstance(messages, bytes):
        return messages.split()
    return [item for group in (messages or []) if isinstance(group, bytes) for item in group.split()]


class GmailClient:
    def __init__(self, server: str, account: str, password: str, max_attempts: int = 3, retry_delay: float = 1.0):
        self.server = server
        self.account = account
        self.password = password
        self.max_attempts = max_attempts
        self.retry_delay = retry_delay
        self.mail = None
        self._selected_folder = None

    def connect(self) -> None:
        for attempt in range(self.max_attempts):
            try:
                self.mail = imaplib.IMAP4_SSL(self.server)
                self.mail.login(self.account, self.password)
                return
            except (imaplib.IMAP4.abort, OSError):
                self.mail = None
                if attempt == self.max_attempts - 1:
                    raise
                time.sleep(self.retry_delay * (2 ** attempt))

    def close(self) -> None:
        if self.mail is not None:
            try:
                try:
                    self.mail.logout()
                except (imaplib.IMAP4.abort, OSError):
                    pass
            finally:
                self.mail = None
                self._selected_folder = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def select(self, folder: str):
        response = self._execute(lambda: self.mail.select(f'"{folder}"'))
        if response[0] == "OK":
            self._selected_folder = folder
        return response

    def search(self, *criteria):
        return self._execute(lambda: self.mail.search(None, *criteria))

    def fetch_batch(self, email_ids: list[bytes]) -> dict[bytes, bytes]:
        if not email_ids:
            return {}
        status, response = self._execute(
            lambda: self.mail.fetch(b",".join(email_ids).decode("ascii"), "(RFC822)")
        )
        if status != "OK":
            return {}
        result = {}
        for item in response:
            if not isinstance(item, tuple) or len(item) < 2:
                continue
            metadata, raw_message = item[0], item[1]
            if isinstance(metadata, bytes) and isinstance(raw_message, bytes):
                result[metadata.split(maxsplit=1)[0]] = raw_message
        return result

    def apply_label(self, email_id: bytes, label: str) -> bool:
        status, _ = self._execute(lambda: self.mail.store(email_id, "+X-GM-LABELS", f'"{label}"'))
        return status == "OK"

    def search_folder(self, label: str) -> list[bytes]:
        status, messages = self.search("ALL")
        return get_email_ids(messages) if status == "OK" else []

    def mark_deleted(self, email_id: bytes) -> bool:
        status, _ = self._execute(lambda: self.mail.store(email_id, "+FLAGS", "\\Deleted"))
        return status == "OK"

    def expunge(self) -> None:
        self._execute(self.mail.expunge)

    def _execute(self, operation):
        for attempt in range(self.max_attempts):
            try:
                return operation()
            except (imaplib.IMAP4.abort, OSError):
                if attempt == self.max_attempts - 1:
                    raise
                selected_folder = self._selected_folder
                self.close()
                self._selected_folder = selected_folder
                time.sleep(self.retry_delay * (2 ** attempt))
                self.connect()
                if self._selected_folder is not None:
                    status, _ = self.mail.select(f'"{self._selected_folder}"')
                    if status != "OK":
                        raise imaplib.IMAP4.error(f"Could not re-select folder: {self._selected_folder}")
