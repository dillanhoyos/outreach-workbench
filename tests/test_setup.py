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
    p.write_text('WORKBENCH_TOKEN=replace-with-a-random-token-of-at-least-24-characters\nVNC_PASSWORD=replace-me\nAPOLLO_API_KEY=fixture-existing\n')
    module.setup(tmp_path)
    assert 'replace-' not in p.read_text()
    assert 'APOLLO_API_KEY=fixture-existing' in p.read_text()
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
