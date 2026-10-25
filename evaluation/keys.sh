#!/usr/bin/env bash
# 密钥移出/归位脚本（测评过程纪律，防再污染）
#
# 背景：第一轮测评中，基线 agent 自行浏览任务目录读到了 ground_truth.json（评分密钥），
#       该轮作废重跑。本脚本把密钥移出被测目录，跑完再归位。
#
# 用法：
#   ./keys.sh hide    # 跑测评前：把 ground_truth*.json 移到 ../.eval_keys_backup/
#   ./keys.sh show    # 评分阶段：把密钥移回 evaluation/（并显示内容清单）
#   ./keys.sh status  # 查看密钥当前在哪
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
BACKUP="${DIR}/../.eval_keys_backup"
FILES=(ground_truth.json ground_truth_long.json ground_truth_nt.json ground_truth_qual.json)

whereis_it() {
  local moved=0 present=0
  for f in "${FILES[@]}"; do
    [ -f "$BACKUP/$f" ] && moved=1
    [ -f "$DIR/$f" ] && present=1
  done
  if [ $present -eq 1 ]; then echo "evaluation/ 内密钥：在（被测方可读！）"; else echo "evaluation/ 内密钥：无"; fi
  if [ $moved -eq 1 ]; then echo "备份目录 $BACKUP ：有"; else echo "备份目录 $BACKUP ：无"; fi
}

case "${1:-}" in
  hide)
    mkdir -p "$BACKUP"
    n=0
    for f in "${FILES[@]}"; do
      if [ -f "$DIR/$f" ]; then mv "$DIR/$f" "$BACKUP/$f"; n=$((n+1)); fi
    done
    echo "已移出 $n 个密钥文件至 $BACKUP"
    echo "提示：同时确认 runs/ 下的 *_summary 与测评报告不含逐条密钥内容（评分矩阵在裁判侧保存）。"
    whereis_it
    ;;
  show)
    n=0
    for f in "${FILES[@]}"; do
      if [ -f "$BACKUP/$f" ]; then mv "$BACKUP/$f" "$DIR/$f"; n=$((n+1)); fi
    done
    echo "已归位 $n 个密钥文件至 evaluation/ —— 现在可以评分了。"
    whereis_it
    ;;
  status)
    whereis_it
    ;;
  *)
    echo "用法：$0 {hide|show|status}"
    exit 1
    ;;
esac
