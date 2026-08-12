# Python Media Echo Agent

This Agent performs a real, visible Pillow transformation: a red inset border and `WorkWorld`
watermark. It downloads the winner-visible input Artifact, uploads the output through the MinIO
multipart flow, and submits the resulting Artifact ID. No model or fake media processing is used.

The Python test suite also starts this file as an independent process against an HTTP/WebSocket
contract server, transfers a real PNG through the SDK, and verifies the transformed output bytes,
digest, multipart ETag, and result envelope. This contract test does not replace the Compose
MinIO/ClamAV acceptance run.
