"""冻结程序的入口：保留退出码，并兼容 Windows 多进程启动。"""

from multiprocessing import freeze_support


if __name__ == "__main__":
    freeze_support()

    import sys
    if len(sys.argv) == 4 and sys.argv[1] == "--verify-pixel-codecs":
        from voxplane.core.codec_check import verify
        raise SystemExit(verify(sys.argv[2], sys.argv[3]))

    if len(sys.argv) == 5 and sys.argv[1] == "--verify-workspace":
        from packaged_workspace_check import verify_workspace
        raise SystemExit(verify_workspace(sys.argv[2], sys.argv[3], sys.argv[4]))

    from voxplane.app import main

    raise SystemExit(main())
