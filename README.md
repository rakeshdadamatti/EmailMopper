# EmailMopper

Classifies Gmail messages with a local Ollama model and labels marketing, social, and supported payment transaction messages for review.

## Requirements

- Python 3.10+
- Gmail IMAP access and a Gmail App Password
- Ollama with the `mistral` model

## Install

From the project directory:

```powershell
python -m pip install -e .
ollama pull mistral
```

Start Ollama before running EmailMopper. Either open the Ollama desktop app or run this in a separate terminal:

```powershell
ollama serve
```

A virtual environment is recommended but optional:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

If `python` is not the desired interpreter, use `py` instead.

## Configure

Create a `.env` file in the project directory:

Note: You would require Gmail App Password

```text
GMAIL_USER=your-address@gmail.com
GMAIL_APP_PASSWORD=your-app-password
```

Edit `config.json` to set folders, the review label, batch size, whitelist, and `OLLAMA_MODEL`.

`mistral` is the default model. For faster CPU classification, install a smaller model such as `qwen2.5:1.5b` and set `OLLAMA_MODEL` to `qwen2.5:1.5b`:

```powershell
ollama pull qwen2.5:1.5b
```

Optional fallback for uncertain results:

```json
"USE_FALLBACK_MODEL": true,
"OLLAMA_FALLBACK_MODEL": "mistral"
```

The fallback runs only when the primary model returns `UNCLASSIFIED`.

## Run

Preview messages without applying labels:

```powershell
emailmopper triage --dry-run
```

A dry run records preview rows with `action=would_label` in `reports/email_report.csv`. Remove those rows after reviewing the preview with PowerShell:

```powershell
$rows = Import-Csv reports\email_report.csv | Where-Object { $_.action -ne "would_label" }
$rows | Export-Csv reports\email_report.csv -NoTypeInformation
```

This does not remove messages from Gmail or affect `labeled_emails.csv`.

Apply labels:

```powershell
emailmopper triage
```

If `emailmopper` is not on `PATH`, use:

```powershell
python -m emailmopper triage --dry-run
python -m emailmopper triage
```

To delete messages with the configured review label, preview first:

```powershell
emailmopper delete
```

Deletion requires the confirmation flag and typing `y` at the prompt:

```powershell
emailmopper delete --confirm-delete
```

Triage never deletes messages. Reports are written to the `reports/` directory with UTC timestamps. `email_report.csv` also records classifier reasons and fallback-model attempts.
PhonePe, Amazon Pay, Google Pay, and BHIM UPI transaction alerts are classified as `TRANSACTION` and labeled for review.

## Test

```powershell
python -m unittest discover -s tests -v
```
