# session_analytics.config_data — packaged config + DDL resources.
#
# Holds defaults.yaml and the normalization map files, loaded via
# importlib.resources so they resolve regardless of cwd. Kept as a package
# (not a bare data dir) so ``resources.files`` can address it by import name.
