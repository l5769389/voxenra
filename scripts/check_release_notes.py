"""Validate the short, bilingual summaries before publishing a GitHub Release."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from qt_dicom_viewer.core.release_notes import validate_release_notes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path', type=Path)
    args = parser.parse_args()
    errors = validate_release_notes(args.path.read_text(encoding='utf-8'))
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print('Release summaries: format validated (Chinese and English).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
