#! /bin/bash

set -ex

# will be set by base.Dockerfile
USE_BUILD_CACHER=0

# without the build-cacher, upload only removes the caches from the image
BUILD_HOST=$(cat /etc/build_host)

for cache in "${@:3}"; do
    [ "$cache" == "ccache" ] && dir=/root/.ccache
    [ "$cache" == "sccache" ] && dir=/root/.cache/sccache
    [ "$cache" == "cargo-registry" ] && dir=/root/.cargo/registry
    [ "$cache" == "npm-cache" ] && dir=/root/.npm/_cacache
    [ "$cache" == "go-cache-dl" ] && dir=/root/go/pkg/mod/cache/download
    [ "$cache" == "go-cache-build" ] && dir=/root/.cache/go-build
    case "$1" in
        download)
            # create it anyway, so that ccache uses it and upload removes it
            mkdir -p ${dir}
            [ ${USE_BUILD_CACHER} -ne 0 ] || continue
            rsync -a -O --no-perms --mkpath ${dir}/ rsync://o5gc-build-cacher:40860/${cache}/${BUILD_HOST}/$2
            rsync -a rsync://o5gc-build-cacher:40860/${cache}/${BUILD_HOST}/$2/ ${dir}
            ;;
        upload)
            [ ${USE_BUILD_CACHER} -eq 0 ] ||                                  \
                rsync -a -O --no-perms ${dir}/ rsync://o5gc-build-cacher:40860/${cache}/${BUILD_HOST}/$2
            rm -rf ${dir}
            if [ "$cache" == "go-cache-dl" ]; then
                rm -rf /root/go/pkg/mod
            fi
            ;;
    esac
done
