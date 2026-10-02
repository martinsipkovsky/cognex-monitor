"""Settings files in DATA_DIR are put back from the database copy when an
image update (a container without a volume for DATA_DIR) lost them."""
from app import backup_ftp, dbconfig, settings_store


def test_database_setting_restored_after_file_is_lost():
    cfg = {"host": "pg.example", "port": 5432, "database": "cognex", "user": "u", "password": "secret"}
    dbconfig.save(cfg)
    assert settings_store.load(dbconfig.KEY) == cfg

    dbconfig._path().unlink()  # what a recreated container without a volume looks like
    assert dbconfig.load() is None
    assert dbconfig.restore_missing() is True
    assert dbconfig.load() == cfg

    dbconfig.clear()  # clearing also forgets the copy
    assert settings_store.load(dbconfig.KEY) is None
    assert dbconfig.restore_missing() is False
    assert dbconfig.load() is None


def test_existing_file_gets_a_copy_on_start():
    cfg = {"host": "old.example", "port": 5432, "database": "d", "user": "u", "password": "p"}
    dbconfig._write(cfg)  # a file saved by a version without the copy
    settings_store.save(dbconfig.KEY, None)
    assert dbconfig.restore_missing() is False
    assert settings_store.load(dbconfig.KEY) == cfg
    dbconfig.clear()


def test_ftp_settings_restored_after_file_is_lost():
    saved = backup_ftp.save({**backup_ftp.DEFAULTS, "enabled": True, "host": "nas", "password": "pw", "keep": 7})
    backup_ftp._path().unlink()
    assert backup_ftp.load()["host"] == ""
    assert backup_ftp.restore_missing() is True
    assert backup_ftp.load() == saved
    backup_ftp.save(backup_ftp.DEFAULTS)
