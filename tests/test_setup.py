import importlib.util
from pathlib import Path
import pytest
from workbench.config import Settings

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('setup_script', ROOT / 'scripts/setup.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_setup_fresh_and_repeated_preserves_keys(tmp_path, capsys):
    (tmp_path / '.env.example').write_text((ROOT / '.env.example').read_text())
    module.setup(tmp_path)
    p = tmp_path / '.env'
    first = p.read_text()
    values = dict(line.split('=', 1) for line in first.splitlines() if line and not line.startswith('#'))
    assert len(values['WORKBENCH_TOKEN']) >= 24
    assert len(values['VNC_PASSWORD']) == 8
    assert 'TYPESAFE_API_KEY=' in first and 'BROWSER_ADVISOR=none' in first
    assert p.stat().st_mode & 0o777 == 0o600
    assert values['WORKBENCH_TOKEN'] not in capsys.readouterr().out
    p.write_text(first.replace('TYPESAFE_API_KEY=', 'TYPESAFE_API_KEY=fixture-user-key'))
    before = p.read_text()
    module.setup(tmp_path)
    assert p.read_text() == before
    assert 'fixture-user-key' not in capsys.readouterr().out


def test_setup_copied_template_and_legacy_placeholders(tmp_path):
    p = tmp_path / '.env'
    p.write_text('WORKBENCH_TOKEN=replace-with-a-random-token-of-at-least-24-characters\nVNC_PASSWORD=replace-me\nCUSTOM_SERVICE_KEY=fixture-existing\n')
    module.setup(tmp_path)
    assert 'replace-' not in p.read_text()
    assert 'CUSTOM_SERVICE_KEY=fixture-existing' in p.read_text()
    p.write_text((ROOT / '.env.example').read_text())
    module.setup(tmp_path)
    assert '\nWORKBENCH_TOKEN=\n' not in p.read_text()


def test_jev_configuration_requires_explicit_enable_and_key(monkeypatch):
    monkeypatch.setenv('WORKBENCH_TOKEN', 'x' * 32)
    monkeypatch.setenv('WORKBENCH_MODE', 'live')
    monkeypatch.setenv('BROWSER_ADVISOR', 'jev')
    monkeypatch.delenv('TYPESAFE_API_KEY', raising=False)
    with pytest.raises(ValueError, match='TYPESAFE_API_KEY'):
        Settings.from_env()
    monkeypatch.setenv('TYPESAFE_API_KEY', 'fixture-key')
    assert Settings.from_env().browser_advisor == 'jev'
    monkeypatch.setenv('BROWSER_ADVISOR', 'none')
    assert Settings.from_env().browser_advisor == 'none'


@pytest.mark.parametrize('assignment', ['WORKBENCH_TOKEN=short', 'WORKBENCH_TOKEN = short',
    'export WORKBENCH_TOKEN=short', 'WORKBENCH_TOKEN=short # a long comment is not part of the password',
    'WORKBENCH_TOKEN="short" # a long comment is not part of the password'])
def test_short_token_repaired_and_accepted_by_app(tmp_path, monkeypatch, assignment):
    p = tmp_path / '.env'
    p.write_text(assignment + '\nVNC_PASSWORD=keepview\nTYPESAFE_API_KEY=fixture-preserved\n')
    module.setup(tmp_path)
    content = p.read_text()
    token = next(line.split('=', 1)[1] for line in content.splitlines() if line.startswith('WORKBENCH_TOKEN='))
    assert 'VNC_PASSWORD=keepview' in content and 'TYPESAFE_API_KEY=fixture-preserved' in content
    monkeypatch.setenv('WORKBENCH_TOKEN', token)
    monkeypatch.setenv('WORKBENCH_MODE', 'demo')
    monkeypatch.setenv('BROWSER_ADVISOR', 'none')
    assert Settings.from_env().token == token


def test_explicit_reset_rotates_only_app_token(tmp_path, capsys):
    p = tmp_path / '.env'
    old = 'x' * 32
    p.write_text('WORKBENCH_TOKEN=' + old + '\nVNC_PASSWORD=keepview\nCUSTOM_SERVICE_KEY=fixture-existing\n')
    module.setup(tmp_path, reset_token=True)
    text = p.read_text()
    assert old not in text
    assert 'VNC_PASSWORD=keepview' in text and 'CUSTOM_SERVICE_KEY=fixture-existing' in text
    output = capsys.readouterr().out
    assert '--force-recreate' in output and 'fixture-existing' not in output
