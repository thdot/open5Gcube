#! /bin/bash

# Allow root logins with the o5gc SSH key (var/ssh/ on the host).
# The keys are not part of the images, so containers running sshd have to
# mount var/ssh/ and call this script before starting sshd.

set -e

SRC=${1:-/var/run/ssh}

if [ ! -f ${SRC}/id_ed25519.pub ]; then
    echo "install-ssh-keys.sh: no SSH key in ${SRC}, skipping"
    exit 0
fi

install -d -m 0700 /root/.ssh
cat ${SRC}/id_ed25519.pub $(ls ${SRC}/authorized_keys 2>/dev/null)            \
    | sort -u > /root/.ssh/authorized_keys
chmod 0600 /root/.ssh/authorized_keys
