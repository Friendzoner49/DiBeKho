"""Download every main machine's activity log from the cloud (core/cloud/logs.py), with the cloud login saved on this
computer (Cài đặt → Cloud). For the developer, to see what happened on a customer's machine.

    python -X utf8 scripts/fetch_cloud_logs.py <folder>

The logs hold customer and file names: keep the folder private, never commit it."""

import sys
from pathlib import Path

from dibekho.core.cloud import logs
from dibekho.core.cloud import sync as cloud_sync
from dibekho.core.workspace import Config


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    cfg = Config.load()
    pair = cloud_sync.session(cfg, timeout=30) if cfg else None
    if pair is None:
        sys.exit("Máy này chưa đăng nhập Cloud (Cài đặt → Cloud).")
    client, token = pair
    for path in logs.fetch_logs(client, token, Path(sys.argv[1])):
        print(path)


if __name__ == "__main__":
    main()
