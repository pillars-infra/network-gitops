# R640 Cilium Gateway recovery — 2026-10-19

## Final state

Network Flux owns the existing Cilium Helm release and reconciles independently
from main Flux. The fixed Cilium operator, R640 agent, Gateway and public data
path all converged without the emergency admission freeze or iptables guard.

The authoritative path remains:

`223.159.210.222 -> RouterOS DNAT/eBGP -> 10.251.0.4/Cilium Gateway`

`192.168.88.251` remains the declared R640 fallback backend.
`10.181.22.128` is a routing/service identity and must not replace the public
authority in an externally advertised Gateway.

## Root cause

The route, certificate and Envoy SNI configuration were valid. Direct TLS to
R640 Envoy worked while the Gateway VIP reset, isolating the fault to the
`LoadBalancer VIP -> BPF L7 redirect -> Envoy` path.

Cilium `1.21.0-dev` generated semantically identical Envoy route lists in
different orders. The CEC reached generation 1,188,066, approximately 1,332
Gateway reconciles occurred in two minutes, and Envoy processed roughly 15,000
RDS updates. Agent restarts during this control-plane storm exposed a broken L7
redirect state. `Programmed=True` remained set because the controller checked
address validity, not the live TLS/BPF/Envoy path.

The R640 return path also inherited the chart-wide legacy
`egress-masquerade-interfaces=eth0` setting. eBPF masquerade rejects that
legacy selector and requires `devices` instead. Omitting the node override did
not delete the setting; CiliumNodeConfig inherited it from `cilium-config`.

## Durable configuration

- Operator ordering fix:
  `b790b432054017f157d678d9f6f1619ae0dc046c`
- Operator image digest:
  `sha256:5a003fb797d490c2f9557cbd0ef4129a7d6ef20cb803f66e668a4cd8d2a894fb`
- R640 device: `eno2np1`
- R640 acceleration: native XDP
- R640 masquerading: eBPF
- R640 legacy selector override: `egress-masquerade-interfaces: ""`
- Helm chart strategy: `ChartVersion`
- Unconditional agent rollout: disabled
- Upgrade wait on every DaemonSet pod: disabled
- Upgrade remediation retries: zero

The empty legacy selector is intentional. Removing the key reintroduces the
global `eth0` value and prevents the R640 agent from starting.

## Verification

```sh
python3 policies/validate.py
kubectl kustomize clusters/re8ch >/tmp/network-render.yaml

kubectl get kustomization -n flux-network-system domain
kubectl get helmrelease -n flux-network-system cilium
kubectl get gateway -n kube-system re8ch-gateway-canary
kubectl get ciliumenvoyconfig -n kube-system \
  cilium-gateway-re8ch-gateway-canary

kubectl exec -n kube-system <r640-cilium-pod> -c cilium-agent -- \
  cilium-dbg status --verbose

curl -ksS --resolve headlamp.service.re8ch.com:443:10.251.0.4 \
  -o /dev/null -w '%{http_code}\n' https://headlamp.service.re8ch.com/
curl -ksS --resolve headlamp.service.re8ch.com:443:223.159.210.222 \
  -o /dev/null -w '%{http_code}\n' https://headlamp.service.re8ch.com/
```

Require Network Flux and the Cilium HelmRelease to be Ready. Gateway conditions
must be current, the R640 agent must report native acceleration, BPF host
routing and BPF masquerading on `eno2np1`, and the CEC generation/spec hash
must remain stable when inputs do not change. Both traffic probes must reach the
expected application response.

HTTP 502 has a narrower meaning than connection reset: TLS, VIP and Envoy are
working, but the selected application backend is unavailable. Inspect the
HTTPRoute backend, EndpointSlice and target node instead of changing the public
route or restoring the emergency guard.

## Offline-node behavior

A failed WSL worker or control-plane node must not turn a successful CNI apply
into a cluster-wide rollback. Helm therefore completes after applying the
release objects without waiting for every DaemonSet pod. Kubernetes node
conditions, leases and observability remain the authority for per-node health.

Windows host power, Windows SSH transport, WSL reachability, local K3s/etcd
readiness and Kubernetes node readiness are separate signals. An SSH
authentication failure does not prove the Windows host is unreachable; a
powered-on Windows host does not prove its WSL guest is healthy.

## Change record

- `pillars-infra/network-gitops#15`: fixed operator, Cilium adoption and staged
  R640 datapath change.
- `pillars-infra/network-gitops#16`: clear the inherited legacy masquerade
  selector.
- `pillars-infra/network-gitops#17`: stop revision-driven chart upgrades and
  unconditional agent rollouts.
- `pillars-infra/network-gitops#18`: remove the emergency proxy-return guard.
- `pillars-infra/network-gitops#19`: decouple Helm completion from offline
  workers and remove rollback loops.
- `re8ch/service-backend#1972`, `#1973`, `#1974`: exact Network Flux Cilium and
  chart RBAC.
