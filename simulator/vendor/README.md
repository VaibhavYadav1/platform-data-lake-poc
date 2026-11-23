# simulator/vendor

`generate_synthetic_data.py` is POC 1's data generator, copied unchanged from `data-gen-upload-data-lake-poc` at
commit `4edc2ba76736b4820b99f783633b38f67091eda1` (`git show 4edc2ba:generate_synthetic_data.py`).

- SHA-256: `9d9b747d2cd5d76dc9da58301fa363c93e7d83c3ef57ed474ab8c4cade2d3f24`
  (`tests/test_baseline.py` fails if the file changes).
- **Never edit it.** The seed must build exactly the rows POC 1 loaded, so parity compares like with like. With a
  fixed `SEED` and `AS_OF`, it rebuilds `clean_data_20261116_190645` byte for byte (the seed checks every MD5).
- Needs `data-lake-schema==1.0.0` (see `../requirements.txt`).
- To take a newer version: copy it from a new commit, update the hash here and in the test, and expect the seed to
  refuse until the baseline is frozen again (task 0.3).
