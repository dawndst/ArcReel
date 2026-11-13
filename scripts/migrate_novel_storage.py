"""Offline migration/recovery command; stop the application and back up first."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lib.novel_workflow.storage_migration import migrate, rollback


def main():
    parser = argparse.ArgumentParser(description="迁移小说核心业务存储；操作前停止服务并备份数据库和项目目录")
    parser.add_argument("project", type=Path)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    if args.rollback:
        result = rollback(args.project)
    elif args.database:
        result = migrate(args.project, args.database)
    else:
        parser.error("迁移需要 --database；先运行 alembic upgrade head")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
