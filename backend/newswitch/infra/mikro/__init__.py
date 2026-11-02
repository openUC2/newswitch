"""Where an acquisition is stored: the `DatasetStore`s (`newswitch.protocols.dataset_store`).

- `store`: `MikroDatasetStore`, into a mikro (needs the extra ``mikro``);
- `connection`: where a mikro is in FastAPI mode, from the environment;
- `app`: the registry part providing a mikro client and its store in FastAPI mode (needs the
  extra ``mikro``);
- `none`: `NoDatasetStore`, which refuses an acquisition when there is no mikro.

Not imported here: `store` and `app` need the extra.
"""
