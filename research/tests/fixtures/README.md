# Test fixtures (byte-exact historical evidence)

`b5_run2_edge_registry.py.orig`: the exact bytes of `research/edge_registry.py` as hashed by MANIFEST-3 and used by
B5 run 2 (D31). sha256 `e56f49aa862eaaf8048494272e1de1e3d363a0490282562b080f63dae5405c5c`, which equals the
MANIFEST-3 entry for that file and the blob at commits bb9ea44, 45409e4, 4491452, e5d1dc1, a4a07d7 and 1eb0e96.
D33 changed the live file afterwards (D31 added to the spent set), so the tests read the run-2 bytes from here
instead of from git history (owner decision D34). The `.orig` suffix keeps it from being imported or collected.
Do not edit; `.gitattributes` disables line-ending conversion for this folder.
