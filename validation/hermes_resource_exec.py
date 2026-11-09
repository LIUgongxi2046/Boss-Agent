import argparse
import os
import resource
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--file-bytes", type=int, required=True)
    parser.add_argument("--open-files", type=int, required=True)
    parser.add_argument("--cpu-seconds", type=int, required=True)
    parser.add_argument("executable")
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.file_bytes <= 0 or args.open_files < 16 or args.cpu_seconds <= 0:
        raise ValueError("进程资源限制无效")
    executable = Path(args.executable)
    if not executable.is_absolute() or not executable.is_file() or not os.access(executable, os.X_OK):
        raise ValueError("执行文件必须是有效绝对路径")
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_FSIZE, (args.file_bytes, args.file_bytes))
    resource.setrlimit(resource.RLIMIT_NOFILE, (args.open_files, args.open_files))
    resource.setrlimit(resource.RLIMIT_CPU, (args.cpu_seconds, args.cpu_seconds))
    os.execv(str(executable), [str(executable), *args.arguments])


if __name__ == "__main__":
    main()
