import json

from typer.testing import CliRunner

from frameport.cli import app
from frameport.core import library
from frameport.core.events import Reporter
from frameport.core.models import Recipe
from frameport.targets.offline import OfflineTarget


def test_offline_target_install_creates_complete_structure(tmp_path):
    pkg = "com.test.offlinegame"
    src_apk = tmp_path / "game_source.apk"
    src_apk.write_bytes(b"PK fake apk content 1234")

    obb_dir = tmp_path / "game_obbs"
    obb_dir.mkdir()
    obb_file = obb_dir / "main.100.com.test.offlinegame.obb"
    obb_file.write_bytes(b"OBB_CONTENT_TEST")

    recipe = Recipe(
        package=pkg,
        patches={
            "adapter.scale": {"scale": 1.25},
            "adapter.quest_buttons": {"mode": 1},
        },
        source="catalog",
    )

    library.upsert_game(
        pkg,
        title="Offline Test Game",
        apk=str(src_apk),
        data_dir=str(obb_dir),
        data_files=["main.100.com.test.offlinegame.obb"],
        recipe=library.recipe_to_dict(recipe),
    )

    out_dir = tmp_path / "offline_export"
    target = OfflineTarget(outdir=out_dir, move=False, fetch_art=False)
    reporter = Reporter()

    res = target.install(
        package=pkg,
        title="Offline Test Game",
        apk=src_apk,
        data_dir=obb_dir,
        recipe=recipe,
        reporter=reporter,
        data_files=["main.100.com.test.offlinegame.obb"],
    )

    assert res["ok"] is True
    game_dir = out_dir / pkg
    assert res["path"] == str(game_dir)

    # 1. lepton-app files
    dest_apk = game_dir / "lepton-app" / "game.apk"
    assert dest_apk.is_file()
    assert dest_apk.read_bytes() == b"PK fake apk content 1234"
    assert src_apk.exists()  # Copy mode preserved source

    dest_obb = game_dir / "lepton-app" / "obb" / "main.100.com.test.offlinegame.obb"
    assert dest_obb.is_file()
    assert dest_obb.read_bytes() == b"OBB_CONTENT_TEST"

    # 2. settings.conf
    conf_file = game_dir / "settings.conf"
    assert conf_file.is_file()
    conf_text = conf_file.read_text()
    assert "scale=" in conf_text
    assert "quest_buttons=" in conf_text

    # 3. deployment.json
    dep_file = game_dir / "deployment.json"
    assert dep_file.is_file()
    dep_data = json.loads(dep_file.read_text())
    assert dep_data["package"] == pkg
    assert dep_data["title"] == "Offline Test Game"
    assert dep_data["kind"] == "quest"
    assert "appid" in dep_data
    assert "sha256" in dep_data

    # 4. launch.sh
    launch_file = game_dir / "launch.sh"
    assert launch_file.is_file()
    assert launch_file.stat().st_mode & 0o111 != 0  # Executable
    launch_text = launch_file.read_text()
    assert f"export SteamAppId={dep_data['appid']}" in launch_text
    assert 'export STEAM_COMPAT_INSTALL_PATH="$app_dir/lepton-app"' in launch_text
    assert "flock" in launch_text
    assert "fix_perms" in launch_text

    # 5. data and shader directories
    assert (game_dir / "lepton-shaders").is_dir()
    assert (game_dir / "lepton-data" / "external" / "Android" / "data" / pkg / "files").is_dir()


def test_offline_target_move_mode(tmp_path):
    pkg = "com.test.movemode"
    src_apk = tmp_path / "move_source.apk"
    src_apk.write_bytes(b"PK move content")

    obb_dir = tmp_path / "move_obbs"
    obb_dir.mkdir()
    obb_file = obb_dir / "main.1.com.test.movemode.obb"
    obb_file.write_bytes(b"OBB_MOVE_DATA")

    recipe = Recipe(package=pkg, patches={}, source="catalog")
    out_dir = tmp_path / "move_export"
    target = OfflineTarget(outdir=out_dir, move=True, fetch_art=False)

    res = target.install(
        package=pkg,
        title="Move Game",
        apk=src_apk,
        data_dir=obb_dir,
        recipe=recipe,
        reporter=Reporter(),
        data_files=["main.1.com.test.movemode.obb"],
    )

    assert res["ok"] is True
    assert not src_apk.exists()  # Moved
    assert not obb_file.exists()  # Moved
    assert (out_dir / pkg / "lepton-app" / "game.apk").read_bytes() == b"PK move content"
    assert (out_dir / pkg / "lepton-app" / "obb" / "main.1.com.test.movemode.obb").read_bytes() == b"OBB_MOVE_DATA"


def test_offline_target_extra_methods(tmp_path):
    pkg = "com.test.methods"
    out_dir = tmp_path / "methods_export"
    target = OfflineTarget(outdir=out_dir)

    assert target.describe()["kind"] == "offline"
    assert target.installed() == []
    assert target.add_to_library([pkg], Reporter()) == {"ok": True, "packages": [pkg]}

    # Settings update
    game_dir = out_dir / pkg
    game_dir.mkdir(parents=True)
    (game_dir / "settings.conf").write_text("scale=1.0\n", encoding="utf-8")
    target.set_settings(pkg, {"scale": "1.4", "sharpness": "0.5"})
    updated_conf = (game_dir / "settings.conf").read_text()
    assert "scale=1.4" in updated_conf
    assert "sharpness=0.5" in updated_conf

    # Uninstall
    target.uninstall(pkg)
    assert not game_dir.exists()


def test_cli_offline_install_command(tmp_path):
    pkg = "com.test.clioffline"
    src_apk = tmp_path / "cli_game.apk"
    src_apk.write_bytes(b"PK cli game content")

    recipe = Recipe(package=pkg, patches={}, source="catalog")
    library.upsert_game(
        pkg,
        title="CLI Offline Game",
        apk=str(src_apk),
        build={"apk": str(src_apk)},
        recipe=library.recipe_to_dict(recipe),
    )

    out_dir = tmp_path / "cli_output"
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "offline-install",
            pkg,
            "--outdir", str(out_dir),
            "--no-art",
        ],
    )

    assert result.exit_code == 0
    assert "offline bundle created ->" in result.stdout
    assert (out_dir / pkg / "lepton-app" / "game.apk").exists()
    assert (out_dir / pkg / "launch.sh").exists()
    assert (out_dir / pkg / "deployment.json").exists()
