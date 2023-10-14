""" Simple key-value store with disk persistence and buffer management."""
import os
import json
import threading
import time
from hashlib import blake2b
from collections import defaultdict
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
class KeyValueSync:
    """Timer based sync for KeyValueStore instances."""
    def __init__(self, flush_interval_seconds: int):
        self.flush_interval = flush_interval_seconds
        self.stores = []
        self.flush_thread = threading.Thread(target=self.flush_and_sleep)
        self.flush_thread.daemon = True
        self.accepting_new_stores = True
        self.is_running = True
        if self.accepting_new_stores:
            self.flush_thread.start()


    def flush_and_sleep(self):
        """Flushes all registered stores and sleeps for the interval."""
        while self.is_running:
            for store in self.stores:
                store.flush_if_needed()
            time.sleep(self.flush_interval)

    def register_store(self, store):
        """Registers a KeyValueStore instance to be flushed on timer."""
        if self.accepting_new_stores:
            self.stores.append(store)
        else:
            raise RuntimeError("No longer accepting new KeyValueStore registrations.")

    def status(self):
        """Returns a list of status info for all registered stores."""
        status_info = []
        for store in self.stores:
            items_count = len(store.buffer)
            buffer_size = sum(len(value) for value in store.buffer.values())
            status_info.append({
                'store': store.name,
                'items_count': items_count,
                'buffer_size': buffer_size
            })
        return status_info

    def sync_exit(self):
        """Flushes all registered stores and stops the timer."""
        self.is_running = False
        self.accepting_new_stores = False
        for store in self.stores:
            store.flush()



class KeyValueStore:
    """Simple key-value store with disk persistence, buffer and lock management."""
    def __init__(self, data_folder_path: str, db: str, buffer_size_mb: float,
                 namespace: str, sync: KeyValueSync):
        self.data_folder_path = data_folder_path
        self.db = db
        self.buffer_size_bytes = buffer_size_mb * 1024 * 1024
        self.namespace = namespace
        self.buffer = defaultdict(str)
        self.last_flush = datetime.now()
        self.sync = sync
        self.sync.register_store(self)
        self.locks = {}
        self.locks_management_lock = threading.Lock()
        self.global_flush_lock = threading.Lock()

        if not os.path.exists(data_folder_path):
            os.makedirs(data_folder_path)

    def _get_hash(self, key: str) -> str:
        """Returns a hash for the given key, to be used as a file name."""
        full_path = os.path.join(self.namespace, self.db, key)
        hash_value = blake2b(full_path.encode()).hexdigest()
        logging.info(f"Full Path: {full_path}, Hash: {hash_value}")
        return hash_value

    def _get_path(self, key: str) -> str:
        """Returns the full path for the given key."""
        hash_key = self._get_hash(key)
        return os.path.join(
            self.data_folder_path,
            hash_key[0],
            hash_key[1],
            self.namespace,
            self.db,
            hash_key
        )

    def _should_flush(self) -> bool:
        """Returns True if the buffer should be flushed to disk."""
        current_size = sum(len(key) + len(value) for key, value in self.buffer.items())
        time_since_last_flush = datetime.now() - self.last_flush
        return (current_size >= self.buffer_size_bytes or
                time_since_last_flush >= timedelta(seconds=self.sync.flush_interval))


    def flush_if_needed(self):
        """Flushes the buffer to disk if needed."""
        if self._should_flush():
            self._flush_to_disk()

    def _flush_to_disk(self):
        """Flushes the buffer to disk."""
        if len(self.buffer) == 0:
            logging.info("No keys to flush.")
            return

        logging.info(f"Flushing {len(self.buffer)} keys to disk.")
        with self.global_flush_lock:
            for key, value in self.buffer.items():
                path = self._get_path(key)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w') as file:
                    json.dump(value, file)
            self.buffer.clear()
            self.last_flush = datetime.now()

    def set(self, key: str, value: str):
        """Sets a value for the given key."""
        with self._get_lock(key):
            self.buffer[key] = value
        self.flush_if_needed()

    def get(self, key: str):
        """Returns the value for the given key."""
        with self._get_lock(key):
            if key in self.buffer:
                logging.info(f"Key {key} found in buffer.")
                return self.buffer[key]
            path = self._get_path(key)
            if os.path.exists(path):
                logging.info(f"Key {key} found in disk.")
                with open(path, 'r') as file:
                    return json.load(file)
        raise KeyError(f"No value found for key: {key}")

    def delete(self, key: str):
        """Deletes the value for the given key."""
        path = self._get_path(key)
        with self._get_lock(key):
            logging.info(f"Deleting key {key}.")
            if key in self.buffer:
                del self.buffer[key]
            elif os.path.exists(path):
                os.remove(path)
            else:
                raise KeyError(f"No value found for key: {key}")

    def _get_lock(self, key: str):
        """Acquires and returns a lock for the given key."""
        with self.locks_management_lock:
            if key not in self.locks:
                self.locks[key] = threading.Lock()
            return self.locks[key]

    def flush(self):
        """Flushes the buffer to disk."""
        self._flush_to_disk()

    def flushdb(self):
        """Deletes all keys in the current database."""
        for root, dirs, files in os.walk(self.data_folder_path, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))

    @property
    def name(self):
        """Returns the name of the current database."""
        return f"{self.namespace}:{self.db}"


if __name__ == '__main__':
    kv_sync = KeyValueSync(2)
    kv_store = KeyValueStore('./data', 'db1', 1, "ovo", kv_sync)
    kv_store_2 = KeyValueStore('./data', "risoto", 1, "batata", kv_sync)
    kv_store_2.set('key1', 'value12')
    kv_store_2.set('key2', 'value22')
    kv_store_2.set('key3', 'value32')
    kv_store.set('key1', 'value1')
    kv_store.set('key2', 'value2')
    kv_store.set('key3', 'value3')
    print(json.dumps(kv_sync.status(), indent=4))
    time.sleep(5)

    print(kv_store.get('key1'))
    print(kv_store_2.get('key1'))
    print(kv_store.get('key2'))
    print(kv_store_2.get('key2'))
    print(kv_store.get('key3'))
    print(kv_store_2.get('key3'))

    kv_sync.sync_exit()
