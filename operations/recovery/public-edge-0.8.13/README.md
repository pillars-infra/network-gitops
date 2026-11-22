# PublicEdge 0.8.13 cache warmup

Use the same reviewed, temporary, token-free recovery procedure as
[0.8.12](../public-edge-0.8.12/README.md), before this release rollout.
The two Pod objects bind only suxunji/domain-ex and the exact signed 0.8.13 image
from product source `4ee2a95ba2394dd2012971cd1d881392fbfbf112`.
Verify completion, then delete both Pods through platform preview/delete.
Do not add them to the production root or rebuild/retag the image.
