def test_package_imports() -> None:
    import open_mapping

    assert open_mapping.__version__ == "0.2.0"
    assert "map_schemas" in open_mapping.__all__
