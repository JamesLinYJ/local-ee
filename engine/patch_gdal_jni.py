"""Keep GDAL 3.13 metadata pointers const across the JNI bridge."""
from pathlib import Path
root = Path("/src/gdal-warp-bindings/src")
for name in ["locked_dataset.hpp", "bindings.cpp", "bindings.h"]:
    p = root / name
    source = p.read_text()
    old = "const char *domain, char ***list"
    assert source.count(old) == 1, name
    p.write_text(source.replace(old, "const char *domain, const char *const **list"))
p = root / "com_azavea_gdal_GDALWarp.c"
source = p.read_text()
assert source.count("char **list = NULL;") == 1
p.write_text(source.replace("char **list = NULL;", "const char *const *list = NULL;"))
