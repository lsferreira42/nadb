import os
import json
import threading
from hashlib import blake2b
from collections import deque
from datetime import datetime, timedelta

class KeyValueStore:
    def __init__(self, data_folder_path: str, buffer_size_mb: float, flush_interval_seconds: int):
        self.data_folder_path = data_folder_path
        self.buffer_size_bytes = buffer_size_mb * 1024 * 1024
        self.flush_interval = timedelta(seconds=flush_interval_seconds)
        self.buffer = deque()
        self.last_flush = datetime.now()
        self.lock = threading.Lock()

        if not os.path.exists(data_folder_path):
            os.makedirs(data_folder_path)

    def _get_hash(self, key: str) -> str:
        return blake2b(key.encode()).hexdigest()

    def _get_path(self, key: str) -> str:
        hash_key = self._get_hash(key)
        return os.path.join(self.data_folder_path, hash_key[0], hash_key[1], hash_key)

    def _should_flush(self) -> bool:
        current_size = sum(len(value) for key, value in self.buffer)
        time_since_last_flush = datetime.now() - self.last_flush
        return current_size >= self.buffer_size_bytes or time_since_last_flush >= self.flush_interval

    def _flush_to_disk(self):
        with self.lock:
            for key, value in self.buffer:
                path = self._get_path(key)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w') as file:
                    json.dump(value, file)
            self.buffer.clear()
            self.last_flush = datetime.now()

    def create(self, key: str, value: str):
        with self.lock:
            self.buffer.append((key, value))
        if self._should_flush():
            self._flush_to_disk()

    def read(self, key: str):
        path = self._get_path(key)
        if os.path.exists(path):
            with open(path, 'r') as file:
                return json.load(file)
        raise KeyError(f"No value found for key: {key}")

    def update(self, key: str, value: str):
        self.create(key, value)

    def delete(self, key: str):
        path = self._get_path(key)
        if os.path.exists(path):
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