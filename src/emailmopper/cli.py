import argparse

from .delete import LabelDeleter
from .settings import ConfigurationError, load_settings
from .triage import TriageRunner


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="EmailMopper - Gmail email triage and deletion tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    triage_parser = subparsers.add_parser("triage", help="Label-only Gmail email triage")
    triage_parser.add_argument("--dry-run", action="store_true", help="Preview without applying labels")
    triage_parser.add_argument("--batch-size", type=int, default=None, help="Maximum messages per folder; 0 means all")
    triage_parser.add_argument("--classifier-workers", type=int, default=None)
    triage_parser.add_argument("--fetch-chunk-size", type=int, default=None)
    triage_parser.add_argument("--quiet", action="store_true", help="Reduce progress output")
    triage_parser.add_argument("--stage-folder", type=str, default=None, help="Gmail label used as the staging/review folder")

    delete_parser = subparsers.add_parser("delete", help="Delete messages carrying the review label")
    delete_parser.add_argument("--confirm-delete", action="store_true")
    delete_parser.add_argument("--stage-folder", type=str, default=None, help="Gmail label used as the staging/review folder")

    args = parser.parse_args(argv)

    try:
        settings = load_settings()
        if args.stage_folder is not None:
            settings = settings.__class__(**{**settings.__dict__, "stage_folder": args.stage_folder})

        if args.command == "triage":
            if args.batch_size is not None:
                settings = settings.__class__(**{**settings.__dict__, "batch_size": args.batch_size})
            if args.classifier_workers is not None:
                settings = settings.__class__(**{**settings.__dict__, "classifier_workers": args.classifier_workers})
            if args.fetch_chunk_size is not None:
                settings = settings.__class__(**{**settings.__dict__, "fetch_chunk_size": args.fetch_chunk_size})
            if args.quiet:
                settings = settings.__class__(**{**settings.__dict__, "quiet_output": True})
            
            TriageRunner(settings, dry_run=args.dry_run).run()
            
        elif args.command == "delete":
            LabelDeleter(settings).run(confirm=args.confirm_delete)
            
        return 0
    except ConfigurationError as error:
        parser.error(str(error))
        return 2
