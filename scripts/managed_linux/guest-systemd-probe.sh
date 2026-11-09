set -euo pipefail

if [ "${1:-}" = child ]; then
    sleep 300 &
    sleep 300 &
    wait
fi

for index in 1 2 3 4; do
    setsid bash "$0" child &
done
wait
