# FinTrace / PITfall — 开发入口
# 协议见 AGENTS.md；当前进度见 docs/00-STATE.md

.PHONY: onboard doctor setup check wrapup help

help:
	@echo "make onboard  - 新接手 agent 的入口（阅读顺序 + 环境体检）"
	@echo "make doctor   - 环境体检（工具链 / git / 网络）"
	@echo "make setup    - 初始化工具链与仓库"
	@echo "make check    - lint + 类型 + 测试（代码存在时）"
	@echo "make wrapup   - 会话收尾检查清单（AGENTS.md §2）"

onboard: doctor
	@echo ""
	@echo "== 接手阅读顺序 =="
	@echo "1. AGENTS.md            （协议与硬约束）"
	@echo "2. docs/00-STATE.md     （当前进度与下一步 —— 从这里继续）"
	@echo "3. 写代码前: docs/02-项目计划.md；花钱前: docs/03-实验预算方案.md"
	@echo "4. 向用户复述计划后，从 STATE「待办」第一项继续"

doctor:
	@echo "== 环境体检 =="
	@command -v git >/dev/null 2>&1 && echo "[ok] git" || echo "[缺] git（P0-1 需要）"
	@command -v uv >/dev/null 2>&1 && echo "[ok] uv" || echo "[缺] uv（安装: brew install uv）"
	@command -v python3 >/dev/null 2>&1 && python3 -c 'import sys; print("[ok] python", sys.version.split()[0])' || echo "[缺] python3"
	@command -v ollama >/dev/null 2>&1 && echo "[ok] ollama" || echo "[缺] ollama（安装: brew install ollama；P1 消融需要，可暂缓）"
	@if [ -d .git ]; then \
		echo "[ok] git 仓库已初始化，最近提交："; \
		git log --oneline -5 2>/dev/null | sed 's/^/      /'; \
	else \
		echo "[无] 尚未 git init（待办 P0-1）"; \
	fi
	@curl -s -m 8 -o /dev/null -w "[ok] sec.gov 可达 (HTTP %{http_code})\n" https://www.sec.gov/ 2>/dev/null || echo "[警] sec.gov 不可达（网络/代理问题？EDGAR 抓取依赖它）"

setup:
	@command -v uv >/dev/null 2>&1 || { echo "请先安装 uv: brew install uv"; exit 1; }
	@command -v ollama >/dev/null 2>&1 || echo "提示: 消融阶段需要 ollama（brew install ollama），可稍后安装"
	@if [ ! -d .git ]; then git init && echo "[done] git init 完成"; fi
	@if [ -f pyproject.toml ]; then uv sync; else echo "[提示] pyproject.toml 尚未创建（P0-2 任务）"; fi

check:
	@if [ ! -f pyproject.toml ]; then \
		echo "尚无 pyproject.toml（P0-2 任务），跳过检查"; \
	else \
		uv run ruff check --no-cache . && uv run mypy . && uv run pytest -q; \
	fi

wrapup:
	@echo "== 会话收尾清单（AGENTS.md §2）=="
	@echo "1. docs/00-STATE.md 已更新？（任务勾选 / 下一步 / 最后更新时间戳）"
	@echo "2. 重大决策已追加到 STATE「决策日志」？（日期｜决策｜理由｜否决项）"
	@echo "3. 新坑已追加到「经验与坑」？"
	@echo "4. make check 全绿？"
	@echo "5. 「会话日志」已追加一行？"
