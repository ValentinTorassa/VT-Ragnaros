"""`ragnaros install-system` / `install-service`, without sudo or systemctl."""
import os

import pytest

from ragnaros import cli


@pytest.fixture
def no_commands(monkeypatch):
    ran = []

    class Done:
        returncode = 0

    def fake_run(cmd, *args, **kwargs):
        ran.append(cmd)
        return Done()

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    return ran


def test_install_system_print_shows_files_and_runs_nothing(no_commands, capsys, monkeypatch):
    monkeypatch.setattr(cli, "packaged_system_files", lambda: ["/nonexistent/a"])
    assert cli.main(["install-system", "--print"]) == 0
    out = capsys.readouterr().out
    assert "/etc/udev/rules.d/70-ragnaros.rules" in out
    assert "/etc/modprobe.d/ragnaros-usbhid.conf" in out
    assert 'ATTRS{idVendor}=="0200"' in out
    assert "options usbhid quirks=0x0200:0x3001:0x00000004" in out
    assert "sudo udevadm control --reload-rules" in out
    assert no_commands == []


def test_install_system_runs_every_step_with_sudo(no_commands, monkeypatch):
    monkeypatch.setattr(cli, "packaged_system_files", lambda: ["/nonexistent/a"])
    assert cli.main(["install-system"]) == 0
    assert no_commands and all(cmd[0] == "sudo" for cmd in no_commands)
    assert ["sudo", "udevadm", "trigger"] in no_commands


def test_install_system_defers_to_a_package(no_commands, monkeypatch, tmp_path, capsys):
    shipped = [tmp_path / "rules", tmp_path / "conf"]
    for path in shipped:
        path.write_text("x")
    monkeypatch.setattr(cli, "packaged_system_files", lambda: [str(p) for p in shipped])
    assert cli.main(["install-system"]) == 0
    assert "already installed by your package" in capsys.readouterr().out
    assert no_commands == []


def test_builtin_usbhid_is_detected(tmp_path):
    (tmp_path / "6.0.0").mkdir()
    (tmp_path / "6.0.0" / "modules.builtin").write_text("kernel/drivers/hid/usbhid/usbhid.ko\n")
    assert cli.usbhid_builtin("6.0.0", str(tmp_path)) is True
    assert cli.usbhid_builtin("6.9.9", str(tmp_path)) is False


def test_install_service_writes_a_unit_for_this_install(no_commands, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    monkeypatch.setattr(cli, "command_path", lambda name, module: f"/opt/venv/bin/{name}")
    assert cli.main(["install-service", "--gif-refresh"]) == 0
    units = tmp_path / "systemd" / "user"
    service = (units / "ragnarosd.service").read_text()
    assert "ExecStart=/opt/venv/bin/ragnarosd\n" in service
    assert "ExecStart=/opt/venv/bin/ragnaros-fetch-gifs\n" in \
        (units / "ragnaros-gif-refresh.service").read_text()
    assert (units / "ragnaros-gif-refresh.timer").exists()
    assert ["systemctl", "--user", "enable", "ragnarosd.service"] in no_commands


def test_install_service_never_clobbers_a_different_unit(no_commands, tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    units = tmp_path / "systemd" / "user"
    units.mkdir(parents=True)
    (units / "ragnarosd.service").write_text("ExecStart=%h/.config/ragnaros/daemon/ragnarosd.py\n")
    assert cli.main(["install-service"]) == 1
    assert "daemon/ragnarosd.py" in (units / "ragnarosd.service").read_text()
    assert no_commands == []
    assert cli.main(["install-service", "--force"]) == 0


def test_install_service_print_writes_nothing(no_commands, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert cli.main(["install-service", "--print"]) == 0
    assert "[Service]" in capsys.readouterr().out
    assert not os.path.exists(tmp_path / "systemd")
    assert no_commands == []


def test_paths_and_help(capsys):
    assert cli.main(["paths"]) == 0
    assert "gif theme" in capsys.readouterr().out
    assert cli.main([]) == 0
