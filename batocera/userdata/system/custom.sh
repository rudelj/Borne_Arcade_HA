#!/bin/bash
# Batocera user autostart script (/userdata/system/custom.sh)
# Launched automatically by Batocera on system startup and shutdown

case "$1" in
    start)
        /userdata/system/services/ha_kiosk start &
        ;;
    stop)
        /userdata/system/services/ha_kiosk stop &
        ;;
esac
