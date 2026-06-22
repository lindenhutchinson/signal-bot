# Layers a pinned signal-cli over the upstream signal-cli-rest-api image.
#
# We pin 0.14.5 (the first RELEASED build with the serverGuid fix — see
# signal-cli#2059). The upstream rest-api image lags signal-cli releases, so we
# fetch the official release tarball from GitHub and swap the bundled binary.
# Pulled by checksum so a tampered/replaced asset fails the build.
#
# To bump: change SIGNAL_CLI_VERSION + SIGNAL_CLI_SHA256 (get the hash with
# `curl -fsSL <url> | sha256sum`). No vendored artifact, so CI builds this cleanly.
ARG SIGNAL_CLI_VERSION=0.14.5
ARG SIGNAL_CLI_SHA256=62d38ebfef3988d78f437e7328183b75ee549d111382e66c1af70d3ebd3cd7a7

FROM bbernhard/signal-cli-rest-api:latest
ARG SIGNAL_CLI_VERSION
ARG SIGNAL_CLI_SHA256
ADD --checksum=sha256:${SIGNAL_CLI_SHA256} \
    https://github.com/AsamK/signal-cli/releases/download/v${SIGNAL_CLI_VERSION}/signal-cli-${SIGNAL_CLI_VERSION}.tar.gz \
    /tmp/signal-cli.tar.gz
RUN tar xzf /tmp/signal-cli.tar.gz -C /opt \
 && rm /tmp/signal-cli.tar.gz \
 && ln -sf /opt/signal-cli-${SIGNAL_CLI_VERSION}/bin/signal-cli /usr/bin/signal-cli \
 && signal-cli --version
