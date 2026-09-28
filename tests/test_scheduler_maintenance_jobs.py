from types import SimpleNamespace
from services import scheduler_service as module
from datetime import datetime, timezone
from apscheduler.schedulers.background import BackgroundScheduler


def test_cleanup_runs_immediately_and_reload_preserves_schedule(monkeypatch):
    scheduler = BackgroundScheduler()
    scheduler.start(paused=True)
    monkeypatch.setattr(module, 'scheduler', scheduler)
    try:
        before = datetime.now(timezone.utc)
        module.register_generated_images_cleanup()
        job = scheduler.get_job('generated_images_cleanup')
        assert before <= job.next_run_time <= datetime.now(timezone.utc)
        assert job.trigger.interval.total_seconds() == 3600
        assert job.max_instances == 1
        assert job.coalesce is True
        assert job.misfire_grace_time is None
        scheduled = job.next_run_time
        module.register_generated_images_cleanup()
        assert len(scheduler.get_jobs()) == 1
        assert scheduler.get_job(job.id).next_run_time == scheduled
    finally:
        scheduler.shutdown(wait=False)


def test_reload_only_removes_scan_jobs(monkeypatch):
    from services.settings_service import SettingsService
    ids = ['generated_images_cleanup', 'redis_cache_flush_job', 'gdrive_view_copy_cleanup_job',
           'scan_general_13', 'lazy_scan_covers_job']
    removed = []
    scheduler = SimpleNamespace(running=False, configure=lambda **kw: None,
        get_jobs=lambda: [SimpleNamespace(id=x) for x in ids], remove_job=removed.append)
    monkeypatch.setattr(module, 'scheduler', scheduler)
    monkeypatch.setattr(SettingsService, 'get', lambda *a: 'UTC')
    monkeypatch.setattr(module.database, 'get_db_path', lambda *a: '/nonexistent/disposable-db')
    module.SchedulerService.reload_all_jobs()
    assert removed == ['scan_general_13', 'lazy_scan_covers_job']
