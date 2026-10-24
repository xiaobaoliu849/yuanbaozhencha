#!/usr/bin/env bash
# Install / update the app on a mainland-China Linux server (Aliyun ECS etc.) and serve it on port 80.
# Run as root from the unpacked app folder: bash deploy/aliyun/setup.sh
# No Docker needed (Docker Hub is blocked in mainland China); pip uses the Aliyun mirror.
set -euo pipefail

APP_DIR=/opt/chadedao
PORT=${PORT:-80}
HOST=0.0.0.0
# If nginx already owns port 80 (other sites on the same server), run the app privately
# and add an nginx site for SERVER_NAME (the public IP or a domain) instead.
SERVER_NAME=${SERVER_NAME:-}
if [ -n "$SERVER_NAME" ]; then HOST=127.0.0.1; PORT=${APP_PORT:-8020}; fi
PIP_MIRROR=https://mirrors.aliyun.com/pypi/simple/

ok_python() { "$1" -c 'import sys; sys.exit(sys.version_info < (3, 9))' 2>/dev/null; }

PY=""
for c in python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$c" >/dev/null && ok_python "$c"; then PY=$(command -v "$c"); break; fi
done
if [ -z "$PY" ]; then
  echo "Installing Python 3..."
  if command -v apt-get >/dev/null; then
    apt-get update -y && apt-get install -y python3 python3-venv
  else
    (dnf install -y python3.11 || dnf install -y python39 || yum install -y python3)
  fi
  for c in python3.11 python3.9 python3; do
    if command -v "$c" >/dev/null && ok_python "$c"; then PY=$(command -v "$c"); break; fi
  done
fi
[ -n "$PY" ] || { echo "Need Python 3.9+"; exit 1; }
if command -v apt-get >/dev/null && ! "$PY" -c 'import ensurepip' >/dev/null 2>&1; then
  apt-get update -y && apt-get install -y "python3-venv" "$(basename "$PY")-venv" || apt-get install -y python3-venv
fi
echo "Using $PY"

mkdir -p "$APP_DIR/data"
cp -r backend requirements.txt "$APP_DIR/"
mkdir -p "$APP_DIR/frontend" && rm -rf "$APP_DIR/frontend/dist" && cp -r frontend/dist "$APP_DIR/frontend/"
[ -f .env ] && cp .env "$APP_DIR/.env"

[ -x "$APP_DIR/venv/bin/pip" ] || { rm -rf "$APP_DIR/venv"; "$PY" -m venv "$APP_DIR/venv"; }
"$APP_DIR/venv/bin/pip" install -q -i "$PIP_MIRROR" --upgrade pip
"$APP_DIR/venv/bin/pip" install -q -i "$PIP_MIRROR" -r "$APP_DIR/requirements.txt"

cat > /etc/systemd/system/chadedao.service <<UNIT
[Unit]
Description=查得到，信得过
After=network-online.target

[Service]
WorkingDirectory=$APP_DIR
Environment=DATA_DIR=$APP_DIR/data
ExecStart=$APP_DIR/venv/bin/uvicorn backend.main:app --host $HOST --port $PORT --proxy-headers --forwarded-allow-ips=*
Restart=always

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable chadedao >/dev/null
systemctl restart chadedao

if [ -n "$SERVER_NAME" ]; then
  cat > /etc/nginx/conf.d/chadedao.conf <<NGINX
server {
    listen 80;
    server_name $SERVER_NAME;
    client_max_body_size 12m;
    location / {
        proxy_pass http://127.0.0.1:$PORT;
        proxy_http_version 1.1;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_buffering off;
        proxy_read_timeout 600s;
    }
}
NGINX
  nginx -t && systemctl reload nginx
# Open the port in the OS firewall if one is running (the Aliyun security group is separate).
elif command -v firewall-cmd >/dev/null && firewall-cmd --state >/dev/null 2>&1; then
  firewall-cmd --permanent --add-port="$PORT/tcp" && firewall-cmd --reload
elif command -v ufw >/dev/null && ufw status | grep -q active; then
  ufw allow "$PORT/tcp"
fi

for i in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$PORT/api/health" >/dev/null 2>&1; then
    echo "OK: running on port $PORT"; curl -s "http://127.0.0.1:$PORT/api/health"; echo; exit 0
  fi
  sleep 1
done
echo "Did not start; recent log:"; journalctl -u chadedao -n 40 --no-pager; exit 1
