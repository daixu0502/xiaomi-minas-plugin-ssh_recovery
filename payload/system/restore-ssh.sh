#!/bin/sh
# Pure POSIX shell recovery for Xiaomi NAS. Invoked with existing root authority.
set -eu
umask 077
PATH=/usr/sbin:/usr/bin:/sbin:/bin
export PATH
WORK=/data/ssh-autostart-fix
STATE=/data/.minas-privileged/sshrecovery
PASSWD=/etc/passwd
SHELL_DROPIN=/etc/systemd/system/dropbear@.service.d/90-normal-shell.conf
BOOT_DROPIN=/etc/systemd/system/minas.boot_check.service.d/90-keep-ssh.conf
CRON=/etc/cron.d/keep-ssh
PENDING=/etc/cron.d/minas-shell-ssh-activate
SYSTEMCTL=/usr/bin/systemctl
fail() { printf '失败：%s\n' "$*" >&2; exit 1; }

safe() {
    node=$1
    case "$node" in /*) ;; *) fail '恢复路径必须为绝对路径' ;; esac
    while :; do
        [ ! -L "$node" ] || fail "恢复路径包含符号链接：$node"
        if [ -e "$node" ]; then
            info=$(stat -c '%u %a' "$node")
            owner=${info%% *}; path_mode=${info#* }
            [ "$owner" = 0 ] && [ "$((0$path_mode & 0022))" -eq 0 ] || fail "恢复路径权限异常：$node"
        fi
        [ "$node" != / ] || break
        node=${node%/*}; [ -n "$node" ] || node=/
    done
}
private_dir() { safe "$1"; mkdir -p "$1"; chmod 0700 "$1"; }
# Atomic replacement in the target filesystem; callers validate the source.
put() {
    source=$1 target=$2 permissions=$3
    safe "$target"
    temp=$(mktemp "${target%/*}/.ssh-shell.XXXXXXXX")
    if ! cat "$source" > "$temp" || ! chmod "$permissions" "$temp" || ! mv -f "$temp" "$target"; then
        rm -f "$temp"; fail "无法写入 $target"
    fi
}
merge_keys() {
    incoming=$1 auth=$2
    safe "$auth"
    merged=$(mktemp "$WORK/.merge.XXXXXXXX")
    if [ -f "$auth" ]; then cat "$auth" > "$merged"; printf '\n' >> "$merged"; fi
    cat "$incoming" >> "$merged"
    awk 'NF && !seen[$0]++' "$merged" > "$merged.unique"
    put "$merged.unique" "$auth" 0600
    rm -f "$merged" "$merged.unique"
}
prepare_account() {
    safe "$PASSWD"
    record=$(awk -F: '$1=="root" {n++; row=$0} END {if(n==1) print row; else exit 1}' "$PASSWD") || fail 'root 记录异常'
    [ "$(printf '%s\n' "$record" | awk -F: '{print NF ":" $3}')" = '7:0' ] || fail 'root 记录异常'
    home=$(printf '%s\n' "$record" | cut -d: -f6)
    case "$home" in /root) home=/home/rootx ;; /home/rootx) ;; *) fail "不支持的 root 主目录：$home" ;; esac
    private_dir "$home"; private_dir "$home/.ssh"
    if [ "$(printf '%s\n' "$record" | cut -d: -f6)" = /root ] && [ -f /root/.ssh/authorized_keys ]; then
        safe /root/.ssh/authorized_keys
        merge_keys /root/.ssh/authorized_keys "$home/.ssh/authorized_keys"
    fi
    next=$(mktemp "$WORK/.passwd.XXXXXXXX")
    awk -F: -v OFS=: -v home="$home" '$1=="root" {$6=home; if($7 ~ /\/mi-shell$/) $7="/bin/sh"} {print}' "$PASSWD" > "$next"
    if ! cmp -s "$next" "$PASSWD"; then
        if [ ! -e "$WORK/passwd.before-shell-repair" ]; then put "$PASSWD" "$WORK/passwd.before-shell-repair" 0600; fi
        put "$next" "$PASSWD" "$(stat -c %a "$PASSWD")"
    fi
    rm -f "$next"
    safe "$home/.ssh/authorized_keys"
    if [ ! -e "$home/.ssh/authorized_keys" ] && [ -f "$WORK/login-authorized-keys" ]; then
        safe "$WORK/login-authorized-keys"
        put "$WORK/login-authorized-keys" "$home/.ssh/authorized_keys" 0600
    fi
    if [ -f "$home/.ssh/authorized_keys" ]; then chmod 0600 "$home/.ssh/authorized_keys"; fi
}
repair_shell() {
    [ -e /usr/sbin/mi-shell ] || return 0
    target_shell=$(readlink -f /usr/sbin/mi-shell)
    normal_shell=$(readlink -f /usr/bin/bash.bash 2>/dev/null || true)
    [ -x "$normal_shell" ] || normal_shell=$(readlink -f /bin/bash 2>/dev/null || true)
    [ -x "$normal_shell" ] || fail 'mi-shell 固件缺少可用 Bash'
    case "$normal_shell:$target_shell" in *[!a-zA-Z0-9_./:-]*) fail 'shell 路径包含不支持字符' ;; esac
    safe "$normal_shell"; safe "$target_shell"; safe "${SHELL_DROPIN%/*}"
    mkdir -p "${SHELL_DROPIN%/*}"
    conf=$(mktemp "$WORK/.shell-conf.XXXXXXXX")
    printf '[Service]\nBindReadOnlyPaths=%s:%s\n' "$normal_shell" "$target_shell" > "$conf"
    safe "$SHELL_DROPIN"
    if [ -e "$SHELL_DROPIN" ] && ! cmp -s "$conf" "$SHELL_DROPIN"; then
        rm -f "$conf"; fail '已有不同的 SSH shell 配置，已停止覆盖'
    fi
    put "$conf" "$SHELL_DROPIN" 0644; rm -f "$conf"
}
repair_host() {
    private_dir "$WORK/host"
    safe /etc/dropbear; mkdir -p /etc/dropbear
    host=/etc/dropbear/dropbear_rsa_host_key
    saved=$WORK/host/dropbear_rsa_host_key
    safe "$host"; safe "$saved"
    if [ ! -e "$host" ]; then
        if [ -s "$saved" ]; then
            put "$saved" "$host" 0600
        elif [ -s "$STATE/host/dropbear_rsa_host_key" ]; then
            safe "$STATE/host/dropbear_rsa_host_key"
            put "$STATE/host/dropbear_rsa_host_key" "$host" 0600
        else
            /usr/sbin/dropbearkey -t rsa -s 2048 -f "$host" >/dev/null 2>&1
            chmod 0600 "$host"
            printf '%s\n' '已生成新的 SSH 主机密钥，下次连接请核对指纹。'
        fi
    fi
    /usr/sbin/dropbearkey -y -f "$host" >/dev/null 2>&1 || fail '现有主机密钥无效，未覆盖'
    if [ ! -e "$saved" ]; then put "$host" "$saved" 0400; fi
}
install_boot() {
    worker=$1
    [ -f "$worker" ] || fail '缺少纯 Shell 开机复查程序'
    /bin/sh -n "$worker"
    safe "${BOOT_DROPIN%/*}"; safe /etc/cron.d
    mkdir -p "${BOOT_DROPIN%/*}" /etc/cron.d
    put "$worker" "$WORK/restore-ssh.sh" 0700
    conf=$(mktemp "$WORK/.boot-conf.XXXXXXXX")
    printf '[Service]\n# Restore SSH after the Xiaomi boot check when this drop-in is loaded.\nExecStartPost=/usr/bin/systemctl start dropbear.socket\n' > "$conf"
    put "$conf" "$BOOT_DROPIN" 0644
    printf 'SHELL=/bin/sh\nPATH=/usr/sbin:/usr/bin:/sbin:/bin\nMAILTO=""\n\n# Wait for the real boot-check completion, then perform bounded SSH rechecks.\n@reboot root /bin/sh /data/ssh-autostart-fix/restore-ssh.sh\n' > "$conf"
    put "$conf" "$CRON" 0644; rm -f "$conf"
    if [ -f "$home/.ssh/authorized_keys" ]; then put "$home/.ssh/authorized_keys" "$WORK/login-authorized-keys" 0600; fi
}
activate() {
    timeout 15 "$SYSTEMCTL" daemon-reload
    timeout 15 "$SYSTEMCTL" enable dropbear.socket
    timeout 15 "$SYSTEMCTL" reset-failed dropbear.socket || true
    timeout 15 "$SYSTEMCTL" start dropbear.socket
    timeout 15 "$SYSTEMCTL" reload crond.service || fail '无法重载 crond.service，开机恢复尚未验证'
    timeout 10 "$SYSTEMCTL" is-enabled --quiet dropbear.socket || fail 'SSH 未设置为开机启用'
    timeout 10 "$SYSTEMCTL" is-active --quiet dropbear.socket || fail 'SSH socket 未启动'
    loaded=$(timeout 10 "$SYSTEMCTL" show minas.boot_check.service -p DropInPaths --value)
    case "$loaded" in *"$BOOT_DROPIN"*) ;; *) fail '开机修复配置未被 systemd 加载' ;; esac
    if [ -f "$SHELL_DROPIN" ]; then
        loaded=$(timeout 10 "$SYSTEMCTL" show 'dropbear@minas-ssh-check.service' -p DropInPaths --value)
        case "$loaded" in *"$SHELL_DROPIN"*) ;; *) fail 'mi-shell 修复配置未被 systemd 加载' ;; esac
    fi
    safe "$PENDING"; rm -f "$PENDING"
    printf '%s\n' 'SSH socket 已启用；纯 Shell 开机恢复已安装。'
}
activation_state() {
    status_file=$(mktemp "$WORK/.activation.XXXXXXXX")
    printf '%s\n' "$1" > "$status_file"
    put "$status_file" "$WORK/shell-activation.status" 0600
    rm -f "$status_file"
}

WAIT_SECONDS=300
POLL_SECONDS=2
RECHECK_SECONDS=5
RECHECK_COUNT=12
BOOT_UNIT=minas.boot_check.service
SOCKET_UNIT=dropbear.socket

log() {
    logger -t ssh-autostart-fix -- "$*"
}
seconds() {
    read -r elapsed rest < /proc/uptime
    printf '%s\n' "${elapsed%%.*}"
}
boot_finished() {
    active= sub= start=0 end=0 result= job=
    state=$(timeout 8 /usr/bin/systemctl show "$BOOT_UNIT" \
        -p ActiveState -p SubState -p ExecMainStartTimestampMonotonic \
        -p ExecMainExitTimestampMonotonic -p Result -p Job 2>/dev/null) || return 1
    while IFS='=' read -r key value; do
        case "$key" in
            ActiveState) active=$value ;;
            SubState) sub=$value ;;
            ExecMainStartTimestampMonotonic) start=$value ;;
            ExecMainExitTimestampMonotonic) end=$value ;;
            Result) result=$value ;;
            Job) job=$value ;;
        esac
    done <<EOF_STATE
$state
EOF_STATE
    case "$start:$end" in *[!0-9:]*|:*|*:) return 1 ;; esac
    [ "$start" -gt 0 ] && [ "$end" -ge "$start" ] || return 1
    [ -z "$job" ] || [ "$job" = "0" ] || return 1
    case "$active:$sub" in
        active:exited|inactive:dead|failed:failed) return 0 ;;
        *) return 1 ;;
    esac
}
socket_active() {
    timeout 8 /usr/bin/systemctl is-active --quiet "$SOCKET_UNIT"
}
wait_for_boot() {
    while ! boot_finished; do
        if [ "$(seconds)" -ge "$deadline" ]; then
            log "ERROR: boot check did not finish within ${WAIT_SECONDS}s; SSH recovery aborted"
            return 1
        fi
        sleep "$POLL_SECONDS"
    done
}


shell_repair_main() {
[ "$(id -u)" = 0 ] || fail '需要已有的 NAS root 执行权限'
for tool in awk stat mktemp flock timeout cmp readlink; do command -v "$tool" >/dev/null || fail "NAS 缺少 $tool"; done
private_dir "$WORK"
safe /data/.minas-privileged
mkdir -p /data/.minas-privileged
chmod 0755 /data/.minas-privileged
private_dir "$STATE"
safe "$STATE/operations.lock"
exec 8>"$STATE/operations.lock"
flock -w 15 8 || fail '另一个 SSH 修复正在执行'
mode=${1:-}; shift || true
if [ "$mode" = --boot-repair ]; then
    prepare_account; repair_host; repair_shell
    timeout 15 "$SYSTEMCTL" daemon-reload
    exit 0
fi
if [ "$mode" = --activate ]; then
    # Consume the one-shot before waiting; a failed attempt must not become a
    # permanent minute-by-minute recovery loop. Portainer can queue it again.
    safe "$PENDING"; rm -f "$PENDING"
    trap 'result=$?; if [ "$result" -ne 0 ]; then activation_state failed; fi' EXIT
    deadline=$(( $(seconds) + WAIT_SECONDS )); wait_for_boot || fail "等待开机检查超时"
    prepare_account; repair_host; repair_shell; activate
    activation_state ready
    exit 0
fi
offline=0 user= public= worker=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --user) user=$2; shift 2 ;; --public-key) public=$2; shift 2 ;;
        --worker) worker=$2; shift 2 ;; --offline) offline=1; shift ;;
        *) fail "未知参数：$1" ;;
    esac
done
case "$mode" in --recover|--install-boot-only) ;; *) fail '请选择 --recover 或 --install-boot-only' ;; esac
for unit in minas.boot_check.service dropbear.socket 'dropbear@.service' crond.service; do
    if [ "$offline" = 1 ]; then
        [ -f "/usr/lib/systemd/system/$unit" ] || [ -f "/lib/systemd/system/$unit" ] || [ -f "/etc/systemd/system/$unit" ] || fail "固件缺少 $unit"
    else
        timeout 10 "$SYSTEMCTL" cat "$unit" >/dev/null || fail "固件缺少 $unit"
    fi
done
command -v crond >/dev/null || fail 'NAS 缺少 crond'
if [ "$offline" != 1 ]; then deadline=$(( $(seconds) + WAIT_SECONDS )); wait_for_boot || fail "等待开机检查超时"; fi
prepare_account
if [ "$mode" = --recover ]; then
    case "$user" in u*) digits=${user#u}; case "$digits" in ''|*[!0-9]*) fail 'NAS 账户无效' ;; esac ;; *) fail 'NAS 账户无效' ;; esac
    [ -d "/home/$user" ] || fail '指定 NAS 账户不存在'
    [ -f "$public" ] || fail '缺少 SSH 公钥'
    [ "$(awk 'NF {n++} END {print n+0}' "$public")" = 1 ] || fail '一次只能安装一条公钥'
    # Client derives and validates this key with ssh-keygen; reject options here.
    awk 'NF {if(NF!=2 || $1 !~ /^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521))$/ || $2 !~ /^[A-Za-z0-9+\/=]+$/) exit 1}' "$public" || fail '公钥格式无效'
    private_dir "$STATE"; private_dir "$STATE/keys"
    put "$public" "$STATE/keys/$user.pub" 0600
    merge_keys "$public" "$home/.ssh/authorized_keys"
fi
repair_host; repair_shell
install_boot "$worker"
if [ "$offline" = 1 ]; then
    conf=$(mktemp "$WORK/.activate.XXXXXXXX")
    printf 'SHELL=/bin/sh\nPATH=/usr/sbin:/usr/bin:/sbin:/bin\n* * * * * root /bin/sh /data/ssh-autostart-fix/restore-ssh.sh --activate 2>&1 | logger -t ssh-autostart-fix\n' > "$conf"
    put "$conf" "$PENDING" 0644; rm -f "$conf"
    activation_state pending
    printf '%s\n' '已准备恢复文件；等待宿主机 Cron 激活，再验证真实 SSH 命令。'
else
    activate
fi

}

boot_main() {
set +e
if [ "${1:-}" = "--check" ]; then
    if boot_finished && socket_active; then
        printf '%s\n' 'boot-check finished; dropbear.socket active'
        exit 0
    fi
    exit 1
fi

exec 9>/run/ssh-autostart-fix.lock
flock -n 9 || exit 0
deadline=$(( $(seconds) + WAIT_SECONDS ))
log "waiting for $BOOT_UNIT to finish (limit ${WAIT_SECONDS}s)"
wait_for_boot || exit 1
log "boot check finished: state=$active/$sub result=$result; checking SSH"
if ! timeout 30 /bin/sh "$0" --boot-repair; then
    log 'ERROR: SSH login material or mi-shell compatibility repair failed'
    exit 1
fi

i=0
while [ "$i" -le "$RECHECK_COUNT" ]; do
    # If the vendor check runs again during this short window, wait for it again.
    wait_for_boot || exit 1
    if ! socket_active; then
        if timeout 10 /usr/bin/systemctl start "$SOCKET_UNIT"; then
            log "dropbear.socket restored after boot check (check $i/$RECHECK_COUNT)"
        else
            log "WARNING: could not start dropbear.socket (check $i/$RECHECK_COUNT)"
        fi
    fi
    if [ "$i" -eq "$RECHECK_COUNT" ]; then
        if socket_active; then
            log "SSH recovery verified; bounded rechecks finished"
            exit 0
        fi
        log "ERROR: SSH remains inactive after bounded rechecks"
        exit 1
    fi
    i=$((i + 1))
    sleep "$RECHECK_SECONDS"
done

}

case "${1:-}" in
    --recover|--install-boot-only|--boot-repair|--activate) shell_repair_main "$@" ;;
    ""|--check) boot_main "$@" ;;
    *) fail "未知模式：$1" ;;
esac
