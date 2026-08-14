# -*- coding: utf-8 -*-
from conf.config import Settings


def test_mysql_auto_import_defaults_false():
    assert Settings().mysql_auto_import is False
