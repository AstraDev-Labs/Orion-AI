from datetime import datetime, timedelta

from orion.tools import reminders as mod


def test_readback_rejects_disabled_or_wrong_trigger(monkeypatch):
    xml = '<Task><Settings><Enabled>false</Enabled></Settings><Triggers><TimeTrigger><StartBoundary>2099-01-01T12:00:00</StartBoundary></TimeTrigger></Triggers></Task>'
    monkeypatch.setattr(mod, '_run', lambda cmd: (True, xml))
    assert not mod._verify_task('task', '2099-01-01T12:00:00')[0]
    monkeypatch.setattr(mod, '_run', lambda cmd: (True, xml.replace('false', 'true')))
    assert mod._verify_task('task', '2099-01-01T12:00:00')[0]
    assert not mod._verify_task('task', '2099-01-01T13:00:00')[0]


def test_create_needs_readback_not_just_exit_code(monkeypatch, tmp_path):
    monkeypatch.setattr(mod, '_SCRIPTS_DIR', tmp_path)
    monkeypatch.setattr(mod, '_save', lambda data: None)
    monkeypatch.setattr(mod, '_load', lambda: {})
    monkeypatch.setattr(mod, '_run', lambda cmd: (True, ''))
    when = datetime.now() + timedelta(days=1)
    result = mod.ReminderTool()._create(when.strftime('%Y-%m-%d'), '12:00', 'test')
    assert not result.success
    assert 'not a Windows Clock alarm' in result.content
    assert not result.metadata['verified']


def test_past_request_does_not_register_task(monkeypatch):
    monkeypatch.setattr(mod, '_run', lambda cmd: (_ for _ in ()).throw(AssertionError('must not execute')))
    assert not mod.ReminderTool()._create('2000-01-01', '12:00', 'test').success


def test_failed_cancel_preserves_record(monkeypatch):
    records = {'id': {'task_name': 'task', 'message': 'test'}}
    monkeypatch.setattr(mod, '_load', lambda: records)
    monkeypatch.setattr(mod, '_run', lambda cmd: (False, 'Access denied'))
    assert not mod.ReminderTool()._cancel('id').success
    assert 'id' in records
