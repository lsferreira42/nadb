"""NADB 0.3 feature showcase."""
from datetime import datetime, timedelta
import tempfile

from nadb import KeyValueStore


def main():
    with tempfile.TemporaryDirectory() as data_dir:
        with KeyValueStore.open(
            data_folder_path=data_dir,
            db="showcase",
            namespace="org/project/dev",
            return_type="stored",
            encryption_key="demo-secret",
            storage_backend="fs",
        ) as store:
            store.watch("*", lambda **event: print("event:", event["event"], event["key"]))

            store.set_text("hello", "world", tags=["demo"])
            store.set_json("user:1", {"status": "active", "plan": "pro"}, tags=["user"])
            store.set_with_expires_at("session", "active", datetime.now() + timedelta(minutes=5))

            stored = store.get("hello")
            print(stored.text, stored.content_type, stored.etag)

            store.set_many({"counter": "1", "feature": "enabled"})
            print("counter:", store.incr("counter"))

            store.create_index("status")
            print("active users:", store.query_index("status", "active"))
            print("query:", store.query().tag("user").keys())

            with store.open_writer("blob", chunk_size=4) as writer:
                writer.write(b"abcdefgh")
            print("blob:", store.get_chunked("blob"))

            path = f"{data_dir}/backup.jsonl"
            store.export_backup_stream(path)
            print("backup:", path)


if __name__ == "__main__":
    main()
