# docker_open5gs vs. open5Gcube — what to reuse, what to add, what to improve

## Context

You asked me to analyse herlesupreeth/docker_open5gs (as of 2026-10-25: about 586 stars, BSD-2, very active, about 150 commits since 2025, nearly all by the maintainer) and to recommend:
- ideas open5Gcube can reuse,
- sub-projects open5Gcube could add,
- where open5Gcube can improve compared with docker_open5gs.

open5Gcube's VoLTE setup is already "inspired by docker_open5gs" (`Doc/stacks.md`).

This file holds the analysis plus a prioritised list of work packages. Once you approve it, pick which work packages to implement. Each one is meant to become one commit on main.

---

## 1. Where each project is stronger

**docker_open5gs is a voice- and IMS-centric single-core lab.** It is stronger in:
- VoNR: the Kamailio P-CSCF talks **N5** to the PCF through the SCP (`DEPLOY_MODE=5G` swaps `WITH_RX` for `WITH_N5`), plus ViLTE/ViNR video.
- PyHSS as the IMS HSS, with a REST API, Cx/Sh and Redis.
- An alternative IMS on **OpenSIPS 3.6** (P/I/S-CSCF), including OpenSIPS VoNR.
- **VoWiFi**: osmo-epdg with strongswan-epdg (EAP-AKA, SWm, S2b), and the SWu-IKEv2 emulator as a test UE.
- An **IBCF/PSTN trunk with voicemail** on Asterisk 22 with the EVS and AMR codecs.
- **Online charging** with Sigscale OCS over Gy.
- **eUPF**, an eBPF UPF, as a drop-in replacement for the Open5GS UPF.
- A **slicing** deployment: 2 SMF + 2 UPF, 2 SDs, NSSF.
- **CI that publishes prebuilt images** to GHCR (17 images), so users don't have to build.
- `TROUBLESHOOTING.md`: a symptom-first runbook with a **handset compatibility matrix** (CoIMS, iPhone with 00101, Xiaomi SA codes, Quectel), canonical pySim commands and `sim/*.script` files (iPhone SUCI/UST, deactivating 5G, read-all).
- Metrics for more network functions: AMF, SMF, PCF, UPF, MME, PCRF and HSS.

**open5Gcube is clearly stronger in the following areas, and these are worth keeping:**
- **Breadth:** 2G Osmocom; 4G and 5G with many core × RAN combinations (Open5GS, free5GC, OAI CN5G, Ella Core); OCUDU with a CU/DU split; PacketRusher; roaming with SEPP on main.
- **Infrastructure:**
  - layered env files rendered by `envsubst`, where docker_open5gs patches configs with `sed`
  - **automatic subscriber provisioning** from `uedb.env` for every core; docker_open5gs needs manual WebUI or REST steps
  - multi-host DooD
  - the WebUI with a SIM writer
  - the build cacher
  - Robot Framework end-to-end tests, including SDR
  - lint targets
  - version pinning everywhere, with multi-version builds; docker_open5gs has no releases and only a `:master` tag
- **Analysis tools:** LTESniffer, FALCON, NR-Scope, SigDigger.

**Gaps in open5Gcube compared with docker_open5gs:**
- No VoNR with Open5GS + Kamailio.
- PyHSS is built but not wired into any stack.
- No VoWiFi, OpenSIPS, IBCF, OCS or eUPF.
- No slicing stack.
- No CI and no prebuilt images.
- Metrics only on 3 stacks.
- No handset or troubleshooting documentation.
- P-CSCF TLS is disabled. IPsec is already on (`kamailio/pcscf/pcscf.cfg:123`).

---

## 2. Recommended work packages (prioritised)

### P1. VoNR stack: `srsran-open5gs-5g-volte` (renamed `-vonr`), plus an emulated variant

This has the highest research value. The IMS pieces already exist; only the 5G policy path is new.
- Add the N5 path to `modules/o5gc/docker/volte/kamailio/pcscf/`. Port the `WITH_N5` route logic and the `http_client`/`nghttp2`/`jansson` module setup from docker_open5gs (`pcscf/kamailio_pcscf.cfg`, `pcscf/route/*.cfg`, `pcscf.cfg`).
- Switch between Rx and N5 with an env var in `kamailio/entrypoint.sh`, the same way docker_open5gs uses `DEPLOY_MODE`. The Kamailio pin in `kamailio/Dockerfile` must include the needed modules; compare it with commit `9874599e`.
- Open5GS side: give the PCF an IMS DNN policy with 5QI 5 for signalling and 5QI 1/2 GBR for voice and video (from docker_open5gs `pcf/pcf.yaml`). Add the `ims` DNN to the SMF/UPF in 5G mode (that part already exists for 4G).
- New stack `modules/o5gc/stacks/srsran-open5gs-5g-vonr/`, built like `srsran-open5gs-4g-volte` (compose `extends:` from `volte/services.yaml`). Add an `-emu` variant with srsUE NR over ZMQ for the IMS registration test.
- Tests: an `ims.robot` that checks IMS registration (P-CSCF/S-CSCF log regex). Reuse the keywords in `tests/common.resource`.

### P2. Make PyHSS a selectable HSS, with FHoSS kept as an option

The `volte-pyhss` image (1.0.2) already exists.
- Add `pyhss` services to the volte compose profile.
- Provision subscribers automatically from `UE_DB` in a new `pyhss/init-subscribers.sh`. Order: APN → AUC → subscriber → ims_subscriber. Use the REST calls documented in the docker_open5gs README, and `call_for_each_subscriber` from `modules/base/docker/o5gc/core-init.sh`.
- Choose the HSS through `IMS_HSS=fhoss|pyhss` in the stack's `settings.env`.
- Payoff: no Java dependency, Sh support, and the same HSS docker_open5gs uses, so it is easier to follow upstream fixes.

### P3. CI and prebuilt images (GitHub Actions → GHCR)

- Add `.github/workflows/`:
  - (a) a `make lint` job; all linters already run in Docker
  - (b) a build matrix over the `docker-build-<proj>` targets
  - (c) on main or tags, push `ghcr.io/open5gcube/<image>:<version>` using the existing `/etc/image_version` tag logic in the `Makefile` (`define docker-build`)
- Add a `docker-pull-all` make target with a `USE_PREBUILT_IMAGES=1` switch, so the "few hours" build is optional.
- Optional (d): a nightly job that runs `tests-run-all-Emulated` on a GitHub runner. UERANSIM and PacketRusher stacks don't need SDRs. free5GC needs gtp5g, so leave it out.

### P4. Metrics for all Open5GS stacks

- Enable the `metrics` profile (already in `modules/o5gc/docker/open5gs/metrics/services.yaml`) on every Open5GS-based stack, not just 3.
- Extend `prometheus.yaml` to scrape MME, PCRF, HSS and PCF as well, as docker_open5gs does.
- Extend `dashboard.json` with 4G panels (eNBs, MME sessions).

### P5. Troubleshooting and handset docs

- Add `Doc/troubleshooting.md` and `Doc/handsets.md` to mkdocs, so they also show in the WebUI.
- Content to adapt from docker_open5gs `TROUBLESHOOTING.md` (BSD-2, credit it):
  - the CoIMS/VoLTE enable notes per vendor
  - the iPhone 00101 PLMN limitation
  - SA toggles
  - the Quectel RM520N modem
  - the harmless-log-lines list
- Add the pySim-shell scripts under `modules/base/docker/simcard/` (or `rs-o5gc`) and make them selectable in the WebUI's script upload: `iphone-private-5g.script`, `deactivate-5g.script`, `readall-5g.script`.

### P6. New sub-projects, in order of value for a research lab

1. **eUPF** (`modules/o5gc/docker/eupf/`):
   - Go/eBPF, pinned to a commit.
   - Add the stack `ueransim-open5gs-eupf` (or a `UPF_IMPL=eupf` switch). Works with Open5GS, and is likely to work with free5GC and OAI too.
   - Good for UPF performance comparisons.
2. **Slicing stack** `ueransim-open5gs-slicing`:
   - 2 SMF + 2 UPF, 2 SDs, NSSF, two UEs with different `NSSAI_SD`.
   - Copy the topology from docker_open5gs `custom_deployments/slicing/`.
   - Fits the existing `UE_SOFT_MSIN_n` mechanism.
3. **VoWiFi / ePDG** (`modules/o5gc/docker/epdg/`):
   - osmo-epdg plus strongswan-epdg, with the SWu-IKEv2 client as a soft UE.
   - Stack `open5gs-4g-vowifi` with a test that needs no SDR, which fits CI (P3).
   - Use upstream osmo-epdg where possible, because docker_open5gs depends on the maintainer's forks.
4. **OpenSIPS IMS** as an alternative CSCF implementation (`IMS_IMPL=kamailio|opensips`). Useful for comparison studies; experimental upstream.
5. **IBCF / Asterisk with EVS/AMR**: a PSTN or SIP-trunk gateway with voicemail. Lower priority; the EVS reference code has licence restrictions, so check before redistributing images.
6. **Sigscale OCS** (Gy online charging): niche, low priority.

### P7. Smaller improvements inspired by docker_open5gs

- **P-CSCF TLS / WebSocket (WebRTC clients):** make them toggleable through env, not by editing the cfg.
- **SUCI:** docker_open5gs ships UDM home-network keys (profile A/B). Check whether the Open5GS stacks configure `hnet` keys by default; `rs-o5gc/enable-suci.script` already exists for the SIM side.
- **DNS NAPTR records** for IMS (upstream #617) in `volte/dns` zone templates.
- **Wireshark key export:** dump IPsec/IKE keys to a shared volume for decrypting IMS IPsec, as docker_open5gs does for IKE.
- **Core-side pcap sidecar** (`tcpdump` on `corenet`, behind a `capture` profile): neither project has one, so this goes beyond docker_open5gs.

### Explicitly *not* worth copying

- `sed`-based templating and the static single /24 IP plan; open5Gcube's envsubst plus `networks.env` is better.
- Manual subscriber provisioning.
- The `:master`-only image tags and having no releases.
- The OAI eNB/gNB images, which are unmaintained there.

---

## 3. Critical files (for later implementation)

- `modules/o5gc/docker/volte/{services.yaml,kamailio/entrypoint.sh,kamailio/pcscf/*.cfg,pyhss/}`
- `modules/o5gc/docker/open5gs/{services.yaml,pcf*,smf*,metrics/}`
- `modules/base/docker/o5gc/core-init.sh` (`call_for_each_subscriber`)
- `modules/o5gc/stacks/srsran-open5gs-4g-volte/` (template for the VoNR stack)
- `Makefile` (`define docker-build`, image version tags), `modules/o5gc/targets.mk`
- `tests/common.resource`, `tests/targets.mk`
- `Doc/` (mkdocs nav)

## 4. Verification (for each package once implemented)

- `make lint` passes.
- `make docker-build-<proj>` succeeds for new or changed images.
- `make tests-run-<stack>` passes for new stacks:
  - emulated variants (ZMQ, UERANSIM, SWu client) in a full end-to-end run
  - VoNR on SDR with a real handset (IMS registration, then MO/MT call), noted in `Doc/handsets.md`
- CI: the workflow runs green on a test push, and the image appears in GHCR.
- Existing VoLTE stack: re-run `tests-run-srsran-open5gs-4g-volte` after the Kamailio and PyHSS changes, as a regression check.
