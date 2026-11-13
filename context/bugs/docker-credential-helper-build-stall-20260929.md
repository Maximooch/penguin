# Docker public-image build stalls in credential helper

September 29, 2026: Link CI amd64 image build stayed in metadata resolution
for more than two minutes. Process inspection showed docker-buildx waiting on
docker-credential-desktop. Python HTTP checks reached the public registry.
Stopped only the build/helper processes and retried with a temporary Docker
config without credsStore, explicitly targeting the Desktop socket. Build and
push succeeded. Normal ~/.docker/config.json was not changed. Root cause of
credential-helper stall is unconfirmed; not evidence of Penguin context failure.
