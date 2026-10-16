#!/bin/zsh
set -e
cd "${0:A:h}"
print "正在启动：$PWD"
print "新版入口：页面顶部「条目浏览库」；支持原行编辑，保存后自动复查。"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import openai' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r requirements.txt
fi
exec .venv/bin/python workshop_app.py
