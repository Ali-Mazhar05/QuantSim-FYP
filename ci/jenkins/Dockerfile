# QuantSim Jenkins controller: the LTS image plus the Docker CLI (with the buildx and
# compose plugins) and jq. Every pipeline tool beyond these runs in a pinned container
# started by the CI scripts, so Jenkins itself stays small.
FROM jenkins/jenkins:2.580.1-lts

USER root
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
USER jenkins

# Plugins are pinned in plugins.txt and installed at build time, never from the UI
COPY --chown=jenkins:jenkins plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt

# Configuration as code lives outside JENKINS_HOME so a rebuilt image always applies it
COPY casc.yaml /usr/share/jenkins/casc/jenkins.yaml
ENV CASC_JENKINS_CONFIG=/usr/share/jenkins/casc \
    JAVA_OPTS="-Djenkins.install.runSetupWizard=false -Xmx1g"
