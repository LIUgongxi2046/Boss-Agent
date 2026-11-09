set -euo pipefail

group=/sys/fs/cgroup/boss-tree-probe
case "${1:-run}" in
    launch)
        echo "$$" > "$group/cgroup.procs"
        exec setsid bash "$0" descendants
        ;;
    descendants)
        sleep 300 &
        sleep 300 &
        wait
        ;;
    escape)
        echo "$$" > "$group/cgroup.procs"
        exec runuser -u isolation -- sh -c 'echo $$ > /sys/fs/cgroup/cgroup.procs'
        ;;
    run)
        mkdir "$group"
        trap 'echo 1 > "$group/cgroup.kill"' EXIT
        for index in 1 2 3 4; do
            bash "$0" launch &
        done
        sleep 2
        count=$(wc -l < "$group/cgroup.procs")
        printf 'TREE_PROCESS_COUNT %s\n' "$count"
        if [ "$count" -lt 12 ]; then
            echo "TREE_PROCESS_COUNT_INSUFFICIENT" >&2
            exit 1
        fi
        if bash "$0" escape; then
            echo "CGROUP_ESCAPE_ALLOWED" >&2
            exit 1
        fi
        echo "CGROUP_ESCAPE_REJECTED"
        echo 1 > "$group/cgroup.kill"
        cat "$group/cgroup.events"
        grep -qx 'populated 0' "$group/cgroup.events"
        echo "TREE_RECLAIMED"
        ;;
    *)
        exit 2
        ;;
esac
