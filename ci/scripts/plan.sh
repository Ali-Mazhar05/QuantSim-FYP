#!/usr/bin/env bash
# Works out what this build has to do and writes it as KEY=VALUE lines.
#   usage: plan.sh <branch> <output-file>
#
# Output:
#   QS_ENV, QS_MODE      from env-for-branch.sh
#   QS_VERSION, QS_GIT_SHA
#   QS_COMPONENTS        every component, space separated
#   HASH_<COMPONENT>     content hash of each component
#   QS_BUILD_LIST        components whose image is missing (build mode)
#   QS_MISSING_LIST      components whose image is missing (promote mode, an error)
#   QS_AUTO_APPROVE      true when AUTO_APPROVE=true in deploy/env/<env>.env, so the
#                        ACC sign-off or the PROD approval passes without a person
source "$(dirname "$0")/lib.sh"

branch="${1:?usage: plan.sh <branch> <output-file>}"
out="${2:?usage: plan.sh <branch> <output-file>}"

mkdir -p "$(dirname "$out")"

read -r qs_env qs_mode < <("$(dirname "$0")/env-for-branch.sh" "$branch")

# Only an exact "true" skips the approval; anything else, or no setting, asks a person
auto_approve=false
if [[ "$qs_env" != "none" ]]; then
  setting="$(sed -n 's/^AUTO_APPROVE=//p' "$(env_file "$qs_env")" | tr -d '\r' | tail -1)"
  [[ "$setting" == "true" ]] && auto_approve=true
fi

components=()
build_list=()
missing_list=()
hash_lines=()

while read -r name; do
  components+=("$name")
  hash="$("$(dirname "$0")/content-hash.sh" "$name")"
  hash_lines+=("HASH_$(component_var "$name")=$hash")

  [[ "$qs_mode" == "ci" ]] && continue

  status=0
  "$(dirname "$0")/image-exists.sh" "$(image_repo "$name"):$hash" || status=$?
  case "$status" in
    0) log "$name: image $hash exists" ;;
    1) log "$name: image $hash missing"
       build_list+=("$name"); missing_list+=("$name") ;;
    3) if [[ "$qs_mode" == "build" ]]; then
         log "$name: registry denied the lookup, assuming the package has never been pushed"
         build_list+=("$name")
       else
         die "$name: registry denied the lookup; check the ghcr-push credential"
       fi ;;
    *) die "$name: could not check the registry" ;;
  esac
done < <(component_names)

{
  echo "QS_BRANCH=$branch"
  echo "QS_ENV=$qs_env"
  echo "QS_MODE=$qs_mode"
  echo "QS_VERSION=$(project_version)"
  echo "QS_GIT_SHA=$(git -C "$REPO_ROOT" rev-parse HEAD)"
  echo "QS_COMPONENTS=${components[*]}"
  echo "QS_AUTO_APPROVE=$auto_approve"
  printf '%s\n' "${hash_lines[@]}"
  echo "QS_BUILD_LIST=${build_list[*]}"
  echo "QS_MISSING_LIST=$([[ "$qs_mode" == "promote" ]] && echo "${missing_list[*]}")"
} > "$out"

log "plan for $branch: env=$qs_env mode=$qs_mode"
cat "$out" >&2
