"""python -m scripts.import_reference_data --states WI WY --init-db"""

import argparse
from app.services.reference_import_service import import_reference_data


def main():
    """Parse import options and return a safe process exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--states', nargs='+', required=True)
    parser.add_argument('--init-db', action='store_true')
    parser.add_argument('--skip-coordinates', action='store_true')
    args = parser.parse_args()
    try:
        results = import_reference_data(args.states, args.init_db, args.skip_coordinates)
    except Exception as error:
        print('Reference import failed:', type(error).__name__)
        return 1
    for result in results:
        if result['status'] == 'failed':
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
