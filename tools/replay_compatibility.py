"""Validate and replay one bounded compatibility ZIP without Home Assistant."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from custom_components.solar_inverter_bridge.core.compatibility import MAX_ARCHIVE, replay, validate_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    args = parser.parse_args()
    if args.archive.stat().st_size > MAX_ARCHIVE:
        parser.error("report_archive_too_large")
    try:
        result = replay(validate_package(args.archive.read_bytes()))
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
