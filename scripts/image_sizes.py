#!/usr/bin/env python3
"""Record the disk usage of the o5gc/* images and compare two such snapshots.

  scripts/image_sizes.py snapshot FILE        write a snapshot (JSON) and print it
  scripts/image_sizes.py show FILE            print a snapshot
  scripts/image_sizes.py diff OLD NEW         compare two snapshots
  scripts/image_sizes.py diff OLD NEW -l      ... and the layers that changed

Per image (one entry per image ID; ":latest" and ":<version>" are the same):
  disk      bytes on disk, as "docker system df" counts them; with the
            containerd image store this is the unpacked layers plus the
            compressed blobs kept in the content store
  unique    disk minus the part shared with any other image (incl. dangling)
  unpacked  sum of the uncompressed layers, base image included

Totals:
  o5gc unpacked  uncompressed layers of all o5gc images, shared layers once
  all images     disk usage of all images ("docker system df"), incl. non-o5gc
  dangling       what "docker image prune" would free; it distorts "unique"
                 and "all images", so prune before taking a snapshot

Build the images before and after a change back-to-back with the same build
cache; unchanged layers then come from the cache and only the changed ones
differ.
"""
import argparse
import difflib
import http.client
import json
import os
import re
import socket
import sys
from datetime import datetime
from urllib.parse import quote

PREFIX = "o5gc/"


class UnixHTTPConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__("localhost")
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(self.path)


def api(path):
    sock = os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock")
    if not sock.startswith("unix://"):
        sys.exit(f"only unix sockets are supported, DOCKER_HOST={sock}")
    conn = UnixHTTPConnection(sock[len("unix://"):])
    conn.request("GET", path)
    resp = conn.getresponse()
    body = resp.read()
    if resp.status != 200:
        sys.exit(f"docker API {path}: {resp.status} {body.decode()}")
    return json.loads(body)


def short_cmd(created_by):
    cmd = created_by.removesuffix(" # buildkit")
    cmd = re.sub(r"^RUN \|\d+ (\S+=\S* )*", "RUN ", cmd)
    cmd = cmd.replace("/bin/bash -o pipefail -c ", "")
    cmd = cmd.replace("/bin/sh -c #(nop) ", "")
    return re.sub(r"\s+", " ", cmd).strip()


def layers_of(image_id):
    """Uncompressed layers (diff ID, size, command), base first.

    The history has no layer IDs, so its entries with a size are mapped onto
    RootFS.Layers by position. Returns None if the counts do not match.
    """
    inspect = api(f"/images/{quote(image_id)}/json")
    diff_ids = inspect["RootFS"]["Layers"]
    history = [h for h in reversed(api(f"/images/{quote(image_id)}/history"))
               if h["Size"] > 0]
    if len(history) != len(diff_ids):
        return inspect, None
    return inspect, [{"diff_id": d, "size": h["Size"],
                      "cmd": short_cmd(h["CreatedBy"])}
                     for d, h in zip(diff_ids, history)]


def snapshot():
    df = api("/system/df?type=image")
    version = api("/version")
    images, dangling, layer_sizes = {}, [], {}
    repos = {}

    for img in df["Images"]:
        tags = [t for t in img.get("RepoTags") or [] if t != "<none>:<none>"]
        if not tags:
            dangling.append(img["Size"] - img["SharedSize"])
            continue
        o5gc_tags = sorted(t for t in tags if t.startswith(PREFIX))
        if o5gc_tags:
            repos.setdefault(o5gc_tags[0].rsplit(":", 1)[0], []).append(
                (img, o5gc_tags))

    for repo, entries in repos.items():
        for img, tags in entries:
            if len(entries) == 1 or f"{repo}:latest" in tags:
                key = repo
            else:
                key = next(t for t in tags if t.startswith(repo + ":"))
            inspect, layers = layers_of(img["Id"])
            if layers is None:
                print(f"warning: {key}: layers not mapped, counted as unique",
                      file=sys.stderr)
                layer_sizes[img["Id"]] = sum(
                    h["Size"] for h in api(f"/images/{quote(img['Id'])}/history"))
            else:
                layer_sizes.update((l["diff_id"], l["size"]) for l in layers)
            images[key] = {
                "id": img["Id"],
                "tags": tags,
                "created": datetime.fromtimestamp(img["Created"]).isoformat(),
                "version": (inspect["Config"].get("Labels") or {}).get(
                    "org.opencontainers.image.version"),
                "disk": img["Size"],
                "unique": img["Size"] - img["SharedSize"],
                "unpacked": sum(l["size"] for l in layers or []) or None,
                "layers": layers or [],
            }

    return {
        "created": datetime.now().isoformat(timespec="seconds"),
        "docker": version.get("Version"),
        "totals": {
            "o5gc_unpacked": sum(layer_sizes.values()),
            "all_images_disk": df["LayersSize"],
            "dangling_count": len(dangling),
            "dangling_disk": sum(dangling),
        },
        "images": dict(sorted(images.items())),
    }


def fmt(n, signed=False):
    if n is None:
        return "-"
    sign = ("+" if n > 0 else "-" if n < 0 else " ") if signed else ""
    n = abs(n)
    for unit, div in (("GB", 1e9), ("MB", 1e6), ("kB", 1e3)):
        if n >= div:
            return f"{sign}{n / div:.2f} {unit}" if unit == "GB" \
                else f"{sign}{n / div:.0f} {unit}"
    return f"{sign}{n} B"


def pct(old, new):
    return f"{(new - old) / old * 100:+.0f}%" if old >= 1e6 else ""


def print_totals(totals):
    print(f"o5gc unpacked (shared once)  {fmt(totals['o5gc_unpacked']):>10}")
    print(f"all images on disk           {fmt(totals['all_images_disk']):>10}")
    print(f"dangling images ({totals['dangling_count']:3})        "
          f"{fmt(totals['dangling_disk']):>10}")


def show(snap):
    print(f"snapshot {snap['created']}, docker {snap['docker']}\n")
    print(f"{'image':<32} {'version':<20} {'disk':>10} {'unique':>10} {'unpacked':>10}")
    for key, img in snap["images"].items():
        print(f"{key:<32} {img['version'] or '':<20} {fmt(img['disk']):>10} "
              f"{fmt(img['unique']):>10} {fmt(img['unpacked']):>10}")
    print()
    print_totals(snap["totals"])
    if snap["totals"]["dangling_count"]:
        print("\nnote: dangling images distort 'unique' and 'all images', "
              "run 'docker image prune' first")


def diff_layers(old, new):
    a = [l["cmd"] for l in old["layers"]]
    b = [l["cmd"] for l in new["layers"]]
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if tag == "equal":
            for o, n in zip(old["layers"][i1:i2], new["layers"][j1:j2]):
                if o["size"] != n["size"]:
                    yield n["size"] - o["size"], "~", n["cmd"]
            continue
        for o in old["layers"][i1:i2]:
            yield -o["size"], "-", o["cmd"]
        for n in new["layers"][j1:j2]:
            yield n["size"], "+", n["cmd"]


def diff(old, new, layers):
    print(f"old {old['created']}  ->  new {new['created']}\n")
    print(f"{'image':<32} {'unique old':>10} {'new':>10} {'delta':>10} {'':>5}"
          f" {'unpacked old':>12} {'new':>10} {'delta':>10}")
    for key in sorted(old["images"].keys() | new["images"].keys()):
        o, n = old["images"].get(key), new["images"].get(key)
        if not o or not n:
            print(f"{key:<32} {'only in ' + ('old' if o else 'new')}")
            continue
        if o["unique"] == n["unique"] and o["unpacked"] == n["unpacked"]:
            continue
        print(f"{key:<32} {fmt(o['unique']):>10} {fmt(n['unique']):>10} "
              f"{fmt(n['unique'] - o['unique'], True):>10} "
              f"{pct(o['unique'], n['unique']):>5} "
              f"{fmt(o['unpacked']):>12} {fmt(n['unpacked']):>10} "
              f"{fmt((n['unpacked'] or 0) - (o['unpacked'] or 0), True):>10}")
        if o["version"] != n["version"]:
            print(f"{'':<4}version changed: {o['version']} -> {n['version']}")
        if layers and o["id"] != n["id"]:
            for delta, mark, cmd in diff_layers(o, n):
                if abs(delta) >= 1e6:
                    print(f"{'':<4}{mark} {fmt(delta, True):>10}  {cmd[:100]}")
    print()
    ot, nt = old["totals"], new["totals"]
    for label, k in (("o5gc unpacked (shared once)", "o5gc_unpacked"),
                     ("all images on disk", "all_images_disk"),
                     ("dangling images", "dangling_disk")):
        print(f"{label:<28} {fmt(ot[k]):>10} -> {fmt(nt[k]):>10} "
              f"{fmt(nt[k] - ot[k], True):>10} {pct(ot[k], nt[k]):>5}")
    if ot["dangling_count"] or nt["dangling_count"]:
        print("\nnote: dangling images distort 'unique' and 'all images', "
              "run 'docker image prune' before each snapshot")


def load(path):
    with open(path) as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("snapshot", help="write a snapshot of the o5gc images")
    p.add_argument("file")
    p = sub.add_parser("show", help="print a snapshot")
    p.add_argument("file")
    p = sub.add_parser("diff", help="compare two snapshots")
    p.add_argument("old")
    p.add_argument("new")
    p.add_argument("-l", "--layers", action="store_true",
                   help="list the layers that changed (>= 1 MB)")
    args = parser.parse_args()

    if args.cmd == "snapshot":
        snap = snapshot()
        with open(args.file, "w") as f:
            json.dump(snap, f, indent=1)
        show(snap)
    elif args.cmd == "show":
        show(load(args.file))
    else:
        diff(load(args.old), load(args.new), args.layers)


if __name__ == "__main__":
    main()
