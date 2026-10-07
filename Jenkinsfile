// QuantSim pipeline. This file only orchestrates: every step calls a script in
// ci/scripts, which can also be run on a laptop. See docs/ci-cd.md.
//
//   feature/*, bugfix/*, PRs   checks only
//   develop                    checks, build missing images, deploy DEV
//   test                       checks, promote develop's images, deploy TEST
//   acceptance                 checks, promote, deploy ACC, human sign-off
//   main                       checks, approval, promote, deploy PROD, release tag
//   hotfix/*                   checks and build, reaches main through a pull request

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

def approve(String message) {
  timeout(time: 24, unit: 'HOURS') {
    input message: message, ok: 'Approve', submitter: env.QS_APPROVERS
  }
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
      agent any
      environment {
        // Registry login lives in the workspace and is deleted with it
        DOCKER_CONFIG = "${WORKSPACE}/.ci/docker"
        BUILDX_CONFIG = "${JENKINS_HOME}/.buildx"
      }
      options { timeout(time: 45, unit: 'MINUTES') }

      stages {
        stage('Prepare') {
          steps {
            checkout scm
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
              parallel checks
            }
          }
          post {
            always {
              junit allowEmptyResults: true, testResults: 'libs/*/reports/junit.xml, services/*/reports/junit.xml'
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
              for (c in env.QS_COMPONENTS.tokenize(' ')) {
                sh "ci/scripts/promote.sh '${c}' '${env.QS_ENV}'"
              }
            }
          }
        }
      }

      post {
        always {
          archiveArtifacts artifacts: '.ci/plan.env', allowEmptyArchive: true
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
      agent any
      environment {
        DOCKER_CONFIG = "${WORKSPACE}/.ci/docker"
      }
      options { timeout(time: 20, unit: 'MINUTES') }
      steps {
        checkout scm
        lock(resource: "env-${env.QS_ENV}") {
          script {
            ghcrLogin()
            withCredentials([
              file(credentialsId: 'sops-age-key', variable: 'SOPS_AGE_KEY_FILE'),
              string(credentialsId: 'cloudflare-api-token', variable: 'CLOUDFLARE_API_TOKEN'),
              string(credentialsId: 'cloudflare-account-id', variable: 'CLOUDFLARE_ACCOUNT_ID'),
            ]) {
              sh 'ci/scripts/make-release.sh "$QS_ENV" .ci/release.env'
              try {
                sh 'ci/scripts/deploy.sh "$QS_ENV" .ci/release.env'
                sh 'ci/scripts/smoke.sh "$QS_ENV" .ci/release.env'
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
          cleanWs(deleteDirs: true, notFailBuild: true)
        }
      }
    }

    stage('Acceptance sign-off') {
      when { beforeAgent true; branch 'acceptance' }
      steps {
        script {
          def accepted = true
          try {
            approve("ACC is serving v${env.QS_VERSION} (frontend ${env.HASH_FRONTEND}). Accept it for production?")
          } catch (err) {
            accepted = false
          }
          node {
            checkout scm
            withGitHub {
              def state = accepted ? 'success' : 'failure'
              def text = accepted ? 'Accepted for production' : 'Rejected or timed out at acceptance'
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
      agent any
      environment {
        DOCKER_CONFIG = "${WORKSPACE}/.ci/docker"
      }
      options { timeout(time: 10, unit: 'MINUTES') }
      steps {
        checkout scm
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
