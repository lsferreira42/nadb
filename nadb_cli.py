"""Command-line interface for NADB."""
import argparse
import json

from nakv import KeyValueStore


def build_parser():
    parser = argparse.ArgumentParser(prog="nadb", description="Inspect and manage NADB stores")
    parser.add_argument("--data", default="./data", help="Data directory")
    parser.add_argument("--db", default="default", help="Database name")
    parser.add_argument("--namespace", default="default", help="Namespace")
    parser.add_argument("--backend", default="fs", help="Storage backend")
    sub = parser.add_subparsers(dest="command", required=True)

    set_cmd = sub.add_parser("set")
    set_cmd.add_argument("key")
    set_cmd.add_argument("value")

    get_cmd = sub.add_parser("get")
    get_cmd.add_argument("key")

    sub.add_parser("keys")
    sub.add_parser("tags")

    delete_cmd = sub.add_parser("delete")
    delete_cmd.add_argument("key")

    export_cmd = sub.add_parser("export")
    export_cmd.add_argument("path")

    import_cmd = sub.add_parser("import")
    import_cmd.add_argument("path")

    sub.add_parser("compact")
    sub.add_parser("verify")
    sub.add_parser("cleanup-expired")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    with KeyValueStore.open(
        data_folder_path=args.data,
        db=args.db,
        namespace=args.namespace,
        storage_backend=args.backend,
    ) as store:
        if args.command == "set":
            store.set_text(args.key, args.value)
            print("ok")
        elif args.command == "get":
            print(store.get_text(args.key))
        elif args.command == "keys":
            print(json.dumps(store.get_all_keys()))
        elif args.command == "tags":
            print(json.dumps(store.list_all_tags()))
        elif args.command == "delete":
            store.delete(args.key)
            print("ok")
        elif args.command == "export":
            print(store.export_backup_stream(args.path))
        elif args.command == "import":
            print(store.import_backup_stream(args.path))
        elif args.command == "compact":
            print(json.dumps(store.compact_storage(), default=str))
        elif args.command == "verify":
            print(json.dumps(store.get_stats(), default=str))
        elif args.command == "cleanup-expired":
            print(json.dumps(store.cleanup_expired(), default=str))


if __name__ == "__main__":
    main()
