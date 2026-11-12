"""Restore, data package and delete all while the data is shared through the cloud (core/cloud/admin.py): the cloud
takes the new data first, in one push; only then is the file on this computer replaced. Asked first, backed up first."""

import tempfile
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication

from dibekho.core import activity, backup
from dibekho.core.cloud import admin
from dibekho.core.cloud import sync as cloud_sync
from dibekho.core.cloud.client import CloudError
from dibekho.i18n import t
from dibekho.ui.common import ask, error


def replace_shared_data(ctx, parent, build, what: str) -> bool:
    """build(folder) -> path of the new database, made inside that temporary folder without touching the live file.
    what: the action as the user knows it (t('admin.what_*')). True when the shared data was replaced."""
    if not ask(parent, t("admin.confirm", what=what)):
        return False
    runner = getattr(ctx, "sync_runner", None)
    if runner is not None and runner.busy:
        error(parent, t("admin.busy"))
        return False
    on_cloud = False
    try:
        admin.check_ready(ctx.conn)
        pair = cloud_sync.session(ctx.cfg, timeout=30)
        if pair is None:
            error(parent, t("admin.need_cloud"))
            return False
        client, token = pair
        backup.named_backup(ctx.conn, ctx.ws, "truoc-thay-du-lieu-chung")
        with tempfile.TemporaryDirectory() as tmp:
            QGuiApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                new = build(Path(tmp))
                admin.replace_shared(ctx.conn, new, client, token, ctx.cfg.device_id)
                on_cloud = True
            finally:
                QGuiApplication.restoreOverrideCursor()
            activity.log("data", f"shared data replaced: {what}")
            ctx.close()
            try:
                backup.restore(ctx.ws, new)
            finally:
                ctx.reopen()
    except (admin.NotReady, CloudError) as exc:
        error(parent, str(exc))
        return False
    except Exception as exc:  # a broken package or backup: the cloud and this computer are unchanged
        activity.log("error", f"replacing shared data: {exc}")
        # once the cloud holds the new data, the next sync brings it here even if replacing the file failed
        error(parent, t("admin.local_failed" if on_cloud else "admin.failed", error=str(exc)))
        return on_cloud
    return True
