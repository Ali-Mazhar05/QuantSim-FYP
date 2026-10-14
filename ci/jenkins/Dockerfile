# QuantSim Jenkins controller: the LTS image with pinned plugins and configuration as
# code. It runs no builds itself (see agent/); the Docker CLI is kept for maintenance.
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

# Configuration as code lives outside JENKINS_HOME so a rebuilt image always applies it.
# compose.yml selects casc/security/<JENKINS_AUTH>.yaml next to the shared jenkins.yaml.
COPY casc/ /usr/share/jenkins/casc/
ENV CASC_JENKINS_CONFIG=/usr/share/jenkins/casc/jenkins.yaml,/usr/share/jenkins/casc/security/local.yaml \
    JAVA_OPTS="-Djenkins.install.runSetupWizard=false -Xmx1g"
