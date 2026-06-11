# Pins a newer signal-cli than the one baked into the published bridge image.
#
# STOPGAP: this uses signal-cli 0.14.5-SNAPSHOT — a CI build (AsamK/signal-cli
# commit b3c1b6a, run 27307093674) that fixes the serverGuid receive crash. As of
# 2026-06-10 the Signal server stopped sending `serverGuid` on sealed-sender
# envelopes, and signal-cli's non-null assertion dropped ALL incoming messages
# (signal-cli#2059); this affected every released version (0.14.2–0.14.4.1), so a
# downgrade was not an option. The snapshot tarball lives in vendor/.
#
# Once the official 0.14.5 release is published, replace the COPY below with a
# curl from GitHub releases (see git history for the release-fetch variant) and
# delete vendor/signal-cli-0.14.5-SNAPSHOT.tar.gz.
ARG SIGNAL_CLI_VERSION=0.14.5-SNAPSHOT

FROM bbernhard/signal-cli-rest-api:latest
ARG SIGNAL_CLI_VERSION
COPY vendor/signal-cli-${SIGNAL_CLI_VERSION}.tar.gz /tmp/signal-cli.tar.gz
RUN tar xzf /tmp/signal-cli.tar.gz -C /opt \
 && rm /tmp/signal-cli.tar.gz \
 && ln -sf /opt/signal-cli-${SIGNAL_CLI_VERSION}/bin/signal-cli /usr/bin/signal-cli \
 && signal-cli --version
