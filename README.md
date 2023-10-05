# NADB - Not A Database

A simple, thread-safe key-value store with asynchronous disk buffering capabilities.

:rotating_light: **This project is educational and not intended for production use.** :rotating_light:


## Features

- Thread-safe operations for setting, getting, and deleting key-value pairs.
- In-memory buffering of key-value pairs with asynchronous flushing to disk.
- Periodic flushing of the buffer to disk to ensure data integrity.
- Manual flushing capability for immediate persistence.
- Namespace and database separation for organized data storage.
- Simple usage and minimal setup required.

## Installation

```bash
pip install nadb
```

## Quickstart

Here's a basic example of how to use NADB:

```python
from nadb import KeyValueStore, KeyValueSync

# Initialize the KeyValueSync for asynchronous flushing
kv_sync = KeyValueSync()

# Create a KeyValueStore instance

data_folder_path = './data'
db_name = 'db1'
buffer_size_mb = 1  # 1 MB
flush_interval_seconds = 60  # 1 minute
namespace = 'namespace1'
kv_store = KeyValueStore(data_folder_path, db_name, buffer_size_mb, flush_interval_seconds, namespace)

# Set some key-value pairs
kv_store.set('key1', 'value1')
kv_store.set('key2', 'value2')
kv_store.set('key3', 'value3')

# Get a value
value1 = kv_store.get('key1')  # Returns 'value1'

# Delete a key-value pair
kv_store.delete('key1')

# Manual flush (optional, as flushing occurs automatically based on buffer size and time interval)
kv_store.flush()

# Retrieve the status of all KeyValueStore instances
status = kv_sync.status()  # Returns a list of dictionaries with information about each KeyValueStore instance

# Stop accepting new KeyValueStore registrations, sync remaining ones, and exit
kv_sync.sync_exit()
```
