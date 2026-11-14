from __future__ import annotations

import pytest

from darkfluenzer import config


def test_load_resolves_relative_paths(project):
    cfg = config.load(project)
    assert cfg.comfyui.path == project / "local" / "fake_comfy"
    assert cfg.comfyui.url.startswith("http://127.0.0.1:")


def test_missing_config_is_explained(tmp_path):
    with pytest.raises(config.ConfigError, match="config.example.toml"):
        config.load(tmp_path)


@pytest.mark.parametrize(
    "override, message",
    [
        ({"host": "0.0.0.0"}, "Loopback"),
        ({"port": 70000}, "port"),
        ({"startup_timeout_s": 0}, "positive"),
    ],
)
def test_invalid_values_rejected(tmp_path, write_cfg, override, message):
    write_cfg(tmp_path, **override)
    with pytest.raises(config.ConfigError, match=message):
        config.load(tmp_path)


def test_reserved_args_and_watermark(tmp_path, write_cfg):
    write_cfg(tmp_path)
    path = tmp_path / "local" / "config.toml"
    path.write_text(path.read_text().replace("extra_args = []", 'extra_args = ["--port=1"]'))
    with pytest.raises(config.ConfigError, match="extra_args"):
        config.load(tmp_path)
    write_cfg(tmp_path)
    path.write_text(path.read_text() + 'PYTORCH_MPS_HIGH_WATERMARK_RATIO = "-1"\n')
    with pytest.raises(config.ConfigError, match="WATERMARK"):
        config.load(tmp_path)
