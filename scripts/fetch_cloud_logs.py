"""Download every account's activity log from the cloud (core/cloud/logs.py, cloud/supabase/017), with the cloud
login saved on this computer: it must be maychinh (nobody else may read them). For the developer.

    python -X utf8 scripts/fetch_cloud_logs.py <folder>

Names are hidden before the apps send them, but keep the folder private anyway, never commit it."""

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
