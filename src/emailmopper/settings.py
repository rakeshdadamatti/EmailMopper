from dataclasses import dataclass
import json
import os
from pathlib import Path

from dotenv import load_dotenv


class ConfigurationError(RuntimeError):
    """Raised when application configuration is invalid."""


def get_imap_server(server_name: str | None = None) -> str:
    value = (server_name or "gmail.com").strip().lower()
    value = value.replace("imap://", "").replace("http://", "").replace("https://", "").strip("/")
    if value in ("", "gmail", "gmail.com") or value.startswith("gmail"):
        return "imap.gmail.com"
    if value.startswith("imap."):
        return value
    if value.startswith("."):
        return f"imap{value}"
    return f"imap.{value}"


@dataclass(frozen=True)
class Settings:
    base_dir: Path
    email_account: str
    password: str
    target_folders: tuple[str, ...]
    stage_folder: str
    ollama_model: str
    use_fallback_model: bool
    ollama_fallback_model: str
    whitelist_companies: tuple[str, ...]
    batch_size: int
    classifier_workers: int
    fetch_chunk_size: int
    write_reports: bool
    quiet_output: bool
    email_report_file: Path
    labeled_emails_file: Path
    skipped_emails_file: Path
    imap_server: str

    def validate(self) -> None:
        if not self.email_account or not self.password:
            raise ConfigurationError("Set GMAIL_USER and GMAIL_APP_PASSWORD before running the application.")
        if self.batch_size < 0:
            raise ConfigurationError("BATCH_SIZE must be 0 or greater.")
        if self.classifier_workers < 1:
            raise ConfigurationError("CLASSIFIER_WORKERS must be at least 1.")
        if self.fetch_chunk_size < 1:
            raise ConfigurationError("FETCH_CHUNK_SIZE must be at least 1.")


def load_settings(config_file: str | Path | None = None) -> Settings:
    if config_file:
        path = Path(config_file).resolve()
        base_dir = path.parent
    else:
        base_dir = Path.cwd()
        path = base_dir / "config.json"
        if not path.exists():
            pkg_base_dir = Path(__file__).resolve().parent.parent.parent
            if (pkg_base_dir / "config.json").exists():
                base_dir = pkg_base_dir
                path = base_dir / "config.json"
                
    reports_dir = base_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    load_dotenv(base_dir / ".env")
    try:
        with path.open(encoding="utf-8") as config_handle:
            data = json.load(config_handle)
    except (OSError, json.JSONDecodeError) as error:
        raise ConfigurationError(f"Could not load configuration from {path}: {error}") from error

    return Settings(
        base_dir=base_dir,
        email_account=os.getenv("GMAIL_USER", "").strip(),
        password=os.getenv("GMAIL_APP_PASSWORD", "").strip(),
        target_folders=tuple(str(item) for item in data.get("TARGET_FOLDERS", ["INBOX"])),
        stage_folder=str(data.get("STAGE_FOLDER", "Review_To_Delete")),
        ollama_model=str(data.get("OLLAMA_MODEL", "mistral")),
        use_fallback_model=bool(data.get("USE_FALLBACK_MODEL", False)),
        ollama_fallback_model=str(data.get("OLLAMA_FALLBACK_MODEL", "mistral")),
        whitelist_companies=tuple(str(item).lower() for item in data.get("WHITELIST_COMPANIES", [])),
        batch_size=int(data.get("BATCH_SIZE", 0)),
        classifier_workers=int(data.get("CLASSIFIER_WORKERS", 1)),
        fetch_chunk_size=int(data.get("FETCH_CHUNK_SIZE", 50)),
        write_reports=bool(data.get("WRITE_REPORTS", True)),
        quiet_output=bool(data.get("QUIET_OUTPUT", False)),
        email_report_file=reports_dir / "email_report.csv",
        labeled_emails_file=reports_dir / "labeled_emails.csv",
        skipped_emails_file=reports_dir / "skipped_emails.csv",
        imap_server=get_imap_server(str(data.get("IMAP_SERVER", "imap.gmail.com"))),
    )
