#!/bin/bash
pushd .

TMUX_SESSION="mdm_test"
CURRENT_DIR=`dirname $0`
CURRENT_DIR=`cd ${CURRENT_DIR} && pwd`

P0_cmd="python mdm_apns.py"
P1_cmd="tail -f log.txt"
P2_cmd="sleep 1; python mdm_agent.py" #sleep 1 aim to wait the apns server started
P3_cmd="python cli.py"

do_stop () {
    tmux has-session -t $TMUX_SESSION
    if [ $? = 0 ]; then
        tmux send-keys -t $TMUX_SESSION:first.0 C-z
        tmux send-keys -t $TMUX_SESSION:first.2 C-c C-c
        tmux send-keys -t $TMUX_SESSION:first.1 C-c
        tmux send-keys -t $TMUX_SESSION:first.3 C-c

        tmux detach-client
    fi
}

do_start() {
    touch mdm_log.log
    tmux has-session -t $TMUX_SESSION
    if [ $? = 0 ]; then
        tmux detach-client
        tmux kill-session -t $TMUX_SESSION
    fi

    tmux new-session -s $TMUX_SESSION -n first -d
    tmux send-keys -t $TMUX_SESSION "cd ${CURRENT_DIR}" C-m
    #tmux send-keys -t $TMUX_SESSION "ls -l" C-m

    tmux split-window -h -p 50 -t $TMUX_SESSION
    tmux send-keys -t $TMUX_SESSION "cd ${CURRENT_DIR}" C-m

    tmux split-window -v -t $TMUX_SESSION:first.0
    tmux send-keys -t $TMUX_SESSION "cd ${CURRENT_DIR}" C-m

    tmux send-keys -t $TMUX_SESSION:first.0 "$P0_cmd" C-m
    tmux send-keys -t $TMUX_SESSION:first.2 "$P2_cmd" C-m
    tmux send-keys -t $TMUX_SESSION:first.1 "${P1_cmd}" C-m
    

    tmux new-window -n clone -t $TMUX_SESSION
    tmux send-keys -t $TMUX_SESSION "cd ${CURRENT_DIR}" C-m

    tmux select-window -t $TMUX_SESSION:first

    tmux split-window -v -p 25 -t $TMUX_SESSION:first.1
    tmux send-keys -t $TMUX_SESSION "cd ${CURRENT_DIR}" C-m
    tmux send-keys -t $TMUX_SESSION:first.3 "${P3_cmd}" C-m

    # tmux send-keys -t $TMUX_SESSION:first.3 "" C-m

    tmux -2 attach -t $TMUX_SESSION
}

do_restart () {
    do_stop
    do_start
}

case $1 in 
    stop) do_stop ;;
    start) do_start  ;;
    restart) do_restart ;;
    *) do_start
esac

popd
