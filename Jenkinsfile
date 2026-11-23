// QuantSim pipeline. This file only orchestrates: every step calls a script in
// ci/scripts, which can also be run on a laptop. See docs/ci-cd.md.
//
//   feature/*, bugfix/*, PRs   checks only
//   develop                    checks, build missing images, deploy DEV
//   test                       checks, promote develop's images, deploy TEST
//   acceptance                 checks, promote, deploy ACC, human sign-off
//   main                       checks, approval, promote, deploy PROD, release tag
//   hotfix/*                   checks and build, reaches main through a pull request
//
// Every checkout goes through qsCheckout(): the build host's link to GitHub can be slow
// and drop mid-clone, so builds borrow objects from a mirror on the agent's volume.

// A bare mirror of the repository on the agent's persistent volume. Checkouts borrow its
// objects (git alternates), so a build downloads only commits newer than the mirror.
// The first build on a new host fills it once.
MIRROR = '/home/jenkins/agent/git-mirror/QuantSim-FYP.git'

def qsCheckout() {
  // Refresh the mirror under a lock (several builds share it). A failed refresh is not
  // fatal, and a mirror that is not a valid bare repository (e.g. a half-finished seed)
  // is removed and cloned again.
  sh """
    set +e
    mirror='${MIRROR}'
    mkdir -p "\$(dirname "\$mirror")"
    (
      command -v flock >/dev/null && flock -w 960 9
      if [ -e "\$mirror" ] && [ "\$(git -C "\$mirror" rev-parse --is-bare-repository 2>/dev/null)" != true ]; then
        echo "mirror at \$mirror is not a valid repository; removing it"
        rm -rf "\$mirror"
      fi
      if [ -d "\$mirror" ]; then
        timeout 600 git -C "\$mirror" fetch --prune --quiet origin || echo "mirror refresh failed; continuing"
      else
        rm -rf "\$mirror.tmp"
        # Bounded, so a very slow link cannot use up the build; a later build tries again
        timeout 900 git clone --mirror --quiet https://github.com/Ali-Mazhar05/QuantSim-FYP.git "\$mirror.tmp" \\
          && mv "\$mirror.tmp" "\$mirror" || echo "mirror clone failed; checking out without it"
      fi
    ) 9>"\$mirror.lock"
    exit 0
  """
  // Borrow from the mirror only when it is a usable repository
  def mirrorOk = sh(
    script: "test \"\$(git -C '${MIRROR}' rev-parse --is-bare-repository 2>/dev/null)\" = true",
    returnStatus: true,
  ) == 0
  def clone = [$class: 'CloneOption', noTags: true, shallow: false, timeout: 30]
  if (mirrorOk) {
    clone.reference = MIRROR
  } else {
    echo 'checking out without the mirror'
  }
  retry(3) {
    checkout([
      $class: 'GitSCM',
      branches: scm.branches,
      userRemoteConfigs: scm.userRemoteConfigs,
      extensions: scm.extensions + [clone],
    ])
  }
}

def ghcrLogin() {
  withCredentials([usernamePassword(credentialsId: 'ghcr-push', usernameVariable: 'GHCR_USER', passwordVariable: 'GHCR_TOKEN')]) {
    sh 'echo "$GHCR_TOKEN" | docker login ghcr.io --username "$GHCR_USER" --password-stdin'
  }
}

def withGitHub(Closure body) {
  withCredentials([usernamePassword(credentialsId: 'github-app', usernameVariable: 'GITHUB_APP', passwordVariable: 'GITHUB_TOKEN')]) {
    body()
  }
}

// Returns true when a person approved, false when AUTO_APPROVE=true in
// deploy/env/<env>.env let it through; throws when rejected or timed out
def approve(String message) {
  if (env.QS_AUTO_APPROVE == 'true') {
    echo "Auto-approved: AUTO_APPROVE=true in deploy/env/${env.QS_ENV}.env (${message})"
    return false
  }
  timeout(time: 24, unit: 'HOURS') {
    input message: message, ok: 'Approve', submitter: env.QS_APPROVERS
  }
  return true
}

pipeline {
  agent none

  options {
    timestamps()
    disableConcurrentBuilds()
    buildDiscarder(logRotator(numToKeepStr: '30', artifactNumToKeepStr: '10'))
    skipDefaultCheckout()
    // Approval gates may wait up to a day; every working stage has its own limit
    timeout(time: 26, unit: 'HOURS')
  }

  stages {
    stage('Build') {
      agent { label 'docker' }
      environment {
        // Registry login lives in the workspace and is deleted with it
        DOCKER_CONFIG = "${WORKSPACE}/.ci/docker"
      }
      options { timeout(time: 45, unit: 'MINUTES') }

      stages {
        stage('Prepare') {
          steps {
            script { qsCheckout() }
            // A-NFR-15: free space on the host (WARNING under 20 GB); advisory, never fails
            sh 'ci/scripts/disk-check.sh || true'
            script {
              def qsMode = sh(script: "ci/scripts/env-for-branch.sh '${env.BRANCH_NAME}'", returnStdout: true).trim().tokenize(' ')[1]
              if (qsMode != 'ci') {
                ghcrLogin()
              }
              sh "ci/scripts/plan.sh '${env.BRANCH_NAME}' .ci/plan.env"
              def plan = readProperties(file: '.ci/plan.env')
              for (key in (plan.keySet() as List)) {
                env."${key}" = plan[key] ?: ''
              }
              // Read here, on a node, so the approval stages can use it without one
              env.QS_APPROVERS = env.RELEASE_APPROVERS ?: 'admin'

              currentBuild.displayName = "#${env.BUILD_NUMBER} ${env.QS_ENV} ${env.HASH_FRONTEND}"
              currentBuild.description = "${env.QS_MODE} | v${env.QS_VERSION} | ${env.QS_GIT_SHA.substring(0, 12)}"

              if (env.BRANCH_NAME == 'main') {
                withGitHub { sh 'ci/scripts/release-tag.sh check' }
              }
            }
          }
        }

        stage('Pipeline scripts') {
          steps {
            sh 'ci/scripts/shellcheck.sh'
          }
        }

        stage('Frontend CI') {
          steps {
            sh 'ci/scripts/frontend-ci.sh'
          }
          post {
            always {
              junit allowEmptyResults: true, testResults: 'frontend/reports/junit.xml'
              script {
                if (fileExists('frontend/coverage/cobertura-coverage.xml')) {
                  recordCoverage(id: 'frontend', name: 'Frontend coverage',
                                 tools: [[parser: 'COBERTURA', pattern: 'frontend/coverage/cobertura-coverage.xml']],
                                 sourceCodeRetention: 'NEVER')
                }
              }
            }
          }
        }

        stage('Backend CI') {
          steps {
            script {
              // Every Python project: shared libraries in libs/, services in services/
              def projects = []
              for (f in findFiles(glob: 'libs/*/pyproject.toml')) {
                def parts = f.path.tokenize('/')
                projects << "${parts[0]}/${parts[1]}"
              }
              for (f in findFiles(glob: 'services/*/pyproject.toml')) {
                def parts = f.path.tokenize('/')
                projects << "${parts[0]}/${parts[1]}"
              }
              if (projects.isEmpty()) {
                echo 'No Python projects yet, nothing to check'
                return
              }
              def checks = [:]
              for (p in projects) {
                def project = p
                checks[project] = {
                  sh "ci/scripts/python-ci.sh '${project}'"
                  if (project.startsWith('services/')) {
                    sh "ci/scripts/migration-check.sh '${project.tokenize('/')[1]}'"
                  }
                }
              }
              // Each check starts its own Docker network, about a dozen per build, and the
              // host's address pools hold about 30 next to the DEV/TEST/ACC/PROD stacks. Since
              // the webhook starts a push's branch build and its pull request build at once,
              // builds take turns here instead of running out of networks ("all predefined
              // address pools have been fully subnetted", PR-167)
              lock(resource: 'backend-ci-networks') {
                parallel checks
              }
            }
          }
          post {
            always {
              junit allowEmptyResults: true, testResults: 'libs/*/reports/junit.xml, services/*/reports/junit.xml'
              script {
                if (findFiles(glob: 'services/*/reports/coverage.xml').length > 0) {
                  recordCoverage(id: 'backend', name: 'Backend coverage',
                                 tools: [[parser: 'COBERTURA', pattern: 'services/*/reports/coverage.xml']],
                                 sourceCodeRetention: 'NEVER')
                }
              }
            }
          }
        }

        stage('Build images') {
          when { expression { env.QS_MODE == 'build' && env.QS_BUILD_LIST?.trim() } }
          steps {
            script {
              for (c in env.QS_BUILD_LIST.tokenize(' ')) {
                sh "ci/scripts/build-push.sh '${c}'"
              }
            }
          }
        }

        stage('Promote images') {
          when { expression { env.QS_ENV != 'none' } }
          steps {
            script {
              if (env.QS_MISSING_LIST?.trim()) {
                error("Not built on develop: ${env.QS_MISSING_LIST}. Merge the change into develop first so it is built and verified there.")
              }
              // PROD's tag moves only after the approval, in Deploy, so a rejected release
              // never becomes "prod"
              if (env.QS_ENV != 'prod') {
                for (c in env.QS_COMPONENTS.tokenize(' ')) {
                  sh "ci/scripts/promote.sh '${c}' '${env.QS_ENV}'"
                }
              }
            }
          }
        }
      }

      post {
        always {
          archiveArtifacts artifacts: '.ci/plan.env', allowEmptyArchive: true
          // Leftover test containers and old cache would otherwise fill the host's disk
          sh 'ci/scripts/sweep.sh || true'
          cleanWs(deleteDirs: true, notFailBuild: true)
        }
      }
    }

    stage('Approve production') {
      when { beforeAgent true; branch 'main' }
      steps {
        script {
          approve("Deploy v${env.QS_VERSION} (frontend ${env.HASH_FRONTEND}) to production?")
        }
      }
    }

    stage('Deploy') {
      when { beforeAgent true; expression { env.QS_ENV != 'none' } }
      agent { label 'docker' }
      environment {
        DOCKER_CONFIG = "${WORKSPACE}/.ci/docker"
      }
      options { timeout(time: 20, unit: 'MINUTES') }
      steps {
        script { qsCheckout() }
        lock(resource: "env-${env.QS_ENV}") {
          script {
            ghcrLogin()
            withCredentials([
              file(credentialsId: 'sops-age-key', variable: 'SOPS_AGE_KEY_FILE'),
              string(credentialsId: 'cloudflare-api-token', variable: 'CLOUDFLARE_API_TOKEN'),
              string(credentialsId: 'cloudflare-account-id', variable: 'CLOUDFLARE_ACCOUNT_ID'),
            ]) {
              if (env.QS_ENV == 'prod') {
                for (c in env.QS_COMPONENTS.tokenize(' ')) {
                  sh "ci/scripts/promote.sh '${c}' prod"
                }
              }
              sh 'ci/scripts/make-release.sh "$QS_ENV" .ci/release.env'
              try {
                sh 'ci/scripts/deploy.sh "$QS_ENV" .ci/release.env'
                sh 'ci/scripts/smoke.sh "$QS_ENV" .ci/release.env'
                // Playwright gates: a red run fails the deploy, so the environment's
                // verified status (required on the next promotion PR) is never set. They
                // sign in as test.admin, whose password the gate decrypts from the
                // environment's secrets with the sops-age-key bound above
                def gates = [dev: 'dev-smoke', test: 'demo-spine']
                if (gates[env.QS_ENV]) {
                  sh "ci/scripts/playwright-gate.sh '${env.QS_ENV}' '${gates[env.QS_ENV]}'"
                }
                // DEV only, last: runs a portfolio through the trading API and engine on
                // the bundled demo market data and checks its event chain. A failure
                // fails the deploy, so DEV is not verified
                if (env.QS_ENV == 'dev') {
                  sh 'ci/scripts/trading-live-check.sh dev'
                }
              } catch (err) {
                if (env.QS_ENV in ['acc', 'prod']) {
                  echo "Deploy to ${env.QS_ENV} failed, rolling back to the last known-good release"
                  catchError(buildResult: 'FAILURE', stageResult: 'FAILURE') {
                    sh 'ci/scripts/rollback.sh "$QS_ENV" current'
                  }
                }
                error("Deploy to ${env.QS_ENV} failed: ${err.message}")
              }
              sh 'ci/scripts/record-release.sh "$QS_ENV" .ci/release.env'
            }
          }
        }
        script {
          // Branch protection requires these on the next promotion pull request
          def contexts = [dev: 'quantsim/dev-verified', test: 'quantsim/test-verified']
          if (contexts[env.QS_ENV]) {
            withGitHub {
              sh "ci/scripts/github-status.sh '${contexts[env.QS_ENV]}' success '${env.QS_ENV.toUpperCase()} deployed and smoke tested'"
            }
          }
        }
      }
      post {
        always {
          archiveArtifacts artifacts: '.ci/release.env', allowEmptyArchive: true
          junit allowEmptyResults: true, testResults: 'frontend/reports/e2e-*.xml'
          cleanWs(deleteDirs: true, notFailBuild: true)
        }
      }
    }

    stage('Acceptance sign-off') {
      when { beforeAgent true; branch 'acceptance' }
      steps {
        script {
          def accepted = true
          def byPerson = true
          try {
            byPerson = approve("ACC is serving v${env.QS_VERSION} (frontend ${env.HASH_FRONTEND}). Accept it for production?")
          } catch (err) {
            accepted = false
          }
          node('docker') {
            qsCheckout()
            withGitHub {
              def state = accepted ? 'success' : 'failure'
              def text = !accepted ? 'Rejected or timed out at acceptance'
                : (byPerson ? 'Accepted for production' : 'Accepted automatically (AUTO_APPROVE)')
              sh "ci/scripts/github-status.sh quantsim/acceptance-signoff '${state}' '${text}'"
            }
            cleanWs(deleteDirs: true, notFailBuild: true)
          }
          if (!accepted) {
            currentBuild.result = 'ABORTED'
            error('Acceptance was rejected or timed out')
          }
        }
      }
    }

    stage('Release') {
      when { beforeAgent true; branch 'main' }
      agent { label 'docker' }
      environment {
        DOCKER_CONFIG = "${WORKSPACE}/.ci/docker"
      }
      options { timeout(time: 10, unit: 'MINUTES') }
      steps {
        script { qsCheckout() }
        script {
          ghcrLogin()
          for (c in env.QS_COMPONENTS.tokenize(' ')) {
            sh "ci/scripts/promote.sh '${c}' 'v${env.QS_VERSION}'"
          }
          withGitHub { sh 'ci/scripts/release-tag.sh create' }
          currentBuild.displayName = "#${env.BUILD_NUMBER} v${env.QS_VERSION}"
        }
      }
      post {
        always {
          cleanWs(deleteDirs: true, notFailBuild: true)
        }
      }
    }
  }
}
