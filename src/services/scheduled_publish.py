"""Scheduled-publish tick for unified posts (S47.0).

Publishes ``scheduled`` posts whose ``published_at`` has passed (→
``published`` + ``content.changed``). Mirrors the subscription plugin's
scheduler module; the TESTING guard lives in the plugin's on_enable.
"""
import logging

logger = logging.getLogger(__name__)


def run_scheduled_publish(app):
    """Periodic task: publish any due scheduled posts."""
    with app.app_context():
        from vbwd.extensions import db
        from plugins.cms.src.repositories.post_repository import PostRepository
        from plugins.cms.src.repositories.term_repository import TermRepository
        from plugins.cms.src.repositories.post_term_repository import (
            PostTermRepository,
        )
        from plugins.cms.src.services.post_service import PostService

        dispatcher = None
        container = getattr(app, "container", None)
        if container is not None:
            try:
                dispatcher = container.event_dispatcher()
            except Exception:
                dispatcher = None

        service = PostService(
            repo=PostRepository(db.session),
            term_repo=TermRepository(db.session),
            post_term_repo=PostTermRepository(db.session),
            event_dispatcher=dispatcher,
        )
        published = service.publish_due_scheduled()
        if published:
            logger.info(
                "[cms] Scheduled-publish tick published %d post(s)", len(published)
            )


def start_scheduled_publish_tick(app, interval_seconds=60):
    """Start the scheduled-publish background tick."""
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_scheduled_publish,
        "interval",
        seconds=interval_seconds,
        args=[app],
        id="cms_scheduled_publish",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("[cms] Scheduled-publish tick started (interval=%ds)", interval_seconds)
    return scheduler
