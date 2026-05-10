from celery import Celery
from celery.schedules import crontab

from apps.workers.queues import build_send_task_router
from libs.core.config import get_settings

settings = get_settings()
send_task_router = build_send_task_router()

celery_app = Celery(
    "dispatch",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_create_missing_queues=True,
    task_routes=(send_task_router,),
    beat_schedule={
        "suppression-reconcile-with-ses": {
            "task": "suppression.reconcile_with_ses",
            "schedule": 300.0,
        },
        "metrics-rollup-campaign": {
            "task": "metrics.rollup_campaign_metrics",
            "schedule": 60.0,
        },
        "metrics-rollup-domain": {
            "task": "metrics.rollup_domain_metrics",
            "schedule": 60.0,
        },
        "metrics-rollup-account": {
            "task": "metrics.rollup_account_metrics",
            "schedule": 60.0,
        },
        "circuit-breaker-evaluator": {
            "task": "circuit_breakers.evaluate",
            "schedule": 60.0,
        },
        "warmup-compute-daily-budgets": {
            "task": "warmup.compute_daily_budgets",
            "schedule": crontab(minute=0, hour=0),
        },
        "warmup-check-graduation": {
            "task": "warmup.check_graduation",
            "schedule": 86400.0,
        },
        "warmup-fetch-postmaster-metrics": {
            "task": "warmup.fetch_postmaster_metrics",
            "schedule": 86400.0,
        },
    },
    include=[
        "apps.workers.circuit_breaker_tasks",
        "apps.workers.domain_tasks",
        "apps.workers.event_tasks",
        "apps.workers.import_tasks",
        "apps.workers.metrics_tasks",
        "apps.workers.send_tasks",
        "apps.workers.warmup_tasks",
    ],
)
