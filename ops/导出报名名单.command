#!/bin/bash
set -euo pipefail
umask 077
project_dir="$(cd "$(dirname "$0")/../../.." && pwd)"
output_dir="$project_dir/报名数据"
helper='/Applications/MyChuannong Server Auth.app/Contents/MacOS/LocalServerAuth'
mkdir -p "$output_dir"
chmod 700 "$output_dir"
if [ "$("$helper" status)" != 'PRESENT_LOCAL_ONLY' ]; then
  printf '%s\n' '本机服务器凭据不可用，请先在 MyChuannong Server Auth 应用中设置。'
  exit 1
fi
temp_file="$(mktemp "$output_dir/.registration-export.XXXXXX")"
trap 'rm -f "$temp_file"' EXIT
"$helper" run /usr/bin/python3 /opt/kiro-hackathon/server.py export > "$temp_file"
output_file="$output_dir/报名名单-$(date '+%Y%m%d-%H%M%S')-$$.csv"
mv "$temp_file" "$output_file"
chmod 600 "$output_file"
printf '报名名单已保存：%s\n' "$output_file"
open -R "$output_file"
