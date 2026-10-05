#!/usr/bin/env bash
# Never apply errexit/environment changes to the operator's interactive shell.
if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
  echo 'Do not source this script. Run: bash ./spindle-test.sh check (or disabled/hold).' >&2
  return 0
fi
set -Eeuo pipefail
trap 'printf "Launcher failed at line %s (exit %s). Run check with output redirected to diagnose.\n" "$LINENO" "$?" >&2' ERR
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PP_ROOT=${PP_ROOT:-"$HOME/tmc"}
export PATH="$PP_ROOT/bin:$PP_ROOT/scripts:$PATH"
export LD_LIBRARY_PATH="$PP_ROOT/lib:${LD_LIBRARY_PATH:-}"
export EMC2_HOME="$PP_ROOT"
export LINUXCNC_BIN_DIR="$PP_ROOT/bin"
export LINUXCNC_RTLIB_DIR="$PP_ROOT/rtlib"
# These are the variables exported by the target's start_linuxcnc script.
# halcmd/rtapi_app otherwise fall back to paths baked into the development build.
export EMC2_BIN_DIR="$PP_ROOT/bin"
export EMC2_RTLIB_DIR="$PP_ROOT/rtlib"
export HAL_RTMOD_DIR="$PP_ROOT/rtlib"
export LINUXCNC_HOME="$PP_ROOT"
PYRUN="$PP_ROOT/scripts/py3_run.sh"
HALCMD="$PP_ROOT/bin/halcmd"
SPINDLE_ARGS=(--master=0 --position=0 --alias=-)
upload() {
 local value rc
 if value=$(ethercat upload "${SPINDLE_ARGS[@]}" -t "$1" "$2" "$3"); then
   value=${value##* }
   if [[ ! "$value" =~ ^-?[0-9]+$ ]]; then
     echo "Unreadable SDO result for $2:$3: $value" >&2; return 1
   fi
   printf '%s\n' "$value"
 else
   rc=$?
   echo "Read-only SDO upload failed: bus 0, spindle position 0, $2:$3 ($1), exit $rc." >&2
   return "$rc"
 fi
}
check() {
 local vendor product target_velocity position_offset gain_mode output_mask contactor_function contactor_logic
 [[ -x "$PYRUN" && -x "$HALCMD" ]] || { echo 'Missing PathPilot runtime. Set PP_ROOT to the active target runtime.' >&2; return 1; }
 command -v ethercat >/dev/null || { echo 'ethercat utility not available in this runtime environment.' >&2; return 1; }
 if [[ -e "$HERE/.position-gain-backup.json" ]]; then
   echo "Pending gain restore record found; hold will recover it before enabling."
 fi
 echo "Checking runtime $PP_ROOT and SV670N at EtherCAT bus 0, position 0..."
 vendor=$(upload uint32 0x1018 1) || return "$?"
 [[ "$vendor" == 1048576 ]] || { echo "Unexpected spindle vendor: $vendor (expected 1048576)." >&2; return 1; }
 product=$(upload uint32 0x1018 2) || return "$?"
 [[ "$product" == 786736 ]] || { echo "Unexpected spindle product: $product. Expected supplied SV670N INT profile 0x000c0130." >&2; return 1; }
 target_velocity=$(upload int32 0x60FF 0) || return "$?"
 position_offset=$(upload int32 0x60B0 0) || return "$?"
 [[ "$target_velocity" == 0 && "$position_offset" == 0 ]] || { echo 'Nonzero unhandled velocity or position offset; aborting.' >&2; return 1; }
 gain_mode=$(upload uint16 0x2008 9) || return "$?"
 [[ "$gain_mode" == 0 ]] || { echo 'Unexpected P/PI versus gain-bank selection setting.' >&2; return 1; }
 output_mask=$(upload uint32 0x60FE 2) || return "$?"
 (( output_mask == 0 || output_mask == 0x04010000 )) || { echo 'Unhandled forced-output mask; leave it unchanged and report the value.' >&2; return 1; }
 printf 'Output mask: 0x%08x (preserved; no mask writes).\n' "$output_mask"
 if (( output_mask == 0 )); then echo 'Forced P/PI override is not enabled; no effective override is assumed.'; fi
 contactor_function=$(upload uint16 0x2004 3) || return "$?"
 contactor_logic=$(upload uint16 0x2004 4) || return "$?"
 [[ "$contactor_function" == 11 && "$contactor_logic" == 1 ]] || { echo 'DO2 contactor function/logic does not match supplied SV670N profile.' >&2; return 1; }
 echo 'SV670N at position 0 matches the required identity, offsets, P/PI and contactor settings.'
}

case "${1:-help}" in
 plan|--dry-run)
 cat <<'PLAN'
Disabled-only validation: PathPilot closed; SV670N at bus 0, position 0.
Reuse the target PDO generator; do not start the full-mill drive manager.
Every drive control word remains zero. Preserve the current spindle mode/mask.
Confirm feedback and Switch On Disabled, print a snapshot, then release HAL.
hold captures the current position and enables CSP on the spindle only.
hold trials +25% speed gain and 75% integral time; position gain unchanged.
Live motor error uses PDO feedback; no SDO reads run in the holding loop.
Enter, Ctrl+C, or off requests disable, verified speed/integral restore, then CSV mode 9.
PLAN
 ;;
 check) check ;;
 off)
 "$HALCMD" getp csp-test-ui.begin >/dev/null
 "$HALCMD" setp csp-test-ui.stop true
 echo 'Stop requested. Wait for the hold terminal to confirm disable and close.'
 ;;
 disabled|hold)
 action=$1
 if [[ "$action" == hold && ! -t 0 ]]; then
   echo 'Run hold in an interactive terminal so Enter can stop it.' >&2; exit 1
 fi
 for required_file in bin/rtapi_app rtlib/hal_lib.so rtlib/threads.so rtlib/lcec.so rtlib/mux2_s32.so; do
   [[ -f "$PP_ROOT/$required_file" ]] || { echo "Missing runtime file: $PP_ROOT/$required_file" >&2; exit 1; }
 done
 if [[ "$action" == hold ]]; then
   for module in mux2_u32 oneshot match8 estop_latch; do
     [[ -f "$PP_ROOT/rtlib/$module.so" ]] || { echo "Missing runtime module: $module" >&2; exit 1; }
   done
 fi
 [[ -x "$PYRUN" && -x "$HALCMD" ]] || { echo 'Set PP_ROOT to the target PathPilot runtime.' >&2; exit 1; }
 # Never stop/kill an existing PathPilot or HAL session to take ownership.
 if pgrep -x rtapi_app >/dev/null || pgrep -x milltask >/dev/null || pgrep -f '[p]athpilotmanager.py' >/dev/null; then
   echo 'PathPilot/HAL is still running. Close it completely before this standalone test.' >&2; exit 1
 fi
 exec 9>"$HERE/.session-lock"
 flock -n 9 || { echo 'A test launcher is already active.' >&2; exit 1; }
 check
 initial_mode=$(upload int8 0x6061 0)
 [[ "$initial_mode" == 8 || "$initial_mode" == 9 ]] || { echo 'Unexpected initial spindle mode; do not change it. Report the value.' >&2; exit 1; }
 session=$(mktemp -d /tmp/1500mx-spindle-hold.XXXXXX)
 owned=0; supervisor=''
 cleanup() {
   trap - EXIT INT TERM HUP
   if [[ "$owned" == 1 ]]; then
     "$HALCMD" setp csp-test-ui.stop true 2>/dev/null || true
     if [[ -n "$supervisor" ]]; then
       # Allow bounded SDO restore/readback to finish before releasing EtherCAT.
       for ((n=0;n<500;n++)); do
         kill -0 "$supervisor" 2>/dev/null || break
         sleep .1
       done
       if kill -0 "$supervisor" 2>/dev/null; then kill -TERM "$supervisor" 2>/dev/null || true; sleep .5; fi
       wait "$supervisor" 2>/dev/null || true
     fi
     # The latch already loses permit/heartbeat; do not override its wired pins.
     sleep .1
     "$HALCMD" setp lcec.0.deactivate true 2>/dev/null || true
     sleep .1
     "$HALCMD" stop 2>/dev/null || true
     "$HALCMD" unload all 2>/dev/null || true
     "$PP_ROOT/scripts/realtime" stop || true
   fi
   rm -rf -- "$session"
 }
 trap cleanup EXIT
 trap 'exit 130' INT
 trap 'exit 143' TERM
 trap 'exit 129' HUP
 # Target generator scans the actual chain and configures PDOs; it does not run
 # the device manager's SDO parameter initialization or enable other drives.
 "$PYRUN" python3.8 -m pp_device_mgr.gen_ethercat_conf mill 1500MX "$session/ethercat.xml"
 # Retain the generated map for diagnosing a rejected mapping before HAL loads.
 cp -- "$session/ethercat.xml" "$HERE/last-ethercat.xml"
 # Enforce exact identity/address BEFORE loading any live PDO interface.
 "$PYRUN" python3.8 "$HERE/validate_xml.py" "$session/ethercat.xml"
 "$PP_ROOT/scripts/realtime" start
 owned=1
 CSP_LAUNCHER_PID=$$ CSP_INITIAL_MODE="$initial_mode" "$PYRUN" python3.8 "$HERE/hold.py" "--$action" &
 supervisor=$!
 for ((n=0;n<100;n++)); do
   "$HALCMD" getp csp-test-ui.begin >/dev/null 2>&1 && break
   kill -0 "$supervisor" 2>/dev/null || { echo 'Supervisor failed to start.' >&2; exit 1; }
   sleep .05
 done
 "$HALCMD" getp csp-test-ui.begin >/dev/null
 "$HALCMD" loadusr -W lcec_conf "$session/ethercat.xml"
 "$HALCMD" -f "$HERE/$action.hal"
 "$HALCMD" setp csp-test-ui.begin true
 if [[ "$action" == hold ]]; then
   echo 'Starting CSP hold. Wait for CSP HOLD ENABLED before testing rigidity.'
   echo 'Press Enter or Ctrl+C to stop; off also works from another terminal.'
   while kill -0 "$supervisor" 2>/dev/null; do
     if read -r -t .1 stop_line; then
       "$HALCMD" setp csp-test-ui.stop true
       break
     fi
   done
 else
   echo 'Running disabled-only feedback validation; this ends automatically.'
 fi
 wait "$supervisor"
 supervisor=''
 ;;
 *) echo 'Usage: ./spindle-test.sh plan | check | disabled | hold | off';;
esac
