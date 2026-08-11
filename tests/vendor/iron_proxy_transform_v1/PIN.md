# Vendored: Iron `transform.v1` contract (pinned upstream source)

This fixture captures the exact upstream TransformService contract DAGR
interoperates with at the pinned Iron commit.

- Source repo: `https://github.com/paradigmxyz/iron-proxy`
- Commit: `564f7bac971dd3d3f077c23a7aaa7484671ed39f`
- License: `Apache-2.0`
- Proto path: `proto/transform/v1/transform.proto`
- gRPC shim path: `internal/transform/grpc/grpc.go`

The vendored proto text is byte-for-byte the upstream file at that commit.
The gRPC shim itself is not vendored; its source path and digest are pinned in
`SOURCE_MANIFEST.json` for provenance and drift detection.
