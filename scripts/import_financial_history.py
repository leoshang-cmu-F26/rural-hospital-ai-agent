"""Run with python -m scripts.import_financial_history; secrets remain in .env."""

import argparse
from app.services.financial_import_service import run_import


def main():
    """Parse import options and return a safe process exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', required=True)
    parser.add_argument('--start-year', type=int)
    parser.add_argument('--end-year', type=int)
    parser.add_argument('--init-db', action='store_true')
    parser.add_argument('--check-updates', action='store_true')
    parser.add_argument('--refresh', action='store_true')
    args = parser.parse_args()
    try:
        results = run_import(
            args.state,
            args.start_year,
            args.end_year,
            args.init_db,
            args.check_updates,
            args.refresh,
        )
    except Exception as error:
        print('Import job failed:', type(error).__name__)
        return 1
    for result in results:
        if result['status'] in ('failed', 'source_not_published'):
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
