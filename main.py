"""Launch Pythona SSH, or preview its interface in a desktop browser."""


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preview", action="store_true", help="preview with simulated SSH sessions")
    parser.add_argument("--port", type=int, default=8878, help="loopback preview port")
    parser.add_argument("--language", default="en", help="preview language: en, zh-Hans, zh-Hant")
    args = parser.parse_args()
    if args.preview:
        from ssh_app.preview import serve
        serve(args.port, args.language)
    else:
        import builtins
        if not hasattr(builtins, "run_on_ui"):
            parser.error("Run inside Pythona, or add --preview for a desktop browser preview.")
        from ssh_app.ui import main as present
        present()


if __name__ == "__main__":
    main()
