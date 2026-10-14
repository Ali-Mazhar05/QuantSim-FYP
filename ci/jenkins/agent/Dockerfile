# QuantSim build agent: the Jenkins SSH agent plus the Docker CLI (buildx, compose),
# jq and curl. The controller connects to it over SSH on the private compose network
# and runs every build here.
FROM jenkins/ssh-agent:latest-jdk21@sha256:8298f5861edfb274bbb460f7d17a4ff14e8b73ac644b633fbe3671ad1264485f

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg jq \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
 && chmod a+r /etc/apt/keyrings/docker.asc \
 && . /etc/os-release \
 && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/debian ${VERSION_CODENAME} stable" \
      > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends docker-ce-cli docker-buildx-plugin docker-compose-plugin \
 && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /usr/local/bin/quantsim-agent-entrypoint
RUN chmod 0755 /usr/local/bin/quantsim-agent-entrypoint

ENTRYPOINT ["/usr/local/bin/quantsim-agent-entrypoint"]
