import json

import pytest
import typer
from typer.testing import CliRunner

from changelog_forge import cli
from changelog_forge.collect.github import RepoNotFound

from .conftest import make_engine

runner = CliRunner()


def test_parse_audiences():
    assert cli.parse_audiences("dev,user") == ["user", "dev"]
    assert cli.parse_audiences(" dev ") == ["dev"]
    for bad in ("", "users", "user,admin"):
        with pytest.raises(typer.BadParameter):
            cli.parse_audiences(bad)


@pytest.fixture
def fake_engine(monkeypatch, settings, sample_range):
    engine = make_engine(settings, collected_range=sample_range)
    monkeypatch.setattr(cli, "engine_factory", lambda _settings: engine)
    return engine


def test_markdown_for_both_audiences_on_stdout(fake_engine):
    result = runner.invoke(cli.app, ["acme/widgets", "v1.0.0..v1.1.0", "-q"])
    assert result.exit_code == 0, result.output
    assert "## What's new in acme/widgets v1.1.0" in result.stdout
    assert "## acme/widgets v1.0.0...v1.1.0" in result.stdout
    assert "\n---\n" in result.stdout


def test_json_to_a_file_for_one_audience(fake_engine, tmp_path):
    out = tmp_path / "notes.json"
    result = runner.invoke(
        cli.app,
        ["acme/widgets", "v1.0.0...v1.1.0", "--audience", "dev", "--json", "--out", str(out)],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(out.read_text(encoding="utf-8"))
    assert list(data["outputs"]) == ["dev"]
    assert data["usage"]["calls"] == 2  # one map, one dev reduce
    assert "ledger:" in result.stderr


def test_compare_url_without_a_range(fake_engine):
    url = "https://github.com/acme/widgets/compare/v1.0.0...v1.1.0"
    assert runner.invoke(cli.app, [url, "-q", "-a", "user"]).exit_code == 0


def test_recorded_input_skips_github(monkeypatch, settings, sample_range, tmp_path):
    engine = make_engine(settings, github_error=RuntimeError("must not be called"))
    monkeypatch.setattr(cli, "engine_factory", lambda _settings: engine)
    snapshot = tmp_path / "input.json"
    snapshot.write_text(sample_range.model_dump_json(), encoding="utf-8")
    result = runner.invoke(cli.app, ["acme/widgets", "--input", str(snapshot), "-q"])
    assert result.exit_code == 0, result.output


def test_bad_arguments_and_github_errors_have_distinct_exit_codes(monkeypatch, settings):
    assert runner.invoke(cli.app, ["acme/widgets", "v1"]).exit_code == 2
    assert runner.invoke(cli.app, ["acme/widgets", "v1..v2", "--audience", "boss"]).exit_code == 2
    engine = make_engine(settings, github_error=RepoNotFound("acme/widgets was not found"))
    monkeypatch.setattr(cli, "engine_factory", lambda _settings: engine)
    result = runner.invoke(cli.app, ["acme/widgets", "v1..v2"])
    assert result.exit_code == 3
    assert "was not found" in result.stderr
