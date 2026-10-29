"""python -m scripts.import_methodology_vectors --init-db"""

import argparse
import json

from app.services.methodology_vectors import import_vectors


def main():
    """Embed changed public passages and atomically activate a complete corpus."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--init-db', action='store_true')
    args = parser.parse_args()
    try:
        result = import_vectors(init_db=args.init_db)
        print(json.dumps(result))
    except Exception as error:
        print('Methodology vector import failed:', type(error).__name__)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
