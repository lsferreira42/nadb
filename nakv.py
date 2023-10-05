import os
import json
import threading
import time
from hashlib import blake2b
from collections import defaultdict
from datetime import datetime, timedelta
import logging

class KeyValueSync:
    def __init__(self, flush_interval_seconds: int):
        self.flush_interval = flush_interval_seconds
        self.stores = []
        self.flush_thread = threading.Timer(self.flush_interval, self.flush_and_restart)
        self.flush_thread.daemon = True
        self.flush_thread.start()
        self.accepting_new_stores = True

    def flush_and_restart(self):
        for store in self.stores:
            store.flush()
        self.flush_thread = threading.Timer(self.flush_interval, self.flush_and_restart)
        self.flush_thread.daemon = True
        self.flush_thread.start()

    def register_store(self, store):
        if self.accepting_new_stores:
            self.stores.append(store)
        else:
            raise RuntimeError("No longer accepting new KeyValueStore registrations.")

    def status(self):
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
        self.accepting_new_stores = False
        for store in self.stores:
            store.flush()
        self.flush_thread.cancel()


class KeyValueStore:
    def __init__(self, data_folder_path: str, db: str, buffer_size_mb: float, namespace: str, sync: KeyValueSync):
        self.data_folder_path = data_folder_path
        self.db = db
        self.buffer_size_bytes = buffer_size_mb * 1024 * 1024
        self.namespace = namespace
        self.buffer = defaultdict(str)
        self.last_flush = datetime.now()
        self.locks = {}
        self.sync = sync
        self.sync.register_store(self)

        if not os.path.exists(data_folder_path):
            os.makedirs(data_folder_path)

        logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

    def _get_hash(self, key: str) -> str:
        full_path = os.path.join(self.namespace, self.db, key)
        hash_value = blake2b(full_path.encode()).hexdigest()
        logging.debug(f"Full Path: {full_path}, Hash: {hash_value}")
        return hash_value

    def _get_path(self, key: str) -> str:
        hash_key = self._get_hash(key)
        return os.path.join(self.data_folder_path, hash_key[0], hash_key[1], self.namespace, self.db, hash_key)

    def _get_lock(self, key: str) -> threading.Lock:
        with threading.Lock():
            if key not in self.locks:
                self.locks[key] = threading.Lock()
            return self.locks[key]

    def _should_flush(self) -> bool:
        current_size = sum(len(value) for value in self.buffer.values())
        time_since_last_flush = datetime.now() - self.last_flush
        return current_size >= self.buffer_size_bytes or time_since_last_flush >= timedelta(seconds=self.sync.flush_interval)

    def _flush_to_disk(self):
        logging.debug(f"Flushing {len(self.buffer)} keys to disk.")
        with threading.Lock():
            for key, value in self.buffer.items():
                path = self._get_path(key)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w') as file:
                    json.dump(value, file)
            self.buffer.clear()
            self.last_flush = datetime.now()

    def set(self, key: str, value: str):
        with self._get_lock(key):
            logging.debug(f"Setting key {key}.")
            self.buffer[key] = value
        if self._should_flush():
            self._flush_to_disk()

    def get(self, key: str):
        with self._get_lock(key):
            logging.debug(f"Getting key {key}.")
            if key in self.buffer:
                logging.debug(f"Key {key} found in buffer.")
                return self.buffer[key]
            path = self._get_path(key)
            if os.path.exists(path):
                with open(path, 'r') as file:
                    return json.load(file)
        raise KeyError(f"No value found for key: {key}")

    def delete(self, key: str):
        path = self._get_path(key)
        with self._get_lock(key):
            logging.debug(f"Deleting key {key}.")
            if key in self.buffer:
                del self.buffer[key]
            elif os.path.exists(path):
                os.remove(path)
            else:
                raise KeyError(f"No value found for key: {key}")

    def flush(self):
        self._flush_to_disk()

    def flushdb(self):
        for root, dirs, files in os.walk(self.data_folder_path, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))

    @property
    def name(self):
        return f"{self.namespace}:{self.db}"


if __name__ == '__main__':
    # Usage:
    data_folder_path = './data'
    db_name = 'db1'
    buffer_size_mb = 1  # 1 MB
    flush_interval_seconds = 2
    namespace = 'namespace1'
    kv_sync = KeyValueSync(flush_interval_seconds)
    kv_store = KeyValueStore(data_folder_path, db_name, buffer_size_mb, namespace, kv_sync)
    kv_store_2 = KeyValueStore(data_folder_path, "risoto", buffer_size_mb, "batata", kv_sync)
    kv_store_2.set('key1', 'value12')
    kv_store_2.set('key2', 'value22')
    kv_store_2.set('key3', 'value32')
    kv_store.set('key1', 'value1')
    kv_store.set('key2', 'value2')
    kv_store.set('key3', 'value3')
    print(json.dumps(kv_sync.status(), indent=4))
    print(kv_store.get('key1'))
    print(kv_store_2.get('key1'))
    print(kv_store.get('key2'))
    print(kv_store_2.get('key2'))
    print(kv_store.get('key3'))
    print(kv_store_2.get('key3'))

    kv_sync.sync_exit()
